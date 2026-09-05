from __future__ import annotations

import re

import numpy as np
import pandas as pd


def interval_milliseconds(interval: str) -> int:
    match = re.fullmatch(r"([1-9][0-9]*)([smhdw])", interval)
    if match is None:
        raise ValueError("Interval harus interval tetap Binance, misalnya 15m, 1h, 4h, 1d")
    return int(match[1]) * {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}[match[2]] * 1000


def validate_candles(candles: pd.DataFrame) -> pd.DataFrame:
    frame = candles.copy()
    for column in ("open_time", "close_time"):
        frame[column] = pd.to_datetime(frame[column], utc=True)
    frame = frame.sort_values("open_time").reset_index(drop=True)
    if frame.empty or frame["open_time"].duplicated().any():
        raise ValueError("Dataset kosong atau timestamp duplikat")
    values = frame[["open", "high", "low", "close", "volume"]].astype(float)
    if not np.isfinite(values).all().all() or (values["volume"] < 0).any():
        raise ValueError("OHLCV tidak finite atau volume negatif")
    if (values[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("Harga OHLC harus positif")
    if (values["high"] < values[["open", "low", "close"]].max(axis=1)).any():
        raise ValueError("High OHLC tidak valid")
    if (values["low"] > values[["open", "high", "close"]].min(axis=1)).any():
        raise ValueError("Low OHLC tidak valid")
    if (frame["close_time"] <= frame["open_time"]).any():
        raise ValueError("close_time harus sesudah open_time")
    return frame
