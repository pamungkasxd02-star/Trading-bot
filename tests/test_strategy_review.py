import numpy as np
import pandas as pd

from spotlab.config import StrategyConfig
from spotlab.strategies import STRATEGIES, build_strategy
from spotlab.strategy_review import TECHNIQUES, catalogue, evaluate, review
from spotlab.telegram_menu import route


def frame():
    close = 100 + np.arange(240) * 0.05 + np.sin(np.arange(240))
    times = pd.date_range("2026-01-01", periods=240, freq="min", tz="UTC")
    return pd.DataFrame(
        dict(
            open_time=times,
            close_time=times + pd.Timedelta(59999, unit="ms"),
            open=close - 0.1,
            high=close + 1,
            low=close - 1,
            close=close,
            volume=np.full(240, 100.0),
        )
    )


def test_catalogue_covers_actual_registry():
    assert set(TECHNIQUES) == set(STRATEGIES)
    assert "curve_scalping_v1" in catalogue("curve_scalping_v1")


def test_comparison_reuses_strategy_outputs():
    cfg = StrategyConfig()
    data = frame()
    for name in ["rule_based_v1", "quality_cross_v1", "curve_scalping_v1"]:
        prepared = build_strategy(name, config=cfg).prepare(data)
        row = prepared.iloc[-1]
        expected = (
            "EXIT CONDITION" if row.exit_long else "SETUP ENTRY" if row.enter_long else "WAIT"
        )
        result = evaluate(data, cfg, name)
        assert result["state"] == expected
        assert row.signal_reason in result["detail"]


def test_short_and_daily_histories_not_mislabeled_as_wait():
    cfg = StrategyConfig()
    assert evaluate(frame().head(5), cfg, "rule_based_v1")["state"] == "DATA KURANG"
    for name in ["adaptive_trend_v2", "regime_reversion_v3"]:
        assert evaluate(frame(), cfg, name)["state"] == "DATA KURANG"
    data = frame()
    data["volume"] = 0
    assert evaluate(data, cfg, "quality_cross_v1")["state"] == "DATA TIDAK VALID"


def test_report_and_menu_are_read_only_and_bounded():
    class Charts:
        def candles(self, query, interval):
            assert (query, interval) == ("SOL", "1m")
            return {"symbol": "SOLUSDT"}, frame()

    result = review(Charts(), "SOL", "1m", StrategyConfig())
    assert len(result) < 3900
    assert "bukan voting" in result
    state = {"auto": False}
    route("Cek teknik coin", state, 100)
    route("SOL", state, 101)
    assert route("1m", state, 102)[0] == "/techniques SOL 1m"
    assert state == {"auto": False}


def test_entry_preview_costs_and_quote_currency(monkeypatch):
    from decimal import Decimal
    from types import SimpleNamespace

    from spotlab.config import AppConfig
    from spotlab.entry_preview import preview
    from spotlab.models import SymbolRules
    from spotlab.risk import RiskManager

    cfg = AppConfig()
    cfg.backtest.fee_bps = 10
    cfg.backtest.slippage_bps = 5
    cfg.demo.analysis_only = True
    state = dict(
        cash=1000,
        health="healthy",
        position=None,
        trading_halted=False,
        telegram_control={"auto": False},
    )
    account = SimpleNamespace(
        config=cfg,
        status=lambda: state,
        market=SimpleNamespace(metadata=lambda _: {"symbols": ["SOLUSDT"]}),
    )
    rules = SymbolRules(
        "SOLUSDT", Decimal(".001"), Decimal("100000"), Decimal(".001"), Decimal(".01"), Decimal("5")
    )
    monkeypatch.setattr("spotlab.entry_preview.parse_symbol_rules", lambda info, symbol: rules)
    data = frame()
    charts = SimpleNamespace(
        candles=lambda query, interval: ({"symbol": "SOLUSDT", "quoteAsset": "USDT"}, data)
    )
    report = preview(account, charts, "SOL", cfg.demo.interval)
    assert "mode belajar" in report and "auto entry dijeda" in report
    assert "SL trigger:" in report and "TP trigger:" in report
    assert "BUKAN harga ask" in report
    assert len(report) < 3900
    assert state["telegram_control"]["auto"] is False and state["position"] is None
    charts.candles = lambda query, interval: ({"quoteAsset": "BTC"}, data)
    assert "hanya untuk pair USDT" in preview(account, charts, "SOLBTC", "1m")
    # Independently verify the reported net loss includes both fees and exit slippage.
    entry = float(data.close.iloc[-1]) * 1.0005
    size = RiskManager(cfg.risk, rules).size_long(1000, entry, 1000 / 1.001, cost_bps=30)
    exit_price = float(size.stop_price) * 0.9995
    loss = float(size.quantity) * ((entry - exit_price) + 0.001 * (entry + exit_price))
    assert f"loss ke SL: {loss:.4f}" in report
