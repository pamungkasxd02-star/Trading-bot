"""Read-only explanations from demo state; no inferred execution guarantees."""

import json

from spotlab.telegram_text import number, utc_time

SKIP_REASONS = {
    "spread_too_wide": "spread terlalu lebar",
    "signal_price_drift": "harga sudah terlalu jauh dari sinyal",
    "candle_participation_limit": "ukuran order terlalu besar dibanding volume candle",
    "insufficient_virtual_cash": "saldo virtual tidak cukup",
}


def position_report(account):
    status = account.status()
    p = status["position"]
    if not p:
        return "Belum ada posisi demo terbuka. Lihat Kenapa belum buy? untuk pemeriksaan akun."
    return (
        f"Posisi demo · {p['symbol']}\n\n"
        f"Entry: {number(p['entry_price'])} USDT\n"
        f"Jumlah: {number(p['quantity'])}\n\n"
        f"Stop-loss: {number(p['stop_price'])}\n"
        f"take-profit: {number(p['take_profit_price'])}\n"
        f"\nDibuka: {utc_time(p['entry_time'])}\n"
        "\nSL/TP virtual memerlukan bot aktif dan data harga tersedia."
    )


def why_report(account):
    status = account.status()
    control = status.get("telegram_control", {})
    lines = ["Kenapa belum buy?", ""]
    if account.config.demo.analysis_only:
        lines.append("- Mode belajar: memang tidak membuka posisi.")
    if not control.get("auto", True):
        lines.append("- Auto entry dijeda. Atur demo untuk mengubahnya.")
    if status["trading_halted"]:
        lines.append("- Risk halt/kill-switch aktif; periksa lokal. Menu tidak bisa meresetnya.")
    if not status["process_alive"]:
        lines.append("- Heartbeat proses tidak aktif; periksa collector.")
    elif status["health"] != "healthy":
        lines.append("- Data/koneksi sebagian belum sehat; cek collector dan umur sinyal.")
    if status["position"]:
        lines.append(f"- Posisi {status['position']['symbol']} masih terbuka; batas satu posisi.")
    selected = control.get("tradecoins", [])
    lines.append("Coin entry: " + (", ".join(selected[:20]) if selected else "semua eligible"))
    rows = account.signals(2000)
    scoped = [r for r in rows if not selected or r["symbol"] in selected]
    fresh = [r for r in scoped if r["fresh_now"]]
    setups = [r for r in fresh if r["assessment"] == "setup_detected"]
    lines.append(
        f"Sampel maksimal 2000 coin: {len(scoped)} analisis tersimpan, "
        f"{len(fresh)} segar, {len(setups)} setup entry segar dalam pilihan coin."
    )
    if not scoped:
        lines.append("Belum ada analisis pada pilihan ini. Tunggu bootstrap/candle tertutup.")
    elif not fresh:
        lines.append("Analisis tersimpan sudah kedaluwarsa; bukan izin entry baru.")
    elif not setups:
        lines.append("Belum ada setup entry segar yang memenuhi aturan strategi.")
    else:
        lines.append(
            "Setup terdeteksi belum berarti order: harga, spread, "
            "saldo dan risk dicek saat eksekusi."
        )
    with account.connect() as conn:
        events = conn.execute(
            "SELECT timestamp,payload FROM demo_records WHERE kind='event' "
            "ORDER BY id DESC LIMIT 200"
        ).fetchall()
    for event in events:
        payload = json.loads(event["payload"])
        if payload.get("event") == "entry_skipped":
            reason = SKIP_REASONS.get(payload.get("reason"), "validasi eksekusi/risk menolak entry")
            lines.append(
                f"Riwayat skip terakhir (bisa sudah lama): {utc_time(event['timestamp'])}\n{reason}"
            )
            break
    lines.append("\nRingkasan kondisi akun; tidak mengirim order.")
    return "\n".join(lines)
