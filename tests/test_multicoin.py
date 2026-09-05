import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from spotlab.config import AppConfig, BacktestConfig, RiskConfig, StrategyConfig, UniverseConfig
from spotlab.data import parse_symbol_rules
from spotlab.gates import paper_gate, research_gate
from spotlab.indicators import completed_daily_trend
from spotlab.journal import TradingJournal
from spotlab.models import SymbolRules
from spotlab.portfolio import PortfolioBacktester
from spotlab.quality import validate_candles
from spotlab.research.walkforward import research_fingerprint, wilson_interval
from spotlab.risk import RiskManager, RiskViolation
from spotlab.selection import ranked_entries
from spotlab.strategies.adaptive import AdaptiveTrendStrategy
from spotlab.strategies.base import Strategy
from spotlab.universe import select_universe, spread_bps


def bars(count=6):
    dates = pd.date_range("2025-01-01", periods=count, freq="4h", tz="UTC")
    close = 100 + np.sin(np.arange(count) / 10) * 2
    return pd.DataFrame(
        {
            "open_time": dates,
            "close_time": dates + timedelta(hours=4, milliseconds=-1),
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": 1_000_000.0,
            "enter_long": [True] + [False] * (count - 1),
            "exit_long": False,
            "signal_reason": "fixture",
            "signal_score": 50.0,
        }
    )


def rule(symbol="BTCUSDT"):
    return SymbolRules(
        symbol, Decimal("0.001"), Decimal("100000"), Decimal("0.001"), Decimal("0.01"), Decimal("5")
    )


class Prepared(Strategy):
    def prepare(self, candles):
        return candles.copy()


def test_multicoin_shares_cash_and_ranks_simultaneous_entries():
    btc, eth = bars(), bars()
    eth["signal_score"] = 80
    engine = PortfolioBacktester(
        Prepared(),
        BacktestConfig(initial_cash=1000),
        RiskConfig(),
        {"BTCUSDT": rule(), "ETHUSDT": rule("ETHUSDT")},
    )
    result = engine.run({"BTCUSDT": btc, "ETHUSDT": eth})
    assert len(result.trades) == 1
    assert result.trades.iloc[0].symbol == "ETHUSDT"
    assert result.trades.iloc[0].entry_time == eth.iloc[1].open_time
    assert result.equity.iloc[0].equity == 1000
    assert result.metrics.total_fees > 0


def test_gap_through_stop_is_filled_at_worse_open():
    data = bars()
    data.loc[2, ["open", "high", "low", "close"]] = [80, 82, 79, 81]
    result = PortfolioBacktester(
        Prepared(), BacktestConfig(initial_cash=1000), RiskConfig(), {"BTCUSDT": rule()}
    ).run({"BTCUSDT": data})
    assert result.trades.iloc[0].exit_reason == "gap_stop"
    assert result.trades.iloc[0].exit_price < 80


def test_drawdown_halts_further_portfolio_entries():
    data = bars(30)
    data["enter_long"] = True
    data.loc[2, ["open", "high", "low", "close"]] = [50, 51, 49, 50]
    result = PortfolioBacktester(
        Prepared(),
        BacktestConfig(initial_cash=1000),
        RiskConfig(max_drawdown_pct=5),
        {"BTCUSDT": rule()},
    ).run({"BTCUSDT": data})
    assert len(result.trades) == 1
    assert result.metrics.max_drawdown_pct > 5


def test_no_signal_borrowed_across_missing_bar():
    data = bars().drop(index=1).reset_index(drop=True)
    result = PortfolioBacktester(
        Prepared(), BacktestConfig(), RiskConfig(), {"BTCUSDT": rule()}
    ).run({"BTCUSDT": data})
    assert result.metrics.trade_count == 0


