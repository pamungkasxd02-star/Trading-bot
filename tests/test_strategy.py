from datetime import timedelta

import numpy as np
import pandas as pd

from spotlab.config import StrategyConfig
from spotlab.strategies.rule_based import RuleBasedStrategy


def candles(count: int = 180) -> pd.DataFrame:
    time = pd.date_range("2025-01-01", periods=count, freq="4h", tz="UTC")
    close = np.concatenate([np.linspace(100, 80, 100), np.linspace(80, 140, count - 100)])
    return pd.DataFrame(
        {
            "open_time": time,
            "close_time": time + timedelta(hours=4),
            "open": close,
            "high": close * 1.005,
            "low": close * 0.995,
            "close": close,
            "volume": np.full(count, 100.0),
        }
    )


def test_strategy_outputs_auditable_signal_columns() -> None:
    result = RuleBasedStrategy(StrategyConfig(min_confirmations=2)).prepare(candles())
    required = {"enter_long", "exit_long", "confirmation_count", "signal_reason"}
    assert required.issubset(result.columns)
    assert result["confirmation_count"].between(0, 4).all()


def test_strategy_does_not_mutate_input() -> None:
    source = candles()
    original_columns = source.columns.tolist()
    RuleBasedStrategy().prepare(source)
    assert source.columns.tolist() == original_columns
