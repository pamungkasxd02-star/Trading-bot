from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class Strategy(ABC):
    """A strategy emits deterministic columns; it never places orders."""

    @abstractmethod
    def prepare(self, candles: pd.DataFrame) -> pd.DataFrame:
        """Return candles plus `enter_long`, `exit_long`, and `signal_reason`."""


def require_ohlcv(candles: pd.DataFrame) -> None:
    required = {"open_time", "open", "high", "low", "close", "volume"}
    missing = required.difference(candles.columns)
    if missing:
        raise ValueError(f"Missing OHLCV columns: {', '.join(sorted(missing))}")