def test_oos_warmup_does_not_open_positions_before_test_start():
    data = bars(15)
    data.loc[6, "enter_long"] = True
    start = data.iloc[7].open_time
    result = PortfolioBacktester(
        Prepared(), BacktestConfig(), RiskConfig(), {"BTCUSDT": rule()}
    ).run({"BTCUSDT": data}, trade_start=start)
    assert (pd.to_datetime(result.trades.entry_time) >= start).all()


def test_adaptive_strategy_is_prefix_invariant():
    data = bars(800)
    strategy = AdaptiveTrendStrategy(StrategyConfig())
    prefix = strategy.prepare(data.iloc[:403])
    full = strategy.prepare(data)
    for column in ("enter_long", "exit_long", "daily_ema", "atr", "adx", "signal_score"):
        pd.testing.assert_series_equal(prefix[column], full[column].iloc[:403])


def test_daily_trend_ignores_unclosed_day_prices():
    data = bars(60)
    before = completed_daily_trend(data, 2)
    changed = data.copy()
    changed.loc[58:, "close"] *= 10
    after = completed_daily_trend(changed, 2)
    pd.testing.assert_series_equal(before, after)


def test_universe_rejects_delisted_wide_spread_and_non_spot():
    cfg = AppConfig(universe=UniverseConfig(mode="all", max_symbols=None, min_quote_volume=100))
    symbols = []
    for name in ("BTCUSDT", "ETHUSDT", "ADAUSDT", "SOLUSDT"):
        symbols.append(
            {
                "symbol": name,
                "baseAsset": name[:-4],
                "quoteAsset": "USDT",
                "status": "TRADING",
                "isSpotTradingAllowed": True,
                "ocoAllowed": True,
                "orderTypes": ["MARKET", "STOP_LOSS_LIMIT", "TAKE_PROFIT_LIMIT"],
            }
        )
    symbols[1]["status"] = "BREAK"
    symbols[2]["isSpotTradingAllowed"] = False
    books = [
        {"symbol": item["symbol"], "bidPrice": "100", "askPrice": "100.01"} for item in symbols
    ]
    books[-1]["askPrice"] = "105"
    tickers = [{"symbol": item["symbol"], "quoteVolume": "10000000"} for item in symbols]
    selected, rejected = select_universe(cfg, {"symbols": symbols}, tickers, books)
    assert [item.symbol for item in selected] == ["BTCUSDT"]
    assert len(rejected) == 3


def test_nan_or_crossed_book_cannot_pass_spread_filter():
    assert spread_bps({"bidPrice": "NaN", "askPrice": "100"}) == float("inf")
    assert spread_bps({"bidPrice": "101", "askPrice": "100"}) == float("inf")


