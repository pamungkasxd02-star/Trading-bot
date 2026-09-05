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


def atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    previous = frame["close"].shift(1)
    ranges = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous).abs(),
            (frame["low"] - previous).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def adx(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    upward = frame["high"].diff()
    downward = -frame["low"].diff()
    plus = upward.where((upward > downward) & (upward > 0), 0.0)
    minus = downward.where((downward > upward) & (downward > 0), 0.0)
    volatility = atr(frame, period).replace(0, np.nan)
    plus_di = 100 * plus.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / volatility
    minus_di = (
        100 * minus.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / volatility
    )
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def completed_daily_trend(frame: pd.DataFrame, period: int) -> pd.Series:
    """Daily EMA becomes visible only after that UTC day closes."""
    source = frame.set_index(pd.to_datetime(frame["open_time"], utc=True))["close"]
    daily = source.resample("1D", closed="left", label="right").last()
    daily_ema = ema(daily, period).rename("daily_ema").reset_index()
    daily_ema.columns = ["available_at", "daily_ema"]
    closed = pd.DataFrame({"asof": pd.to_datetime(frame["close_time"], utc=True)})
    return pd.merge_asof(
        closed, daily_ema, left_on="asof", right_on="available_at", direction="backward"
    )["daily_ema"].set_axis(frame.index)
