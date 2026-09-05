from __future__ import annotations

import numpy as np
import pandas as pd

from spotlab.indicators import completed_daily_trend, crossed_below, rsi
from spotlab.strategies.adaptive import AdaptiveTrendStrategy


class RegimeReversionStrategy(AdaptiveTrendStrategy):
    """Buy a confirmed rebound in an uptrend or a non-bearish range.

    Scores rank signals; they are not fitted probabilities. Bearish daily regimes,
    oversized shock candles and unconfirmed falls do not produce entries.
    """

    def prepare(self, candles: pd.DataFrame) -> pd.DataFrame:
        frame = super().prepare(candles)
        cfg = self.config
        frame["fast_rsi"] = rsi(frame["close"], cfg.fast_rsi_period)
        daily_previous = completed_daily_trend(frame, cfg.daily_ema_period, lag_days=1)
        frame["daily_change_pct"] = 100 * (frame["daily_ema"] / daily_previous - 1)
        span = (frame["high"] - frame["low"]).replace(0, np.nan)
        frame["close_location"] = (frame["close"] - frame["low"]) / span
        safe_atr = frame["atr"].replace(0, np.nan)
        trend = (
            frame["daily_change_pct"].gt(0)
            & frame["close"].gt(frame["daily_ema"])
            & frame["ema_fast"].gt(frame["ema_slow"])
            & frame["close"].gt(frame["sma_trend"])
            & frame["adx"].ge(cfg.min_adx)
        )
        sideways = (
            frame["adx"].lt(cfg.range_max_adx)
            & frame["daily_change_pct"].ge(-cfg.max_daily_decline_pct)
            & frame["close"].ge(frame["daily_ema"] * (1 - cfg.max_daily_distance_pct / 100))
            & ~trend
        )
        dipped = (
            frame["fast_rsi"].shift(1).rolling(cfg.pullback_lookback).min() <= cfg.fast_rsi_oversold
        )
        recovering = (
            frame["close"].gt(frame["close"].shift(1))
            & frame["close"].gt(frame["open"])
            & frame["fast_rsi"].gt(frame["fast_rsi"].shift(1))
            & frame["close_location"].ge(cfg.min_close_location)
        )
        trend_trigger = (
            dipped
            & frame["rsi"].lt(cfg.rsi_max)
            & ((frame["close"] - frame["ema_fast"]).abs() / safe_atr).le(
                cfg.max_pullback_distance_atr
            )
        )
        range_trigger = (
            frame["close"].shift(1).lt(frame["bb_lower"].shift(1))
            | frame["rsi"].shift(1).lt(cfg.range_entry_rsi)
        ) & frame["close"].gt(frame["bb_lower"])
        quality = (
            recovering
            & frame["atr_pct"].between(cfg.min_atr_pct, cfg.max_atr_pct)
            & frame["relative_volume"].ge(cfg.min_relative_volume)
            & (span / safe_atr).le(cfg.max_signal_candle_atr)
        )
        frame["signal_score"] = (
            frame["close_location"].clip(0, 1) * 40
            + frame["relative_volume"].clip(0, 2) / 2 * 20
            + (100 - frame["fast_rsi"].shift(1)).clip(0, 100) / 100 * 25
            + frame["daily_change_pct"].ge(0).astype(float) * 15
        ).fillna(0)
        trend_entry = trend & trend_trigger & (cfg.regime_mode != "range")
        range_entry = sideways & range_trigger & (cfg.regime_mode != "trend")
        frame["enter_long"] = (
            (trend_entry | range_entry)
            & quality
            & frame["signal_score"].ge(cfg.min_reversion_score)
        )
        frame["exit_long"] = (
            (frame["rsi"].ge(cfg.reversion_exit_rsi) & frame["close"].ge(frame["ema_fast"]))
            | crossed_below(frame["ema_fast"], frame["ema_slow"])
            | frame["close"].lt(frame["daily_ema"] * (1 - cfg.max_daily_distance_pct / 100))
        )
        frame["regime"] = "avoid"
        frame.loc[trend, "regime"] = "trend"
        frame.loc[sideways, "regime"] = "range"
        frame["signal_reason"] = "hold:regime_or_rebound_filter"
        frame.loc[frame["enter_long"], "signal_reason"] = (
            "reversion:" + frame.loc[frame["enter_long"], "regime"] + "+confirmed_rebound"
        )
        frame.loc[frame["exit_long"], "signal_reason"] = "reversion:recovered_or_trend_break"
        return frame
