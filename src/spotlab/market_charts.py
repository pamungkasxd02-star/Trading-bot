"""Public on-demand charts, independent of the execution universe."""

from __future__ import annotations

import time

import numpy as np
import pandas as pd

from spotlab.exchange import PublicMarketClient

INTERVALS = (
    "1s",
    "1m",
    "3m",
    "5m",
    "15m",
    "30m",
    "1h",
    "2h",
    "4h",
    "6h",
    "8h",
    "12h",
    "1d",
    "3d",
    "1w",
    "1M",
)
ALIASES = {
    "bitcoin": "BTC",
    "ethereum": "ETH",
    "solana": "SOL",
    "dogecoin": "DOGE",
    "cardano": "ADA",
    "avalanche": "AVAX",
    "chainlink": "LINK",
    "ripple": "XRP",
    "binancecoin": "BNB",
    "bitcoin-cash": "BCH",
    "litecoin": "LTC",
}


def normalize_coin(value):
    return ALIASES.get(value.lower(), value.upper()).replace("/", "").replace("-", "")


def selected_symbol(value, selected):
    coin = normalize_coin(value)
    if coin in selected:
        return coin
    if coin + "USDT" in selected:
        return coin + "USDT"
    raise ValueError("Coin tidak masuk universe trading; lihat /eligible.")


class MarketCharts:
    def __init__(self, client=None):
        self.client = client or PublicMarketClient()
        self.cached = None
        self.fetched_at = 0

    def catalogue(self):
        if self.cached is None or time.monotonic() - self.fetched_at > 900:
            info = self.client.exchange_info()
            self.cached = {
                r["symbol"]: r
                for r in info["symbols"]
                if r.get("isSpotTradingAllowed") and r.get("status") == "TRADING"
            }
            self.fetched_at = time.monotonic()
        return self.cached

    def resolve(self, query):
        catalogue = self.catalogue()
        coin = normalize_coin(query)
        if coin in catalogue:
            return catalogue[coin]
        if coin + "USDT" in catalogue:
            return catalogue[coin + "USDT"]
        candidates = [r for r in catalogue.values() if r["baseAsset"] == coin]
        if len(candidates) == 1:
            return candidates[0]
        if candidates:
            raise ValueError("Pilih pair: " + ", ".join(r["symbol"] for r in candidates[:12]))
        raise ValueError("Coin/pair tidak ditemukan di Binance Spot. Coba /coins TICKER.")

    def candles(self, query, interval, limit=500):
        if interval not in INTERVALS:
            raise ValueError("Interval: " + " ".join(INTERVALS))
        market = self.resolve(query)
        raw = self.client.klines(market["symbol"], interval, limit=limit)
        now_ms = int(time.time() * 1000)
        rows = [r for r in raw if int(r[6]) < now_ms]
        if len(rows) < 2:
            raise ValueError("Belum cukup candle tertutup pada interval ini.")
        frame = pd.DataFrame(
            [
                {
                    "open_time": int(r[0]),
                    "close_time": int(r[6]),
                    "open": float(r[1]),
                    "high": float(r[2]),
                    "low": float(r[3]),
                    "close": float(r[4]),
                    "volume": float(r[5]),
                }
                for r in rows
            ]
        )
        values = frame[["open", "high", "low", "close", "volume"]]
        if not np.isfinite(values.to_numpy()).all() or (values < 0).any().any():
            raise ValueError("OHLCV invalid")
        if (
            not (frame.high >= frame[["open", "close", "low"]].max(axis=1)).all()
            or not (frame.low <= frame[["open", "close", "high"]].min(axis=1)).all()
        ):
            raise ValueError("OHLC inconsistent")
        for key in ["open_time", "close_time"]:
            frame[key] = pd.to_datetime(frame[key], unit="ms", utc=True)
        if not frame.open_time.is_monotonic_increasing or frame.open_time.duplicated().any():
            raise ValueError("Candle timestamps invalid")
        offset = (
            pd.DateOffset(months=1)
            if interval == "1M"
            else pd.Timedelta(
                int(interval[:-1]),
                unit={"s": "s", "m": "min", "h": "h", "d": "d", "w": "W"}[interval[-1]],
            )
        )
        expected = frame.open_time.iloc[:-1].map(lambda t: t + offset).reset_index(drop=True)
        if not expected.equals(frame.open_time.iloc[1:].reset_index(drop=True)):
            raise ValueError("History candle berlubang; coba kembali setelah data pulih.")
        if frame.open_time.iloc[-1] + offset * 2 < pd.Timestamp.now(tz="UTC"):
            raise ValueError("Data publik stale; grafik tidak dikirim.")
        return market, frame
