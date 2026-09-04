from __future__ import annotations

import numpy as np
import pandas as pd


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)
    average_gain = gains.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    average_loss = losses.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    relative_strength = average_gain / average_loss.replace(0, np.nan)
    result = 100 - (100 / (1 + relative_strength))
    return result.where(average_loss.ne(0), 100.0).where(average_gain.ne(0), 0.0)


def macd(
    series: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    line = ema(series, fast) - ema(series, slow)
    signal_line = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return line, signal_line, line - signal_line


def bollinger_bands(
    series: pd.Series,
    period: int = 20,
    deviations: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    middle = sma(series, period)
    standard_deviation = series.rolling(period, min_periods=period).std(ddof=0)
    return (
        middle - deviations * standard_deviation,
        middle,
        middle + deviations * standard_deviation,
    )


def crossed_above(left: pd.Series, right: pd.Series) -> pd.Series:
    return left.gt(right) & left.shift(1).le(right.shift(1))


def crossed_below(left: pd.Series, right: pd.Series) -> pd.Series:
    return left.lt(right) & left.shift(1).ge(right.shift(1))
