from datetime import timedelta
from decimal import Decimal

import pandas as pd
import yaml

from spotlab.config import AppConfig, BacktestConfig, ExchangeConfig, ResearchConfig, RiskConfig
from spotlab.models import SymbolRules
from spotlab.research import walkforward
from spotlab.strategies.base import Strategy


def test_candidate_identity_survives_yaml_round_trip():
    for candidate in walkforward.candidates(AppConfig()):
        reloaded = AppConfig.model_validate(
            yaml.safe_load(yaml.safe_dump(candidate.config.model_dump(mode="json")))
        )
        assert walkforward.research_fingerprint(
            candidate.config, ["BTCUSDT", "ETHUSDT"]
        ) == walkforward.research_fingerprint(reloaded, ["ETHUSDT", "BTCUSDT"])


class FixtureSignals(Strategy):
    def prepare(self, candles):
        result = candles.copy()
        result["enter_long"] = result.index % 7 == 0
        result["exit_long"] = False
        result["signal_score"] = 50
        result["signal_reason"] = "fixture"
        return result


def test_oos_prices_never_change_training_selection_or_scores(tmp_path, monkeypatch):
    cfg = AppConfig(
        exchange=ExchangeConfig(interval="1d"),
        backtest=BacktestConfig(initial_cash=1000),
        risk=RiskConfig(stop_loss_pct=10, take_profit_pct=2),
        research=ResearchConfig(train_months=3, test_months=1, min_train_trades=1),
    )
    dates = pd.date_range("2025-01-01", periods=200, freq="1D", tz="UTC")
    frame = pd.DataFrame(
        {
            "open_time": dates,
            "close_time": dates + timedelta(days=1, milliseconds=-1),
            "open": 100.0,
            "high": 105.0,
            "low": 99.0,
            "close": 101.0,
            "volume": 1_000_000.0,
        }
    )
    rule = SymbolRules(
        "BTCUSDT",
        Decimal("0.001"),
        Decimal("100000"),
        Decimal("0.001"),
        Decimal("0.01"),
        Decimal("5"),
    )
    monkeypatch.setattr(walkforward, "candidates", lambda _: [walkforward.Candidate("fixed", cfg)])
    monkeypatch.setattr(walkforward, "build_strategy", lambda *a, **kw: FixtureSignals())
    monkeypatch.setattr(walkforward, "plot_equity", lambda *a: None)
    first = walkforward.run_walkforward({"BTCUSDT": frame}, {"BTCUSDT": rule}, cfg, tmp_path / "a")
    changed = frame.copy()
    boundary = pd.Timestamp(first["train_end_exclusive"])
    changed.loc[changed.open_time >= boundary, ["open", "high", "low", "close"]] *= 0.5
    second = walkforward.run_walkforward(
        {"BTCUSDT": changed}, {"BTCUSDT": rule}, cfg, tmp_path / "b"
    )
    assert first["selection"] == second["selection"] == "fixed"
    pd.testing.assert_frame_equal(
        pd.read_csv(tmp_path / "a/training.csv"), pd.read_csv(tmp_path / "b/training.csv")
    )
    assert first["results"]["fixed"]["status"] == "RESEARCH_FAIL"
    assert "source_or_exchange_filters_unverified" in first["results"]["fixed"]["failures"]
    trades = pd.read_csv(tmp_path / "a/fixed/trades.csv")
    assert (pd.to_datetime(trades.entry_time) >= pd.Timestamp(first["oos_start"])).all()


def test_one_profitable_balance_cannot_mask_a_failing_balance(tmp_path, monkeypatch):
    cfg = AppConfig(
        exchange=ExchangeConfig(interval="1d"),
        backtest=BacktestConfig(initial_cash=1000),
        risk=RiskConfig(stop_loss_pct=10, take_profit_pct=2),
        research=ResearchConfig(
            train_months=3,
            test_months=1,
            min_train_trades=1,
            min_oos_trades=1,
            evaluation_capitals=[20, 1000],
            target_win_rate_pct=55,
        ),
    )
    dates = pd.date_range("2025-01-01", periods=200, freq="1D", tz="UTC")
    frame = pd.DataFrame(
        {
            "open_time": dates,
            "close_time": dates + timedelta(days=1, milliseconds=-1),
            "open": 100.0,
            "high": 105.0,
            "low": 99.0,
            "close": 101.0,
            "volume": 1e6,
        }
    )
    rule = SymbolRules(
        "BTCUSDT", Decimal(".001"), Decimal("100000"), Decimal(".001"), Decimal(".01"), Decimal("5")
    )
    monkeypatch.setattr(walkforward, "candidates", lambda _: [walkforward.Candidate("fixed", cfg)])
    monkeypatch.setattr(walkforward, "build_strategy", lambda *a, **kw: FixtureSignals())
    monkeypatch.setattr(walkforward, "plot_equity", lambda *a: None)
    report = walkforward.run_walkforward(
        {"BTCUSDT": frame},
        {"BTCUSDT": rule},
        cfg,
        tmp_path,
        provenance={"exchange_verified": True},
    )
    assert report["results"]["fixed"]["win_rate_pct"] == 100
    assert report["selection"] is None
    assert report["policy_action"] == "NO_TRADE"
    assert "capital_validation_failed:20" in report["results"]["fixed"]["failures"]
