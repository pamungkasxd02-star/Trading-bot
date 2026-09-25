"""Owner-only reply keyboard and short-lived guided input."""

import re

from spotlab.market_charts import INTERVALS

MAIN_ROWS = [
    ["Lihat candle", "Status akun"],
    ["Pasar dan coin", "Strategi dan analisis"],
    ["Akun demo", "Notifikasi"],
    ["Panduan dan bantuan"],
]
DEMO_ROWS = [
    ["Status akun", "Posisi aktif"],
    ["Kenapa belum buy?", "Pengaturan"],
    ["Coin eligible", "Pilih coin demo"],
    ["Jeda auto-buy demo", "Aktifkan auto-buy demo"],
    ["Menu utama"],
]
SECTIONS = {
    "/menu": MAIN_ROWS,
    "/demo": DEMO_ROWS,
    "/marketmenu": [
        ["Cari coin", "Detail coin"],
        ["Semua pair USDT", "Semua pair Spot"],
        ["Lihat candle", "Cakupan pasar"],
        ["Menu utama"],
    ],
    "/analysismenu": [
        ["Analisis coin", "Sinyal terbaru"],
        ["Daftar strategi", "Cek teknik coin"],
        ["Rencana entry demo"],
        ["Menu utama"],
    ],
    "/notifications": [
        ["Pilih notifikasi coin", "Pengaturan"],
        ["Gambar otomatis ON", "Gambar otomatis OFF"],
        ["Hanya setup", "Semua pengamatan"],
        ["Menu utama"],
    ],
    "/helpmenu": [
        ["Cara pakai", "Arti istilah"],
        ["Data dan riset", "Bot tidak merespons"],
        ["Menu utama"],
    ],
}
PANELS = {
    "/marketmenu": "PASAR DAN COIN - hanya melihat data\n"
    "Cari coin: cari ticker/pair. Detail coin: pasangan dan alasan filter.\n"
    "Semua pair: katalog dengan tombol halaman. Lihat candle: pilih coin lalu interval.\n"
    "Cakupan pasar: bedakan katalog tersedia dengan daftar collector akun.",
    "/analysismenu": "STRATEGI DAN ANALISIS - tidak membuat order\n"
    "Analisis coin: bandingkan beberapa timeframe. Sinyal terbaru: analisis tersimpan.\n"
    "Daftar strategi: teknik dan strategi akun. Cek teknik coin: hasil tiap aturan.\n"
    "Rencana entry demo: simulasi harga acuan, ukuran, SL/TP dan biaya. Bukan tombol BUY.",
    "/notifications": "NOTIFIKASI - hanya mengubah pesan otomatis\n"
    "Pilih notifikasi coin: batasi gambar pada coin eligible.\n"
    "Gambar ON/OFF: tidak menjeda trading atau balasan command.\n"
    "Hanya setup: kirim gambar saat setup. Semua pengamatan: tidak perlu menunggu setup.\n"
    "Cooldown tetap berlaku. Periksa pilihan aktif lewat Pengaturan.",
    "/helpmenu": "PANDUAN DAN BANTUAN\n"
    "Cara pakai: alur pemula. Arti istilah: baca metrik.\n"
    "Data dan riset: pahami dataset dan belajar strategi.\n"
    "Bot tidak merespons: langkah pemeriksaan. /menu selalu membuka menu utama.",
    "/glossary": "ARTI ISTILAH\n"
    "Candle: harga buka, tertinggi, terendah, tutup dan volume dalam satu interval.\n"
    "1m = 1 menit; 1h = 1 jam; 1d = 1 hari; 1M = 1 bulan.\n"
    "Setup: syarat sinyal terpenuhi, belum tentu order. WAIT: menunggu.\n"
    "Eligible: masuk pilihan scanner; masih tunduk pada risk/setting akun.\n"
    "SL/TP: batas keluar rugi/target untung virtual, memerlukan bot berjalan.\n"
    "WR: persentase trade untung. PF: total untung dibagi total rugi.\n"
    "Expectancy: rata-rata PnL per trade. Drawdown: penurunan equity dari puncak.\n"
    "N/A: belum ada dasar perhitungan; bukan angka nol. WR tinggi tidak menjamin untung.",
    "/datahelp": "DATA DAN RISET\n"
    "Cakupan pasar menunjukkan daftar collector akun, bukan jumlah data training.\n"
    "Grafik manual mengambil data publik. Dataset riset memakai proses terpisah.\n"
    "Ribuan job pada rencana batch bukan ribuan dataset yang sudah selesai.\n"
    "Menyimpan candle tidak otomatis melatih ML. Strategi harus diuji setelah fee/slippage.\n"
    "Menu ini tidak menjalankan unduhan besar, training, atau membuka live.",
    "/troubleshoot": "BOT TIDAK MERESPONS?\n"
    "1. Gunakan chat pribadi pemilik. Kirim /menu lagi, bukan pesan lama.\n"
    "2. Jika tombol tersembunyi, tekan ikon keyboard Telegram.\n"
    "3. Collector harus aktif dan bootstrap selesai; satu bot untuk satu collector.\n"
    "4. Request grafik/analisis dapat menunda balasan berikutnya.\n"
    "5. Setelah update kode, restart proses dengan config yang sama.\n"
    "6. Cek pengaturan Telegram dan log lokal. Jangan kirim token/API secret ke chat.",
}


def section_keyboard(control):
    return keyboard(SECTIONS.get(control.get("menu_section", "/menu"), MAIN_ROWS))


BUTTONS = {
    "Pasar dan coin": "/marketmenu",
    "Strategi dan analisis": "/analysismenu",
    "Akun demo": "/demo",
    "Notifikasi": "/notifications",
    "Panduan dan bantuan": "/helpmenu",
    "Arti istilah": "/glossary",
    "Data dan riset": "/datahelp",
    "Bot tidak merespons": "/troubleshoot",
    "Hanya setup": "/mode setups",
    "Semua pengamatan": "/mode observe",
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
    "1. Menu utama -> Status akun: lihat koneksi/data, saldo virtual, posisi dan hasil trade.\n"
    "2. Pasar dan coin -> Cari coin: temukan pair Binance Spot.\n"
    "3. Lihat candle: tekan tombol lalu ketik BTC 15m untuk gambar.\n"
    "4. Strategi dan analisis -> Analisis coin: pilih coin, lalu preset Scalping/Intraday/Swing.\n"
    "5. Akun demo: pilih coin eligible dan jeda/aktifkan entry otomatis.\n\n"
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
        return "", "Kirim teks atau pilih tombol.", section_keyboard(control)
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
        command = text.split()[0].lower()
        if command in {"/start", "/menu"}:
            control["menu_section"] = "/menu"
        elif command in SECTIONS:
            control["menu_section"] = command
        return text, None, section_keyboard(control)
    pending = control.get("menu_prompt")
    if pending and now > pending["expires"]:
        control.pop("menu_prompt", None)
        return "", "Pilihan kedaluwarsa. Pilih tombol lagi.", section_keyboard(control)
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
        return command + " " + text, None, section_keyboard(control)
    control["menu_section"] = "/menu"
    return "/menu", None, keyboard(MAIN_ROWS)


BROWSER_ROWS = [
    ["Halaman sebelumnya", "Halaman berikut"],
    ["Detail coin", "Lihat candle"],
    ["Menu utama"],
]


def metric(value, suffix=""):
    return "N/A" if value is None else f"{value:.2f}{suffix}"


def health_label(value):
    return {
        "healthy": "sehat",
        "degraded": "data/koneksi belum lengkap",
        "offline": "proses tidak aktif",
    }.get(value, value)
