"""Owner-only reply keyboard and short-lived guided input."""

MAIN_ROWS = [
    ["Status akun", "Cara pakai"],
    ["Cari coin", "Lihat candle"],
    ["Analisis coin", "Sinyal terbaru"],
    ["Atur demo", "Pengaturan"],
]
DEMO_ROWS = [
    ["Coin eligible", "Pilih coin demo"],
    ["Jeda auto-buy demo", "Aktifkan auto-buy demo"],
    ["Pilih notifikasi coin", "Gambar otomatis ON", "Gambar otomatis OFF"],
    ["Menu utama"],
]
BUTTONS = {
    "Status akun": "/status",
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
    "Cari coin": (
        "/coins",
        "Ketik ticker/nama, misalnya SOL atau bitcoin. Balas USDT untuk pair USDT.",
    ),
    "Lihat candle": (
        "/chart",
        "Ketik coin dan interval, misalnya BTC 15m atau ETHUSDT 1h.\n"
        "Tanpa interval memakai timeframe akun. /intervals untuk daftar.",
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
    "4. Analisis coin: ketik BTC untuk membandingkan beberapa timeframe.\n"
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


def route(text, control, now):
    """Return command text, optional prompt, optional keyboard. Called after auth."""
    text = text.strip()
    if text in PROMPTS:
        command, prompt = PROMPTS[text]
        control["menu_prompt"] = dict(command=command, expires=now + 300)
        return "", prompt + "\nBerlaku 5 menit. Tekan Batal untuk kembali.", keyboard([["Batal"]])
    if text in BUTTONS:
        text = BUTTONS[text]
    if text.startswith("/"):
        control.pop("menu_prompt", None)
        return text, None, None
    pending = control.pop("menu_prompt", None)
    if pending and now <= pending["expires"]:
        return pending["command"] + " " + text, None, keyboard(MAIN_ROWS)
    if pending:
        return "", "Pilihan kedaluwarsa. Pilih tombol lagi.", keyboard(MAIN_ROWS)
    return "/menu", None, None
