"""Owner-only reply keyboard and short-lived guided input."""

import re

from spotlab.market_charts import INTERVALS

MAIN_ROWS = [
    ["Status akun", "Cara pakai"],
    ["Cari coin", "Lihat candle"],
    ["Analisis coin", "Sinyal terbaru"],
    ["Atur demo", "Pengaturan"],
    ["Kenapa belum buy?", "Posisi aktif"],
    ["Daftar strategi", "Cek teknik coin"],
    ["Rencana entry demo"],
    ["Semua pair USDT", "Semua pair Spot"],
    ["Cakupan pasar", "Detail coin"],
]
DEMO_ROWS = [
    ["Coin eligible", "Pilih coin demo"],
    ["Jeda auto-buy demo", "Aktifkan auto-buy demo"],
    ["Pilih notifikasi coin", "Gambar otomatis ON", "Gambar otomatis OFF"],
    ["Menu utama"],
]
BUTTONS = {
    "Status akun": "/status",
    "Semua pair USDT": "/markets USDT",
    "Semua pair Spot": "/markets ALL",
    "Cakupan pasar": "/coverage",
    "Daftar strategi": "/strategies",
    "Kenapa belum buy?": "/why",
    "Posisi aktif": "/position",
    "Cara pakai": "/guide",
    "Sinyal terbaru": "/signals",
    "Atur demo": "/demo",
    "Pengaturan": "/settings",
    "Coin eligible": "/eligible",
    "Jeda auto-buy demo": "/auto off",
    "Aktifkan auto-buy demo": "/auto on",
    "Gambar otomatis ON": "/alerts on",
    "Gambar otomatis OFF": "/alerts off",
    "Menu utama": "/menu",
    "Batal": "/menu",
}
PROMPTS = {
    "Detail coin": (
        "/coin",
        "Ketik ticker seperti SOL untuk melihat semua pasangan dan alasan filter.",
    ),
    "Rencana entry demo": (
        "/plan",
        "Pilih coin/timeframe untuk simulasi sizing, SL dan TP. Tidak membuat order.",
    ),
    "Cek teknik coin": (
        "/techniques",
        "Pilih coin lalu timeframe untuk membandingkan aturan strategi.",
    ),
    "Cari coin": (
        "/coins",
        "Ketik ticker/nama, misalnya SOL atau bitcoin. Balas USDT untuk pair USDT.",
    ),
    "Lihat candle": (
        "/chart",
        "Ketik coin dan interval, misalnya BTC 15m atau ETHUSDT 1h.\n"
        "Coin saja membuka pilihan timeframe berikutnya.",
    ),
    "Analisis coin": (
        "/analyze",
        "Ketik coin, misalnya SOL, atau BTC 1m 5m 15m. Maksimal 4 timeframe.",
    ),
    "Pilih coin demo": (
        "/tradecoins",
        "Ketik coin eligible, misalnya BTC ETH, atau ALL. "
        "Ini membatasi entry demo baru; tidak membeli langsung. /eligible untuk daftar.",
    ),
    "Pilih notifikasi coin": (
        "/watch",
        "Ketik coin eligible, misalnya BTC ETH, atau ALL. Hanya mengatur gambar otomatis.",
    ),
}
GUIDE = (
    "CARA PAKAI\n"
    "1. Status akun: lihat koneksi/data, saldo virtual, posisi dan hasil trade.\n"
    "2. Cari coin: temukan pair Binance Spot.\n"
    "3. Lihat candle: tekan tombol lalu ketik BTC 15m untuk gambar.\n"
    "4. Analisis coin: pilih coin, lalu preset Scalping/Intraday/Swing.\n"
    "5. Atur demo: pilih coin eligible dan jeda/aktifkan entry otomatis.\n\n"
    "Demo memakai saldo virtual. Akun belajar hanya menganalisis; tidak bisa buy. "
    "Auto-buy menunggu sinyal yang lolos filter, bukan membeli setiap harga naik. "
    "Jeda menghentikan entry baru; posisi terbuka tetap dikelola saat bot berjalan.\n"
    "WR = persentase trade untung; PF = total untung / total rugi; "
    "expectancy = rata-rata PnL/trade.\n"
    "Melihat chart/analisis tidak mengubah trading. /menu atau Batal kembali ke menu."
)


