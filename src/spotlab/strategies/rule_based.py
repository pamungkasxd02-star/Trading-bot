from __future__ import annotations

import pandas as pd

from spotlab.config import StrategyConfig
from spotlab.indicators import bollinger_bands, crossed_above, crossed_below, ema, macd, rsi, sma
from spotlab.strategies.base import Strategy, require_ohlcv


class RuleBasedStrategy(Strategy):
    """Auditable 4-hour trend-following baseline.

    Entry requires a fresh EMA cross, a long-term uptrend, and at least N of
    four confirmations (RSI, MACD, Bollinger position, volume). Exit is a
    bearish EMA cross; hard stop and take-profit remain execution concerns.
    """

    def __init__(self, config: StrategyConfig | None = None, **_: object) -> None:
        self.config = config or StrategyConfig()

    def prepare(self, candles: pd.DataFrame) -> pd.DataFrame:
        require_ohlcv(candles)
        cfg = self.config
        frame = candles.sort_values("open_time").reset_index(drop=True).copy()

        frame["ema_fast"] = ema(frame["close"], cfg.ema_fast)
        frame["ema_slow"] = ema(frame["close"], cfg.ema_slow)
        frame["sma_trend"] = sma(frame["close"], cfg.sma_trend)
        frame["rsi"] = rsi(frame["close"], cfg.rsi_period)
        frame["macd"], frame["macd_signal"], frame["macd_hist"] = macd(
            frame["close"], cfg.macd_fast, cfg.macd_slow, cfg.macd_signal
        )
        frame["bb_lower"], frame["bb_middle"], frame["bb_upper"] = bollinger_bands(
            frame["close"], cfg.bb_period, cfg.bb_std
        )
        frame["volume_sma"] = sma(frame["volume"], cfg.volume_period)

        confirmations = pd.DataFrame(
            {
                "rsi": frame["rsi"].between(cfg.rsi_min, cfg.rsi_max),
                "macd": frame["macd"].gt(frame["macd_signal"]),
                "bollinger": frame["close"].between(frame["bb_middle"], frame["bb_upper"]),
                "volume": frame["volume"].ge(frame["volume_sma"]),
            }
        )
        frame["confirmation_count"] = confirmations.sum(axis=1)
        fresh_cross = crossed_above(frame["ema_fast"], frame["ema_slow"])
        trend_ok = frame["close"].gt(frame["sma_trend"])
        frame["enter_long"] = (
            fresh_cross & trend_ok & frame["confirmation_count"].ge(cfg.min_confirmations)
        )
        frame["exit_long"] = crossed_below(frame["ema_fast"], frame["ema_slow"])
        frame["signal_reason"] = "hold"
        frame.loc[frame["enter_long"], "signal_reason"] = (
            "ema_bullish_cross+trend+confirmations_"
            + frame.loc[frame["enter_long"], "confirmation_count"].astype(str)
        )
        frame.loc[frame["exit_long"], "signal_reason"] = "ema_bearish_cross"
        return frame
