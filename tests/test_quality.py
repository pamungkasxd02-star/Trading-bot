import numpy as np
import pandas as pd

from spotlab.config import AppConfig, ResearchConfig, StrategyConfig
from spotlab.research.walkforward import candidates
from spotlab.strategies.quality import QualityCrossStrategy
from spotlab.strategies.rule_based import RuleBasedStrategy


def market():
    rng = np.random.default_rng(401)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.012, 1200)))
    times = pd.date_range("2024-01-01", periods=len(close), freq="4h", tz="UTC")
    return pd.DataFrame(
        dict(
            open_time=times,
            close_time=times + pd.Timedelta(4, unit="h"),
            open=close * 0.999,
            high=close * 1.01,
            low=close * 0.99,
            close=close,
            volume=rng.uniform(50, 200, len(close)),
        )
    )


def test_quality_filters_never_add_entries_or_change_exits():
    data = market()
    cfg = StrategyConfig(min_confirmations=1, sma_trend=20)
    baseline = RuleBasedStrategy(cfg).prepare(data)
    filtered = QualityCrossStrategy(cfg).prepare(data)
    assert baseline.enter_long.any()
    assert not (filtered.enter_long & ~baseline.enter_long).any()
    pd.testing.assert_series_equal(filtered.exit_long, baseline.exit_long)
    strict = cfg.model_copy(update={"min_relative_volume": 1000})
    assert not QualityCrossStrategy(strict).prepare(data).enter_long.any()


def test_quality_signals_do_not_depend_on_future_bars():
    data = market()
    original = data.copy(deep=True)
    strategy = QualityCrossStrategy()
    full = strategy.prepare(data)
    prefix = strategy.prepare(data.iloc[:800])
    pd.testing.assert_frame_equal(full.iloc[:800], prefix)
    pd.testing.assert_frame_equal(data, original)


def test_quality_family_keeps_risk_and_costs_comparable():
    cfg = AppConfig(research=ResearchConfig(candidate_set="quality"))
    family = candidates(cfg)
    assert [c.name for c in family] == ["baseline", "quality_cross", "quality_cross_selective"]
    assert all(c.config.risk == family[0].config.risk for c in family)
    assert all(c.config.backtest == cfg.backtest for c in family)
