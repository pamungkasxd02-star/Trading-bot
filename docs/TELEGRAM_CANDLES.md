# Grafik candle ke Telegram

Collector demo/belajar dapat mengirim PNG candle tertutup, garis EMA cepat/lambat,
volume, timestamp UTC, skor dan checklist alasan setup. Tidak menyertakan saldo,
API key Binance, chat ID, atau identitas akun trading dalam gambar/caption.
Ini notifikasi analisis; bukan perintah beli dan tidak membuka gate live.

## Aktivasi

1. Buat bot lewat akun resmi **@BotFather** di Telegram. Simpan token secara privat.
2. Buka chat dengan bot dan tekan **Start**. Gunakan chat pribadi untuk awal.
3. Simpan `TELEGRAM_BOT_TOKEN` dan `TELEGRAM_CHAT_ID` pada `.env` lokal atau Codespaces
   Secrets. Jangan isi YAML/README atau mengirim token di percakapan/issue/screenshot.
   Chat ID harus milik chat tujuan. Jika belum tahu ID, lihat update bot melalui Bot API
   dari lingkungan privat setelah mengirim pesan ke bot; jangan membagikan URL/token
   atau memakai bot pihak ketiga yang meminta token. Bot juga dapat mengirim ke grup
   jika ditambahkan dan diberi izin; anggota grup akan dapat melihat gambarnya.
4. Tambahkan blok berikut ke config yang dipakai, misalnya `config/candle-study.yaml`:

```yaml
candle_alerts:
  enabled: true
  setups_only: true
  symbols: []
  bars: 60
  min_interval_seconds: 60
  symbol_cooldown_seconds: 900
```

`symbols: []` berarti menerima setup dari semua pair yang dipindai. Untuk watchlist,
isi misalnya `[BTCUSDT, ETHUSDT]` dengan huruf besar. Untuk belajar candle walau belum
ada setup, ubah `setups_only: false`; gunakan watchlist kecil agar hasil mudah dibaca.
Batas pengiriman tetap berlaku; tidak setiap candle akan dikirim.

```bash
bash scripts/candle-study.sh
# Atau, akun demo yang mensimulasikan trade:
bash scripts/all-scalping-demo.sh
```

`candle_alerts.enabled` berbeda dari `runtime.telegram_enabled` milik executor
Testnet/live. Default candle alerts mati. Mode demo hanya memuat dua secret Telegram
ketika fitur ini aktif, tidak memuat kredensial exchange ke adapter demo. Mengubah
pengaturan notifikasi tidak mengubah strategi atau saldo akun.

## Preview tanpa mengirim

Setelah collector mempunyai data:

```bash
.venv/bin/python -m spotlab --config config/candle-study.yaml demo-chart --symbol BTCUSDT --output exports/candle-preview.png
```

Buka PNG tersebut dari Explorer Codespaces. Preview memakai candle tertutup terakhir
yang tersimpan dan mencantumkan waktunya; jika collector berhenti, gambar bisa lama.
Preview tidak menghubungi Telegram dan tidak memerlukan token. Data minimal dua candle.
Windows: ganti `.venv/bin/python` dengan `.venv\Scripts\python.exe`.

## Isi dan ketahanan pengiriman

- PNG menampilkan maksimal `bars` candle dan EMA; caption berisi SETUP atau OBSERVE,
  harga close, score (bukan WR), waktu dan checklist entry.
- Notifikasi otomatis hanya memakai candle hingga waktu sinyal tersebut. History yang
  berlubang, tidak lengkap atau sinyal yang sudah kedaluwarsa dilewati.
- Maksimal satu upaya per interval global; cooldown per coin juga disimpan di SQLite.
  Tidak ada jaminan satu foto per coin atau per candle saat semua pair ramai bersamaan.
- Pencatatan upaya terjadi sebelum upload. Ini mencegah pengulangan pada restart,
  tetapi crash/timeout dapat membuat pesan hilang atau statusnya tidak pasti. Tidak
  ada retry otomatis foto yang sama; sinyal selanjutnya dapat dikirim setelah jeda.
- Respons HTTP pembatasan memakai `retry_after` (dibatasi 60 detik–24 jam); kegagalan
  lain tetap diberi jeda. Gangguan Telegram tidak menghentikan pengumpulan harga.
- Render dan upload dijalankan di worker terpisah agar loop harga tidak menunggu HTTP
  Telegram; beban CPU rendering tetap perlu dipantau. HTTP memiliki timeout 15 detik.
- Lihat `candle_alerts.last_status` dan `next_at` melalui `demo-status`, serta event
  `candle_alert` pada export. Error tidak mencetak URL yang memuat token.

## Privasi dan batasan

Gambar/caption dikirim ke layanan Telegram dan chat yang dikonfigurasi. Pengiriman
memakai `protect_content`, tetapi tidak dapat menjamin penerima tidak mengambil foto
layar atau menyalin informasi secara manual. Tidak perlu membuka port publik/webhook;
integrasi ini outbound saja dan belum menyediakan command bot seperti `/buy`/`sell`.

Token yang pernah bocor harus dicabut/dirotasi melalui BotFather. Jangan menjalankan
mode debug jaringan yang mencetak URL request. Ikuti [panduan privasi](CODESPACES_PRIVACY.md).
Tidak ada bot/chat pengguna yang dibuat atau dikirim pesan selama implementasi ini.
Tes memakai transport tiruan; pengiriman nyata menunggu token, chat tujuan, dan collector
aktif pada lingkungan pengguna. Fitur ini tidak membuktikan peningkatan win rate.

Referensi: [Telegram sendPhoto](https://core.telegram.org/bots/api#sendphoto).
