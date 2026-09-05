from __future__ import annotations

import pandas as pd

from spotlab.config import StrategyConfig
from spotlab.indicators import adx, atr, completed_daily_trend, crossed_above
from spotlab.strategies.rule_based import RuleBasedStrategy


class AdaptiveTrendStrategy(RuleBasedStrategy):
    """Long-only trend pullbacks; bearish/low-quality regimes stay in cash.

    A score ranks simultaneous signals. It is not a probability of winning.
    Every indicator uses only information available at the closed candle.
    """

    def __init__(self, config: StrategyConfig | None = None, **_: object) -> None:
        super().__init__(config)

    def prepare(self, candles: pd.DataFrame) -> pd.DataFrame:
        frame = super().prepare(candles)
        cfg = self.config
        frame["atr"] = atr(frame, cfg.atr_period)
        frame["atr_pct"] = 100 * frame["atr"] / frame["close"]
        frame["adx"] = adx(frame, cfg.adx_period)
        frame["daily_ema"] = completed_daily_trend(frame, cfg.daily_ema_period)
        # Compare current volume with previous candles, without diluting a spike.
        frame["relative_volume"] = frame["volume"] / frame["volume_sma"].shift(1)
        trend = (
            frame["ema_fast"].gt(frame["ema_slow"])
            & frame["close"].gt(frame["sma_trend"])
            & frame["close"].gt(frame["daily_ema"])
            & frame["ema_slow"].gt(frame["ema_slow"].shift(3))
            & frame["adx"].ge(cfg.min_adx)
        )
        dipped = frame["rsi"].shift(1).rolling(cfg.pullback_lookback).min().le(cfg.pullback_rsi)
        recovery = crossed_above(frame["close"], frame["ema_fast"]) & dipped
        cross = crossed_above(frame["ema_fast"], frame["ema_slow"])
        quality = (
            frame["atr_pct"].between(cfg.min_atr_pct, cfg.max_atr_pct)
            & frame["relative_volume"].ge(cfg.min_relative_volume)
            & frame["rsi"].between(cfg.rsi_min, cfg.rsi_max)
            & frame["macd_hist"].gt(frame["macd_hist"].shift(1))
        )
        frame["enter_long"] = trend & quality & (recovery | cross)
        frame["exit_long"] = frame["exit_long"] | frame["close"].lt(frame["daily_ema"])
        frame["signal_score"] = (
            frame["adx"].clip(0, 50) / 50 * 40
            + frame["relative_volume"].clip(0, 3) / 3 * 30
            + frame["confirmation_count"] / 4 * 30
        ).fillna(0)
        frame["regime"] = "avoid"
        frame.loc[trend, "regime"] = "uptrend"
        frame["signal_reason"] = "hold:regime_or_quality_filter"
        frame.loc[frame["enter_long"], "signal_reason"] = "adaptive:trend+pullback_or_cross+quality"
        frame.loc[frame["exit_long"], "signal_reason"] = "adaptive:trend_break"
        return frame
