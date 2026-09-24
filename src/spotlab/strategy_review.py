"""Explain and compare existing strategy implementations without placing orders."""

import numpy as np

from spotlab.market_charts import INTERVALS
from spotlab.strategies import STRATEGIES, build_strategy

TECHNIQUES = {
    "rule_based_v1": (
        "EMA crossover",
        "Cross EMA baru + tren SMA; konfirmasi RSI, MACD, Bollinger dan volume.",
    ),
    "quality_cross_v1": (
        "Quality crossover",
        "Baseline ditambah ADX, ATR, volume relatif dan pembatas candle ekstrem/jarak harga.",
    ),
    "adaptive_trend_v2": (
        "Trend pullback",
        "Tren EMA harian + pullback/persilangan pulih, momentum dan kualitas volume.",
    ),
    "regime_reversion_v3": (
        "Rebound sesuai regime",
        "Bedakan tren/range; rebound RSI/Bollinger terkonfirmasi, hindari regime bearish.",
    ),
    "curve_scalping_v1": (
        "Curve scalping",
        "Slope tren, pullback EMA, close melewati high sebelumnya, momentum dan kualitas candle.",
    ),
}


def catalogue(active):
    lines = [f"STRATEGI AKUN: {active}"]
    for name, (title, detail) in TECHNIQUES.items():
        lines.append(f"\n{title} ({name})\n{detail}")
    lines.append(
        "\n/techniques SOL 15m membandingkan aturan pada coin pilihan. "
        "Tidak mengganti strategi aktif. Skor bukan peluang menang; "
        "strategi belum dijamin profitable. SL/TP, biaya dan risk tetap di engine."
    )
    return "\n".join(lines)


def evaluate(frame, config, name):
    minimum = max(
        config.sma_trend + config.pullback_lookback + 1,
        config.ema_slow + config.pullback_lookback + 1,
        config.macd_slow + config.macd_signal + 1,
        config.volume_period + 2,
        config.rsi_period + 2,
        config.bb_period + 2,
        config.adx_period * 2 + 2,
        config.atr_period + 2,
    )
    if len(frame) < minimum:
        return {"state": "DATA KURANG", "detail": f"Butuh minimal {minimum} candle."}
    if name in {"adaptive_trend_v2", "regime_reversion_v3"}:
        # Exclude first partial day and current day from daily warmup coverage.
        days = (
            frame.close_time.iloc[-1].normalize() - frame.open_time.iloc[0].normalize()
        ).days - 1
        if days < config.daily_ema_period + 1:
            return {
                "state": "DATA KURANG",
                "detail": "Butuh histori EMA harian lengkap; gunakan dataset historis.",
            }
    prepared = build_strategy(name, config=config).prepare(frame)
    required = ["ema_fast", "ema_slow", "sma_trend", "rsi", "macd_hist", "bb_lower", "volume_sma"]
    if name != "rule_based_v1":
        required += ["adx", "atr_pct", "relative_volume"]
    if name in {"adaptive_trend_v2", "regime_reversion_v3"}:
        required += ["daily_ema"]
    if name == "regime_reversion_v3":
        required += ["daily_change_pct", "fast_rsi", "close_location"]
    if not np.isfinite(prepared[required].tail(2).to_numpy(dtype=float)).all():
        return {
            "state": "DATA TIDAK VALID",
            "detail": "Indikator belum siap/volume pembanding nol.",
        }
    row = prepared.iloc[-1]
    state = "EXIT CONDITION" if row.exit_long else "SETUP ENTRY" if row.enter_long else "WAIT"
    checks = [
        f"{col[6:]}={'lolos' if bool(row[col]) else 'belum'}"
        for col in prepared
        if col.startswith("check_")
    ]
    if "entry_quality_ok" in row and not checks:
        checks.append("quality=" + ("lolos" if row.entry_quality_ok else "belum"))
    detail = str(row.signal_reason)
    if checks:
        detail += "\n" + ", ".join(checks)
    return {"state": state, "detail": detail}


def review(charts, query, interval, config):
    if interval not in INTERVALS:
        raise ValueError("Interval tidak valid; lihat /intervals.")
    market, frame = charts.candles(query, interval)
    lines = [
        f"TEKNIK {market['symbol']} | {interval} | candle tertutup",
        f"Tutup UTC: {frame.close_time.iloc[-1].isoformat()}",
        f"Strategi akun: {config.name}",
    ]
    for name in STRATEGIES:
        try:
            result = evaluate(frame, config, name)
        except Exception:
            result = {
                "state": "TIDAK TERSEDIA",
                "detail": "Evaluasi gagal; bukan konfirmasi entry.",
            }
        lines.append(f"\n{TECHNIQUES[name][0]}: {result['state']}\n{result['detail']}")
    lines.append(
        "\nPerbandingan memakai parameter akun yang sama, bukan optimasi per strategi. "
        "SETUP bukan order; EXIT bukan short. Teknik saling berkorelasi, "
        "bukan voting/probabilitas. Tidak mengubah auto-buy atau belajar otomatis."
    )
    return "\n".join(lines)
