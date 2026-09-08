from __future__ import annotations

import pandas as pd

from spotlab.strategies.quality import QualityCrossStrategy


class CurveScalpingStrategy(QualityCrossStrategy):
    """Closed-bar trend/pullback hypothesis; never extrapolates future prices."""

    def prepare(self, candles: pd.DataFrame) -> pd.DataFrame:
        frame = super().prepare(candles)
        cfg = self.config
        lookback = cfg.pullback_lookback
        movement = frame["close"].diff().abs().rolling(lookback).sum()
        displacement = frame["close"] - frame["close"].shift(lookback)
        frame["curve_efficiency"] = (displacement.abs() / movement.where(movement > 0)).fillna(0)
        frame["curve_slope_atr"] = (
            (frame["ema_slow"] - frame["ema_slow"].shift(lookback))
            / frame["atr"].where(frame["atr"] > 0)
        ).fillna(0)
        span = frame["high"] - frame["low"]
        frame["close_location"] = ((frame["close"] - frame["low"]) / span.where(span > 0)).fillna(0)
        trend = (
            frame["ema_fast"].gt(frame["ema_slow"])
            & frame["curve_slope_atr"].gt(0)
            & frame["close"].gt(frame["sma_trend"])
        )
        pullback = frame["low"].le(frame["ema_fast"]).shift(1).rolling(lookback).max().eq(1)
        recovery = (
            frame["close"].gt(frame["high"].shift(1))
            & frame["close"].gt(frame["ema_fast"])
            & frame["close_location"].ge(cfg.min_close_location)
            & frame["rsi"].between(cfg.rsi_min, cfg.rsi_max)
            & frame["macd_hist"].gt(frame["macd_hist"].shift(1))
        )
        frame["signal_score"] = (
            frame["curve_efficiency"].clip(0, 1) * 40
            + frame["adx"].clip(0, 50) / 50 * 30
            + frame["close_location"].clip(0, 1) * 30
        ).fillna(0)
        frame["enter_long"] = (
            trend
            & pullback
            & recovery
            & frame["entry_quality_ok"]
            & frame["signal_score"].ge(cfg.min_reversion_score)
        )
        frame["exit_long"] |= frame["close"].lt(frame["ema_slow"])
        frame["signal_reason"] = "hold:curve_or_recovery_filter"
        frame.loc[frame["enter_long"], "signal_reason"] = (
            "curve:uptrend+pullback+confirmed_recovery"
        )
        frame.loc[frame["exit_long"], "signal_reason"] = "curve:trend_break"
        return frame