def test_exchange_rules_select_correct_symbol_and_intersect_market_lot():
    filters = [
        {"filterType": "LOT_SIZE", "minQty": "0.002", "maxQty": "100", "stepSize": "0.002"},
        {"filterType": "MARKET_LOT_SIZE", "minQty": "0.003", "maxQty": "10", "stepSize": "0.003"},
        {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
        {"filterType": "MIN_NOTIONAL", "minNotional": "5"},
    ]
    result = parse_symbol_rules(
        {
            "symbols": [
                {"symbol": "BTCUSDT", "filters": []},
                {"symbol": "ETHUSDT", "filters": filters},
            ]
        },
        "ETHUSDT",
    )
    assert result.step_size == Decimal("0.006")
    assert result.max_qty == Decimal("10")
    assert result.min_qty == Decimal("0.003")


def test_atr_sizing_scales_risk_and_requires_volatility():
    manager = RiskManager(RiskConfig(stop_mode="atr"), rule())
    low = manager.size_long(1000, 100, 1000, atr_value=1)
    high = manager.size_long(1000, 100, 1000, atr_value=3)
    assert high.quantity < low.quantity
    assert high.stop_price < low.stop_price
    assert high.quantity * (Decimal("100") - high.stop_price) <= Decimal("10")
    with pytest.raises(RiskViolation, match="ATR"):
        manager.size_long(1000, 100, atr_value=float("nan"))


def test_oco_notional_and_tick_constraints_are_checked_before_buy():
    with pytest.raises(RiskViolation, match="stop"):
        RiskManager(RiskConfig(), rule()).size_long(15.3, 100)
    with pytest.raises(RiskViolation, match="Tick"):
        RiskManager(RiskConfig(), replace(rule(), tick_size=Decimal("100"))).size_long(1000, 100)


def test_signal_ranking_is_deterministic_and_not_a_probability():
    rows = {
        s: {"enter_long": True, "exit_long": False, "signal_score": 40}
        for s in ("SOLUSDT", "BTCUSDT")
    }
    assert ranked_entries(rows) == ["BTCUSDT", "SOLUSDT"]
    rows["BTCUSDT"]["exit_long"] = True
    assert ranked_entries(rows) == ["SOLUSDT"]


def test_changed_coin_or_strategy_cannot_reuse_research_pass(tmp_path):
    cfg = AppConfig()
    signature = research_fingerprint(cfg, ["BTCUSDT"])
    (tmp_path / "validation_summary.json").write_text(
        json.dumps(
            {
                "fingerprint": signature,
                "status": "RESEARCH_PASS",
                "profit_factor": 2,
                "max_drawdown_pct": 2,
                "positive_windows_ratio": 1,
                "expectancy_per_trade": 1,
            }
        )
    )
    assert research_gate(tmp_path, cfg.gates, signature).passed
    assert not research_gate(tmp_path, cfg.gates, research_fingerprint(cfg, ["ETHUSDT"])).passed
    changed = cfg.model_copy(update={"strategy": cfg.strategy.model_copy(update={"ema_fast": 10})})
    assert not research_gate(tmp_path, cfg.gates, research_fingerprint(changed, ["BTCUSDT"])).passed


def test_paper_days_are_scoped_to_config_and_outages_do_not_count(tmp_path):
    journal = TradingJournal(tmp_path / "runtime.db")
    session = journal.start_session("paper", fingerprint="old")
    import sqlite3

    with sqlite3.connect(journal.database) as db:
        db.execute(
            "UPDATE sessions SET last_heartbeat=? WHERE id=?",
            ((datetime.now(UTC) - timedelta(days=14)).isoformat(), session),
        )
    journal.heartbeat(session)
    assert 0 < journal.paper_runtime_seconds("old") <= 60
    assert journal.paper_runtime_seconds("new") == 0
    assert not paper_gate(journal, AppConfig().gates, "new").passed


def test_duplicate_or_old_candle_is_never_reclaimed_after_restart(tmp_path):
    path = tmp_path / "runtime.db"
    journal = TradingJournal(path)
    assert journal.claim_candle("paper", "BTCUSDT", "4h", 10)
    restarted = TradingJournal(path)
    assert not restarted.claim_candle("paper", "BTCUSDT", "4h", 10)
    assert not restarted.claim_candle("paper", "BTCUSDT", "4h", 9)
    assert restarted.claim_candle("paper", "ETHUSDT", "4h", 10)


def test_pending_intent_survives_restart(tmp_path):
    path = tmp_path / "runtime.db"
    TradingJournal(path).set_intent("paper", {"client_order_id": "abc", "symbol": "ETHUSDT"})
    assert TradingJournal(path).pending_intent("paper")["client_order_id"] == "abc"


def test_wilson_interval_shows_small_sample_uncertainty():
    low, high = wilson_interval(5, 5)
    assert low < 60 and high == pytest.approx(100)
    assert wilson_interval(0, 0) == (0, 100)


def test_invalid_ohlcv_rejected():
    data = bars()
    data.loc[1, "high"] = 0
    with pytest.raises(ValueError):
        validate_candles(data)


def test_nonfinite_configuration_is_rejected():
    with pytest.raises(ValueError):
        BacktestConfig(initial_cash=float("inf"))