def keyboard(rows):
    return dict(
        keyboard=rows,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Pilih tombol atau ketik /menu",
    )


COIN_ROWS = [["BTC", "ETH", "SOL"], ["Batal"]]
TIME_ROWS = [["1m", "5m", "15m"], ["1h", "4h", "1d"], ["Kembali", "Batal"]]
ANALYSIS_ROWS = [["Scalping", "Intraday", "Swing"], ["Kembali", "Batal"]]
PRESETS = {"Scalping": "1m 5m 15m", "Intraday": "15m 1h 4h", "Swing": "4h 1d 1w"}


def route(text, control, now):
    """Return command text, optional prompt, optional keyboard. Called after auth."""
    text = text.strip()
    if not text:
        return "", "Kirim teks atau pilih tombol.", keyboard(MAIN_ROWS)
    if text in {"Halaman berikut", "Halaman sebelumnya"}:
        control.pop("menu_prompt", None)
        saved = control.get("market_browser", {"quote": "USDT", "page": 1})
        page = max(1, saved["page"] + (1 if text == "Halaman berikut" else -1))
        return f"/markets {saved['quote']} {page}", None, None
    if text in PROMPTS:
        command, prompt = PROMPTS[text]
        control["menu_prompt"] = dict(command=command, expires=now + 300)
        rows = (
            COIN_ROWS if command in {"/chart", "/analyze", "/techniques", "/plan"} else [["Batal"]]
        )
        return "", prompt + "\nPilih/ketik coin. Berlaku 5 menit.", keyboard(rows)
    if text in BUTTONS:
        text = BUTTONS[text]
    if text.startswith("/"):
        control.pop("menu_prompt", None)
        return text, None, None
    pending = control.get("menu_prompt")
    if pending and now > pending["expires"]:
        control.pop("menu_prompt", None)
        return "", "Pilihan kedaluwarsa. Pilih tombol lagi.", keyboard(MAIN_ROWS)
    if pending:
        command = pending["command"]
        if text == "Kembali":
            pending.pop("coin", None)
            return "", "Pilih atau ketik coin lagi.", keyboard(COIN_ROWS)
        if command in {"/chart", "/analyze", "/techniques", "/plan"}:
            if "coin" not in pending:
                parts = text.split()
                if not re.fullmatch(r"[A-Za-z0-9/-]{1,40}", parts[0]):
                    return "", "Gunakan ticker seperti BTC atau pair ETH/USDT.", keyboard(COIN_ROWS)
                coin, intervals = parts[0], parts[1:]
                if not intervals:
                    pending["coin"] = coin
                    rows = (
                        TIME_ROWS
                        if command in {"/chart", "/techniques", "/plan"}
                        else ANALYSIS_ROWS
                    )
                    hint = (
                        "interval, misalnya 15m"
                        if command in {"/chart", "/techniques", "/plan"}
                        else "preset atau 1m 5m 15m"
                    )
                    return "", f"Coin: {coin}. Pilih {hint}.", keyboard(rows)
            else:
                coin = pending["coin"]
                intervals = (PRESETS.get(text, text) if command == "/analyze" else text).split()
            limit = 1 if command in {"/chart", "/techniques", "/plan"} else 4
            if not 1 <= len(intervals) <= limit or any(i not in INTERVALS for i in intervals):
                pending["coin"] = coin
                rows = TIME_ROWS if command in {"/chart", "/techniques", "/plan"} else ANALYSIS_ROWS
                return "", f"Pilih 1-{limit} interval valid. " + " ".join(INTERVALS), keyboard(rows)
            text = coin + " " + " ".join(intervals)
        control.pop("menu_prompt", None)
        return command + " " + text, None, keyboard(MAIN_ROWS)
    return "/menu", None, None


BROWSER_ROWS = [
    ["Halaman sebelumnya", "Halaman berikut"],
    ["Detail coin", "Lihat candle"],
    ["Menu utama"],
]
