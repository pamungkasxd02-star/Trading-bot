import asyncio
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pandas as pd
import pytest

from spotlab.config import AppConfig, RuntimeConfig
from spotlab.data import MarketDataStore
from spotlab.exchange import TESTNET_REST, BinanceAPIError
from spotlab.execution.broker import BinanceBroker
from spotlab.execution.paper import TestnetPaperBroker as PaperBroker
from spotlab.execution.realtime import RealtimeRunner
from spotlab.journal import TradingJournal
from spotlab.models import SymbolRules
from spotlab.strategies.base import Strategy


class FakeExchange:
    base_url = TESTNET_REST

    def __init__(self):
        self.buys, self.ocos, self.sells = [], [], []
        self.fail_oco = False

    def account(self):
        return {"canTrade": True, "balances": [{"asset": "USDT", "free": "1000", "locked": "0"}]}

    def book_ticker(self, symbol):
        price = 100 if symbol == "BTCUSDT" else 200
        return {"bidPrice": str(price), "askPrice": str(price + 0.01)}

    def order(self, **kwargs):
        (self.buys if kwargs["side"] == "BUY" else self.sells).append(kwargs)
        price = float(self.book_ticker(kwargs["symbol"])["askPrice"])
        quantity = float(kwargs["quantity"])
        return {
            "orderId": "123",
            "status": "FILLED",
            "executedQty": str(quantity),
            "cummulativeQuoteQty": str(price * quantity),
            "fills": [{"price": str(price), "commissionAsset": "USDT", "commission": "0.1"}],
        }

    def create_oco(self, **kwargs):
        if self.fail_oco:
            raise BinanceAPIError("fixture OCO rejected")
        self.ocos.append(kwargs)
        return {"orderListId": "9", "orderReports": [{"orderId": "10"}, {"orderId": "11"}]}

    def query_order(self, symbol, order_id):
        return {"status": "NEW"}


class FixtureStrategy(Strategy):
    def prepare(self, candles):
        frame = candles.copy()
        frame["enter_long"], frame["exit_long"] = True, False
        frame["signal_score"] = frame["close"]
        frame["signal_reason"] = "fixture"
        return frame


class SilentNotifier:
    def send(self, message):
        pass


def make_runner(tmp_path):
    client = FakeExchange()
    store = MarketDataStore(tmp_path / "market.db")
    journal = TradingJournal(tmp_path / "runtime.db")
    cfg = AppConfig(
        runtime=RuntimeConfig(database=journal.database, kill_switch_file=tmp_path / "KILL")
    )
    brokers = {}
    for symbol in ("BTCUSDT", "ETHUSDT"):
        rules = SymbolRules(
            symbol,
            Decimal("0.001"),
            Decimal("100"),
            Decimal("0.001"),
            Decimal("0.01"),
            Decimal("5"),
        )
        store.save_symbol_rules(rules)
        brokers[symbol] = PaperBroker(client, rules, expected_testnet=True)
    runner = RealtimeRunner(
        mode="paper",
        config=cfg,
        strategy=FixtureStrategy(),
        store=store,
        journal=journal,
        broker=brokers["BTCUSDT"],
        brokers=brokers,
        notifier=SilentNotifier(),
        fingerprint="fixture",
    )
    return runner, client


def test_realtime_batch_places_only_best_pair_with_oco_and_deduplicates(tmp_path):
    runner, client = make_runner(tmp_path)
    close = pd.Timestamp(datetime.now(UTC) - timedelta(seconds=10)).floor("ms")
    opening = close - timedelta(hours=4, milliseconds=-1)
    batch = {}
    for symbol, price in (("BTCUSDT", 100), ("ETHUSDT", 200)):
        dates = pd.date_range(end=opening - timedelta(hours=4), periods=5, freq="4h")
        runner.histories[symbol] = pd.DataFrame(
            {
                "open_time": dates,
                "close_time": dates + timedelta(hours=4, milliseconds=-1),
                "open": price,
                "high": price + 1,
                "low": price - 1,
                "close": price,
                "volume": 1_000_000,
            }
        )
        runner.seen[symbol], runner.marks[symbol] = time.monotonic(), price
        batch[symbol] = {
            "symbol": symbol,
            "open_time": int(opening.timestamp() * 1000),
            "close_time": int(close.timestamp() * 1000),
            "open": price,
            "high": price + 1,
            "low": price - 1,
            "close": price,
            "volume": 1_000_000,
        }
    session = runner.journal.start_session("paper", fingerprint="fixture")

    async def process():
        await runner._process_batch(session, batch)
        await runner._process_batch(session, batch)

    asyncio.run(process())
    assert len(client.buys) == len(client.ocos) == 1
    assert client.buys[0]["symbol"] == "ETHUSDT"
    assert float(client.ocos[0]["stop_price"]) < 200 < float(client.ocos[0]["take_profit_price"])
    assert runner.journal.load_position("paper")["symbol"] == "ETHUSDT"
    assert runner.journal.pending_intent("paper") is None


def test_pending_intent_blocks_restart_before_any_new_order(tmp_path):
    runner, client = make_runner(tmp_path)
    runner.journal.set_intent("paper", {"action": "BUY", "client_order_id": "uncertain"})
    with pytest.raises(RuntimeError, match="intent"):
        asyncio.run(runner.run())
    assert client.buys == []


def test_oco_rejection_triggers_flatten_and_keeps_error(tmp_path):
    runner, client = make_runner(tmp_path)
    client.fail_oco = True
    with pytest.raises(BinanceAPIError):
        runner.broker.enter(
            symbol="BTCUSDT",
            base_asset="BTC",
            quantity=Decimal("0.1"),
            stop_price=Decimal("95"),
            take_profit_price=Decimal("110"),
            entry_time=datetime.now(UTC).isoformat(),
            reason="fixture",
        )
    assert len(client.buys) == len(client.sells) == 1


def test_quote_fee_converts_third_asset_and_respects_zero_commission(tmp_path):
    runner, _ = make_runner(tmp_path)
    broker = BinanceBroker(runner.broker.client, runner.broker.rules, expected_testnet=True)
    fee, base = broker._quote_fee(
        {"fills": [{"commission": "0.01", "commissionAsset": "BNB"}]}, "BTC"
    )
    assert fee == pytest.approx(2.0001)
    assert base == 0
    assert (
        broker._quote_fee(
            {
                "cummulativeQuoteQty": "100",
                "fills": [{"commission": "0", "commissionAsset": "BNB"}],
            },
            "BTC",
        )[0]
        == 0
    )


def test_paper_broker_rejects_actual_production_endpoint(tmp_path):
    runner, client = make_runner(tmp_path)
    client.base_url = "https://api.binance.com/api"
    with pytest.raises(RuntimeError, match="production"):
        runner.broker.validate_account()
