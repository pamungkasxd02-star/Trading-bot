from __future__ import annotations

import pandas as pd

from spotlab.indicators import adx, atr
from spotlab.strategies.rule_based import RuleBasedStrategy


class QualityCrossStrategy(RuleBasedStrategy):
    """Filter baseline entries; hypotheses, not calibrated win probabilities.

    Uses only current/previous closed bars, with no daily warmup requirement.
    Exit and mandatory execution SL/TP retain the baseline semantics.
    """

    def prepare(self, candles: pd.DataFrame) -> pd.DataFrame:
        frame = super().prepare(candles)
        cfg = self.config
        frame["atr"] = atr(frame, cfg.atr_period)
        frame["atr_pct"] = 100 * frame["atr"] / frame["close"]
        frame["adx"] = adx(frame, cfg.adx_period)
        frame["relative_volume"] = frame["volume"] / frame["volume_sma"].shift(1)
        span = frame["high"] - frame["low"]
        quality = (
            frame["adx"].ge(cfg.min_adx)
            & frame["atr_pct"].between(cfg.min_atr_pct, cfg.max_atr_pct)
            & frame["relative_volume"].ge(cfg.min_relative_volume)
            & frame["sma_trend"].gt(frame["sma_trend"].shift(cfg.pullback_lookback))
            & span.le(frame["atr"] * cfg.max_signal_candle_atr)
            & (frame["close"] - frame["ema_fast"]).le(frame["atr"] * cfg.max_pullback_distance_atr)
        ).fillna(False)
        frame["entry_quality_ok"] = quality
        frame["enter_long"] &= quality
        frame["signal_reason"] = "hold:quality_cross_filter"
        frame.loc[frame["enter_long"], "signal_reason"] = "quality_cross:trend+volume+volatility"
        frame.loc[frame["exit_long"], "signal_reason"] = "quality_cross:bearish_cross"
        return frame
