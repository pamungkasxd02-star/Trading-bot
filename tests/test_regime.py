from datetime import timedelta

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from spotlab.config import AppConfig, ResearchConfig, StrategyConfig
from spotlab.research.walkforward import candidates, research_fingerprint
from spotlab.strategies.regime import RegimeReversionStrategy


def oscillating_bars(*, bearish=False):
    ticks = np.arange(1000)
    close = (
        100 - ticks * 0.04 + 0.2 * np.sin(ticks / 5)
        if bearish
        else (100 + ticks * 0.05 + 2 * np.sin(ticks / 5))
    )
    dates = pd.date_range("2024-01-01", periods=len(ticks), freq="4h", tz="UTC")
    return pd.DataFrame(
        {
            "open_time": dates,
            "close_time": dates + timedelta(hours=4, milliseconds=-1),
            "open": close - 0.3,
            "high": close + 0.2,
            "low": close - 0.5,
            "close": close,
            "volume": 1000000.0,
        }
    )


def test_regime_signals_do_not_change_when_future_bars_are_appended():
    source = oscillating_bars()
    strategy = RegimeReversionStrategy(StrategyConfig())
    full = strategy.prepare(source)
    assert full.enter_long.any(), "Fixture must exercise actual entries"
    prefix = strategy.prepare(source.iloc[:505])
    for key in ("daily_change_pct", "enter_long", "exit_long", "signal_score", "regime"):
        pd.testing.assert_series_equal(prefix[key], full[key].iloc[:505])
    assert full.signal_score.between(0, 100).all()


def test_rebounds_in_a_falling_daily_market_are_rejected():
    result = RegimeReversionStrategy(StrategyConfig()).prepare(oscillating_bars(bearish=True))
    assert not result.enter_long.any()


@pytest.mark.parametrize("values", [[float("nan")], [float("inf")], [0], [-10]])
def test_research_rejects_invalid_capital_scenarios(values):
    with pytest.raises(ValidationError):
        ResearchConfig(evaluation_capitals=values)


def test_research_requirements_are_part_of_configuration_identity():
    config = AppConfig()
    changed = config.model_copy(update={"research": ResearchConfig(target_win_rate_pct=55)})
    assert research_fingerprint(config, ["BTCUSDT"]) != research_fingerprint(changed, ["BTCUSDT"])
    config = config.model_copy(update={"research": ResearchConfig(candidate_set="regime")})
    variants = candidates(config)
    assert len(variants) == 6
    assert len({research_fingerprint(c.config, ["BTCUSDT"]) for c in variants}) == 6
