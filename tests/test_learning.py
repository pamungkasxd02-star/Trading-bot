import json
import time
from decimal import Decimal

import pandas as pd
import pytest

from spotlab.config import AppConfig, DemoConfig
from spotlab.exchange import BinanceAPIError, PublicMarketClient
from spotlab.journal import TradingJournal
from spotlab.learning import DemoAccount, DemoEngine
from spotlab.models import SymbolRules


@pytest.fixture
def demo(tmp_path):
    cfg = AppConfig(
        demo=DemoConfig(database=tmp_path / "demo.db", kill_switch_file=tmp_path / "STOP")
    )
    account = DemoAccount(cfg)
    account.start()
    rules = {
        "BTCUSDT": SymbolRules(
            "BTCUSDT",
            Decimal("0.001"),
            Decimal("100000"),
            Decimal("0.001"),
            Decimal("0.01"),
            Decimal("5"),
        )
    }
    engine = DemoEngine(account, rules)
    yield account, engine
    if account.owner:
        account.stop()


def entry_row(**updates):
    return {
        "close_time": pd.Timestamp(time.time() - 2, unit="s", tz="UTC"),
        "enter_long": True,
        "exit_long": False,
        "signal_score": 90,
        "signal_reason": "test_cross",
        "close": 100,
        "volume": 1000000,
        **updates,
    }


def quote(price=100):
    return [{"symbol": "BTCUSDT", "bidPrice": price, "askPrice": price + 0.01}]


def test_fills_only_after_signal_and_pnl_includes_costs(demo):
    account, engine = demo
    row = entry_row()
    engine.signal("BTCUSDT", row)
    assert account.status()["position"] is None
    engine.quotes(quote())
    pos = account.status()["position"]
    assert pos["entry_price"] > 100.01
    assert 0 < pos["stop_price"] < pos["entry_price"] < pos["take_profit_price"]
    engine.signal("BTCUSDT", row)  # replay cannot create a second decision
    assert account.status()["records"]["signal"] == 1
    engine.quotes(quote(96))
    result = account.status()
    assert result["position"] is None
    assert result["trade_count"] == 1
    assert result["realized_pnl"] == pytest.approx(result["cash"] - 1000)
    gross_without_fees = (96 - pos["entry_price"]) * pos["quantity"]
    assert result["realized_pnl"] < gross_without_fees
    assert result["counts_toward_paper_gate"] is False
    engine.quotes(quote(96))
    assert account.status()["trade_count"] == 1


def test_restart_retains_balance_and_closes_unobserved_position(demo):
    account, engine = demo
    engine.signal("BTCUSDT", entry_row())
    engine.quotes(quote())
    cash = account.status()["cash"]
    account.stop()
    account.start()
    assert account.status()["cash"] == cash
    engine.quotes(quote(99))
    assert account.status()["trade_count"] == 1
    with account.connect() as conn:
        trade = json.loads(
            conn.execute("SELECT payload FROM demo_records WHERE kind='trade'").fetchone()[0]
        )
    assert trade["exit_reason"] == "resume_exit_unobserved_gap"


def test_stale_or_future_signals_cannot_buy(demo):
    account, engine = demo
    engine.signal(
        "BTCUSDT", entry_row(close_time=pd.Timestamp(time.time() - 3600, unit="s", tz="UTC"))
    )
    engine.quotes(quote())
    engine.signal(
        "BTCUSDT", entry_row(close_time=pd.Timestamp(time.time() + 60, unit="s", tz="UTC"))
    )
    engine.quotes(quote())
    assert account.status()["position"] is None
    assert account.status()["records"].get("order", 0) == 0


def test_risk_halt_keeps_collecting_quotes(demo):
    account, engine = demo
    account.config.demo.kill_switch_file.touch()
    engine.signal("BTCUSDT", entry_row())
    engine.quotes(quote())
    engine.quotes(quote())
    assert account.status()["halt_reason"] == "manual_stop_trading"
    assert account.status()["records"]["quote"] == 2
    assert account.status()["position"] is None


def test_lease_fences_old_process_and_atomic_rollback(demo):
    account, _ = demo
    second = DemoAccount(account.config)
    with pytest.raises(RuntimeError, match="proses lain"):
        second.start()
    with pytest.raises(ValueError), account.edit() as (conn, state):
        state["cash"] = 1
        account.record(conn, "order", "BTCUSDT", {"side": "BUY"})
        raise ValueError("crash before commit")
    assert account.status()["cash"] == 1000
    assert account.status()["records"].get("order", 0) == 0
    with account.connect() as conn:
        conn.execute("UPDATE demo_account SET heartbeat=0")
    second.start()
    with pytest.raises(RuntimeError, match="Lease"):
        account.heartbeat()
    account.owner = ""
    second.stop()


def test_export_and_demo_do_not_credit_testnet_gate(demo, tmp_path):
    account, engine = demo
    engine.signal("BTCUSDT", entry_row())
    engine.quotes(quote())
    engine.quotes(quote(96))
    destination = account.export(tmp_path / "export")
    assert pd.read_csv(destination / "trade.csv").iloc[0]["mode"] == "demo"
    assert (destination / "learning.db").exists()
    journal = TradingJournal(account.database)
    assert journal.paper_runtime_seconds() == 0
    assert journal.trade_rows("paper") == []


def test_public_transport_rejects_orders_even_with_credentials():
    client = PublicMarketClient()
    with pytest.raises(BinanceAPIError, match="public market data"):
        client.order(symbol="BTCUSDT", side="BUY")
    with pytest.raises(BinanceAPIError, match="public market data"):
        client.account()
    client.api_key = "do-not-send"
    with pytest.raises(BinanceAPIError, match="credential-free"):
        client.klines("BTCUSDT", "1m")


def test_demo_balance_is_not_reset_by_initialization(demo):
    account, engine = demo
    engine.signal("BTCUSDT", entry_row())
    engine.quotes(quote())
    before = account.status()["cash"]
    account.initialize()
    assert account.status()["cash"] == before
    with pytest.raises(ValueError, match="Akun sudah ada"):
        account.initialize(10000)


def test_quote_outage_is_not_claimed_as_continuous_protection(demo):
    account, engine = demo
    engine.signal("BTCUSDT", entry_row())
    engine.quotes(quote())
    with account.edit() as (_, state):
        state["quote_times"]["BTCUSDT"] = time.time() - 300
    engine.quotes(quote(98))
    assert account.status()["position"] is None
    assert account.status()["trade_count"] == 1


def test_demo_cli_never_loads_exchange_secrets(tmp_path, monkeypatch, capsys):
    from spotlab import cli

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_file = config_dir / "demo.yaml"
    config_file.write_text("demo:\n  initial_cash: 2500\n")

    def reject_credentials():
        raise AssertionError("Demo must not load .env credentials")

    monkeypatch.setattr(cli, "Secrets", reject_credentials)
    cli.main(["--config", str(config_file), "demo-init"])
    assert json.loads(capsys.readouterr().out)["cash"] == 2500
    assert not (tmp_path / "data/runtime.db").exists()
