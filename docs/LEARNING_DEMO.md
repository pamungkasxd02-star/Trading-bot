# Akun demo untuk belajar dan mengumpulkan data

Mode ini membuat **akun virtual internal bot**, bukan akun Binance atau Spot Testnet.
Tidak perlu login exchange, deposit, API key, atau secret. Default saldo 1.000 USDT
virtual dapat diubah saat membuat akun. Demo adalah eksperimen forward yang belum
tervalidasi; transaksi ini tidak dihitung untuk membuka research/paper/live gate.

## Mulai di Codespaces

```bash
.venv/bin/python -m spotlab --config config/demo.yaml demo-init
bash scripts/learning-demo.sh
```

Biarkan terminal tersebut berjalan. Di terminal lain:

```bash
.venv/bin/python -m spotlab --config config/demo.yaml demo-status
.venv/bin/python -m spotlab --config config/demo.yaml demo-export --output reports/learning
```

`demo-status` menampilkan saldo, posisi, jumlah candle per coin, jumlah quote/sinyal,
PnL, WR, dan usia quote terakhir. WR kosong sebelum ada trade tertutup; tidak ada
trade buatan untuk mempercantik angka. Akun dapat tetap HOLD ketika belum ada sinyal.

## Data dan mekanisme simulasi

- Sumber: endpoint resmi Binance [market data only](https://developers.binance.com/en/docs/products/spot/faqs/market_data_only).
  Client menolak permintaan selain GET publik yang diizinkan. Ia tidak membaca `.env`.
- Delapan pair Spot/USDT pada preset, difilter lagi menurut status, likuiditas dan spread.
  Untuk memperluas, ubah `universe.mode: all`; `max_symbols` membatasi beban, bukan saldo.
  Universe dipilih saat startup. Pair yang kemudian tidak tersedia tidak diberi harga buatan.
- OHLCV satu menit dari WebSocket; candle terbuka tidak disimpan sebagai candle selesai.
  REST mengisi warmup dan memperbaiki candle terlewat setiap lima menit serta saat restart.
  Cadangan REST tetap mengumpulkan candle bila WebSocket terputus.
- Quote bid/ask diambil tiap 15 detik, bersama sinyal closed-candle dan equity.
  BUY virtual memakai ask + slippage pada quote setelah sinyal; SELL memakai bid
  dikurangi slippage. Fee berlaku di kedua sisi. Spread, drift harga, lot size,
  min-notional dan kapasitas volume membatasi entry. Satu posisi untuk seluruh akun.
- Stop-loss dan target wajib. Proteksi virtual diperiksa pada quote yang diamati:
  bukan OCO exchange dan tidak menjamin harga stop. Gerakan intrabar di antara
  sampling bisa terlewat. Saat restart dengan posisi terbuka, posisi dilikuidasi
  pada quote pertama dengan label `resume_exit_unobserved_gap`; jangan menganggap
  stop tetap bekerja ketika proses offline.
- Batas rugi/kill-switch menghentikan entry dan menutup posisi pada quote berikutnya;
  collector tetap menyimpan data. Halt trading persisten agar restart tidak menghapus rugi.
- Akun, keputusan dan transaksi ditulis atomik. Lease mencegah dua proses memakai
  saldo yang sama. SQLite `data/learning.db` terpisah dari jurnal paper/live.
- `demo-export` menghasilkan CSV candle, quote, sinyal, order, trade, equity, event,
  summary JSON dan backup SQLite. Semua data runtime diabaikan Git; tidak diunggah publik.

Data tidak otomatis melatih ML atau membuat WR naik. Dataset perlu diaudit, dipisah
secara kronologis, dilatih pada bagian training, lalu diuji pada data yang belum dilihat.
Preset satu menit adalah alat belajar; hasil backtest empat jam tidak berlaku otomatis.

## Saldo lain, berhenti, dan daya tahan data

```bash
# Hanya ketika akun pada database ini belum dibuat:
.venv/bin/python -m spotlab --config config/demo.yaml demo-init --initial-cash 10000
# Stop trading virtual, tetapi terus kumpulkan data:
.venv/bin/python -m spotlab --config config/demo.yaml demo-stop-trading
```

Ctrl+C menghentikan collector dan menyimpan akun. Menjalankan kembali tidak mengisi
ulang saldo. Untuk strategi/saldo eksperimen lain, salin config dan gunakan path
`demo.database` serta kill-switch berbeda; akun lama tetap dapat diekspor. Perubahan
strategi, risiko atau biaya ditolak pada akun lama untuk menjaga keterbandingan hasil.

Codespaces dapat berhenti karena idle/kuota; tidak dianggap server gratis 24/7.
SQLite bertahan selama Codespace yang sama belum dihapus. Unduh backup secara berkala:
hapus Codespace berarti kehilangan data lokalnya. Collector ini belum berjalan
di server persisten dan tidak menghindari timeout dengan keep-alive.
