# Kontrol demo dari Telegram

Fitur ini mengendalikan akun **demo internal** yang sedang berjalan. Tidak mempunyai
perintah order Binance asli, tidak mengubah API key, dan tidak membuka gate live.

## Aktifkan

Simpan token dan chat ID privat numerik pada `.env`/Codespaces Secrets, seperti
[panduan gambar candle](TELEGRAM_CANDLES.md). Pada config akun yang dijalankan:

```yaml
candle_alerts:
  enabled: true
  commands_enabled: true
  setups_only: true
  symbols: []
  bars: 60
  min_interval_seconds: 60
  symbol_cooldown_seconds: 900
```

Gunakan `config/all-scalping-demo.yaml` dan `bash scripts/all-scalping-demo.sh` untuk
simulasi auto-buy. `config/candle-study.yaml` tetap khusus analisis dan menolak `/auto on`.
Tunggu bootstrap/collector siap, lalu kirim `/help` ke bot. Gunakan satu bot Telegram
khusus untuk satu collector aktif: dua proses yang memanggil getUpdates akan bersaing.
Webhook yang sudah dipakai aplikasi lain perlu ditinjau sendiri; kode tidak menghapusnya.

Perintah hanya diterima dalam **chat pribadi** dengan chat ID dan ID pengirim sama
seperti `TELEGRAM_CHAT_ID`. Grup/channel tidak didukung untuk kontrol. Jangan memakai
username sebagai ID kontrol. Semua pesan sebelum startup, lebih dari dua menit,
atau update yang sudah diproses diabaikan. Pada awal polling, backlog lama dilewati.

## Menu

| Perintah | Hasil |
| --- | --- |
| `/help` | Daftar perintah |
| `/status` atau `/health` | Health, equity virtual, jumlah trade, WR, PF, expectancy, posisi, halt |
| `/coins 1` | Daftar pair yang lolos scanner, 40 pair per halaman |
| `/signals` | Sampai 20 analisis tersimpan terbaru; stale ditandai |
| `/signals BTCUSDT` | Analisis terakhir coin yang dipilih |
| `/settings` | Watchlist, cakupan auto-buy, mode dan jeda gambar |
| `/watch BTCUSDT ETHUSDT` | Batasi notifikasi gambar otomatis ke coin tersebut |
| `/watch ALL` | Gambar dari semua pair yang dipindai, tetap dibatasi frekuensi |
| `/chart BTCUSDT` | Minta satu grafik candle terbaru dari cache |
| `/mode observe` | Gambar pengamatan, tidak harus menunggu setup |
| `/mode setups` | Gambar hanya ketika setup entry terdeteksi |
| `/alerts off` atau `/alerts on` | Matikan/hidupkan gambar otomatis |
| `/tradecoins BTCUSDT ETHUSDT` | Batasi entry demo baru pada coin tersebut |
| `/tradecoins ALL` | Semua pair eligible boleh dipilih strategi untuk entry demo |
| `/auto off` | Hentikan entry demo baru; posisi yang ada tetap dikelola SL/TP |
| `/auto on` | Izinkan entry demo dari sinyal baru bila risk halt/kill-switch tidak aktif |

Perubahan watchlist/mode/auto disimpan di database, bertahan saat restart. `/watch`
tidak mengubah coin trading; `/tradecoins` tidak menutup posisi yang sudah ada.
`/alerts off` tidak mematikan balasan command atau pesan order demo. Pesan DEMO BUY/SELL
menyatakan eksekusi virtual; lihat `/status` untuk hasil akun. Setting ini berlaku hanya
pada database akun terkait, bukan akun lain atau konfigurasi Testnet/live.

Akun demo trading sebelumnya memang melakukan entry otomatis saat memenuhi syarat.
Mengaktifkan command tidak otomatis mem-pause akun tersebut; periksa `/status`, gunakan
`/auto off` jika ingin menunda. `/auto on` tidak memaksa buy dan membersihkan pending
lama agar entry berikutnya menunggu sinyal baru. Risk halt/kill-switch tidak dapat
reset melalui Telegram. Posisi offline tidak dilindungi stop exchange.

## Seleksi coin dan entry

Harga yang naik saja tidak cukup. Scanner memfilter status Spot, volume 24 jam,
spread, dukungan order dan base pengecualian. Strategi kurva memerlukan tren, pullback,
pemulihan terkonfirmasi, ADX/ATR/volume dan skor minimum. Sebelum entry, engine mengecek
spread saat itu, umur sinyal, pergeseran harga, lot/minimum notional, partisipasi volume,
saldo dan batas risiko. Maksimal satu posisi untuk akun; fee/slippage tetap dihitung.

Filter ini mengurangi sebagian kondisi trading buruk; bukan penilaian fundamental,
audit token, pemeriksaan manipulasi atau jaminan bebas scam. Volume 24 jam dan daftar
coin berasal dari snapshot startup, belum hot-refresh. Tidak semua crypto/exchange
tercakup. Kurva masa lalu tidak menjamin harga akan terus naik. WR dan profitabilitas
preset masih perlu diuji pada data 1m forward; pajak belum termasuk PnL simulator.

## Ketahanan dan privasi

Polling memakai request keluar, tanpa port publik/webhook. Satu update diproses per
putaran (sekitar 5 detik setelah request selesai), lalu pesan order baru bila ada.
Gangguan command diberi jeda 60 detik; collector tetap berjalan. Grafik manual yang
histori terakhirnya lebih dari 120 detik ditolak. Timestamp gambar tetap perlu dibaca.

Perubahan state dan nomor update disimpan sebelum balasan dikirim. Jika jaringan gagal,
perintah bisa sudah berlaku meski balasan tidak sampai: cek `/status` dan `/settings`.
Pesan order dicatat sebelum kirim, tidak diulang setelah timeout/restart, sehingga
notifikasi bisa hilang. Pesan lama tidak dikirim sebagai transaksi baru.

`/status` mengirim ringkasan akun virtual ke chat pemilik yang dikonfigurasi. Perlakukan
chat/perangkat Telegram sebagai akses kontrol akun demo. Token dan detail error jaringan
tidak dicetak ke chat/log. Riwayat pengaturan lokal bukan pengganti backup privat.
Tes lokal memakai Telegram tiruan; aktivasi/pengiriman pada chat pengguna belum diverifikasi.
