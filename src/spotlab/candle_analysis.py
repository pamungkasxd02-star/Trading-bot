"""Descriptive closed-candle analysis; never an execution signal or probability."""

from __future__ import annotations

import numpy as np

from spotlab.indicators import atr, ema, macd, rsi
from spotlab.market_charts import INTERVALS


def describe(frame, config):
    required = max(
        config.ema_slow + 1,
        config.rsi_period + 2,
        config.macd_slow + config.macd_signal,
        config.volume_period + 1,
        config.atr_period + 1,
        config.bb_period + 1,
    )
    if len(frame) < required:
        raise ValueError(f"Butuh {required} candle tertutup; tersedia {len(frame)}.")
    close = frame.close
    fast, slow = ema(close, config.ema_fast), ema(close, config.ema_slow)
    last = frame.iloc[-1]
    if last.close > fast.iloc[-1] > slow.iloc[-1] and slow.iloc[-1] > slow.iloc[-2]:
        trend = "naik"
    elif last.close < fast.iloc[-1] < slow.iloc[-1] and slow.iloc[-1] < slow.iloc[-2]:
        trend = "turun"
    else:
        trend = "campuran"
    strength = rsi(close, config.rsi_period).iloc[-1]
    # A flat window has neither gains nor losses; do not label it oversold.
    if close.iloc[-(config.rsi_period + 1) :].nunique() == 1:
        strength = 50.0
    histogram = macd(close, config.macd_fast, config.macd_slow, config.macd_signal)[2]
    prior_volume = frame.volume.iloc[-(config.volume_period + 1) : -1].mean()
    relative_volume = float(last.volume / prior_volume) if prior_volume > 0 else None
    previous = frame.iloc[-(config.bb_period + 1) : -1]
    low, high = float(previous.low.min()), float(previous.high.max())
    location = (
        "di atas range sebelumnya"
        if last.close > high
        else ("di bawah range sebelumnya" if last.close < low else "di dalam range sebelumnya")
    )
    candle_range = float(last.high - last.low)
    anatomy = {
        "body_pct": abs(float(last.close - last.open)) / candle_range * 100 if candle_range else 0,
        "upper_wick_pct": float(last.high - max(last.open, last.close)) / candle_range * 100
        if candle_range
        else 0,
        "lower_wick_pct": float(min(last.open, last.close) - last.low) / candle_range * 100
        if candle_range
        else 0,
    }
    values = [
        strength,
        histogram.iloc[-1],
        histogram.iloc[-2],
        atr(frame, config.atr_period).iloc[-1],
        last.close,
    ]
    if not np.isfinite(values).all() or last.close <= 0:
        raise ValueError("Indikator belum valid; analisis ditunda.")
    return dict(
        trend=trend,
        rsi=float(strength),
        macd=float(histogram.iloc[-1]),
        momentum="menguat"
        if histogram.iloc[-1] > histogram.iloc[-2]
        else ("melemah" if histogram.iloc[-1] < histogram.iloc[-2] else "tetap"),
        atr_pct=float(values[3] / last.close * 100),
        relative_volume=relative_volume,
        low=low,
        high=high,
        location=location,
        close=float(last.close),
        closed_at=last.close_time.isoformat(),
        **anatomy,
    )


def analysis_report(charts, query, intervals, config):
    intervals = list(dict.fromkeys(intervals))
    if not 1 <= len(intervals) <= 4 or any(i not in INTERVALS for i in intervals):
        raise ValueError("Pilih 1-4 interval valid. Contoh: /analyze BTC 1m 5m 15m")
    market = charts.resolve(query)
    lines = [f"ANALISIS CANDLE {market['symbol']} | harga dalam {market['quoteAsset']}"]
    results = []
    for interval in intervals:
        try:
            _, frame = charts.candles(market["symbol"], interval)
            result = describe(frame, config)
        except Exception:
            # No transport details/tokens; a missing timeframe cannot count as agreement.
            lines.append(f"{interval}: tidak tersedia / histori belum cukup atau tidak valid.")
            continue
        results.append(result)
        volume = "N/A" if result["relative_volume"] is None else f"{result['relative_volume']:.2f}x"
        lines.append(
            f"\n{interval} | tren {result['trend']} | close {result['close']:.8g}\n"
            f"RSI {result['rsi']:.1f} | MACD hist {result['macd']:.4g} ({result['momentum']})\n"
            f"ATR {result['atr_pct']:.2f}% | volume {volume} rata-rata sebelumnya\n"
            f"Range {config.bb_period} candle: {result['low']:.8g}-{result['high']:.8g}; "
            f"{result['location']}\n"
            f"Body {result['body_pct']:.0f}% | wick atas/bawah "
            f"{result['upper_wick_pct']:.0f}%/{result['lower_wick_pct']:.0f}%\n"
            f"Tutup UTC: {result['closed_at']}"
        )
    if len(results) != len(intervals):
        alignment = "DATA TIDAK LENGKAP; keselarasan tidak dinilai."
    elif len(results) == 1:
        alignment = "Satu timeframe; belum ada konfirmasi lintas timeframe."
    elif all(r["trend"] == "naik" for r in results):
        alignment = "Tren naik selaras pada timeframe yang diminta."
    elif all(r["trend"] == "turun" for r in results):
        alignment = "Tren turun selaras pada timeframe yang diminta."
    else:
        alignment = "Tren campuran; belum selaras lintas timeframe."
    lines.extend(
        [
            "\n" + alignment,
            "Deskripsi histori, bukan probabilitas/izin BUY. "
            "Spread, likuiditas, biaya dan risk gate tetap wajib dicek engine.",
        ]
    )
    return "\n".join(lines)
