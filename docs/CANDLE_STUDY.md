# Belajar candle semua pair — tanpa order

Jalankan setelah instalasi:

```bash
bash scripts/candle-study.sh
# Terminal lain:
.venv/bin/python -m spotlab --config config/candle-study.yaml demo-signals --limit 100
.venv/bin/python -m spotlab --config config/candle-study.yaml demo-health
.venv/bin/python -m spotlab --config config/candle-study.yaml demo-universe
```

Windows: `.venv\Scripts\python.exe -m spotlab --config config/candle-study.yaml demo-run`.
Mode `demo.analysis_only: true` mencatat data dan sinyal, tanpa entry/order virtual.
Database terpisah di `data/candle-study.db`. Saldo virtual tetap diperlukan oleh format
akun, tetapi tidak dibelanjakan. Mengubah mode pada akun lama ditolak: buat database
baru untuk percobaan trading agar data dan tujuan akun tidak tercampur.

## Coin mana yang dipelajari?

Semua pair Binance Spot/USDT dipindai saat startup, tanpa daftar coin populer/top 30.
Pair harus lolos filter volume, spread, status Spot aktif, dukungan order, dan base
pengecualian seperti stablecoin. Bukan semua aset di seluruh exchange, futures, atau
semua quote currency. `demo-universe` menjelaskan pair terpilih dan alasan penolakan.
Analisis menunggu 500 candle 1 menit yang sudah tutup dan kontigu untuk tiap pair.
Pair baru atau histori berlubang mungkin belum mempunyai hasil analisis.

## Apa yang dibaca dari candle?

- `candle_direction`: bullish, bearish, atau flat berdasarkan open/close candle.
- `body_ratio`: panjang badan dibagi rentang high-low.
- `upper_wick_ratio` / `lower_wick_ratio`: proporsi sumbu atas dan bawah.
- `curve_slope_atr`: kemiringan EMA lambat yang dinormalisasi ATR.
- `curve_efficiency`: seberapa terarah gerakan harga, dibanding total gerak bolak-balik.
- ADX, ATR%, volume relatif, dan posisi close dalam rentang candle.

Wick panjang atau candle hijau sendiri tidak memastikan harga berikutnya naik.
Strategi memeriksa lima syarat bersama:

| Entry check | Arti |
| --- | --- |
| trend | EMA cepat di atas EMA lambat, kemiringan positif, close di atas SMA |
| pullback | Ada sentuhan EMA cepat pada candle sebelumnya dalam jendela pengamatan |
| recovery | Harga pulih melewati high sebelumnya; RSI/MACD/posisi close mendukung |
| quality | Volume, ADX, ATR, kemiringan SMA dan batas lonjakan/jarak harga lolos |
| score | Skor kualitas mencapai ambang preset; bukan probabilitas menang |

Semua syarat harus true untuk menghasilkan sinyal entry. `demo-signals` membaca hasil
terakhir yang tersimpan per coin: `setup_detected` jika kondisi entry lolos, tidak ada
sinyal exit, dan candle masih segar; `wait` jika belum lolos; `stale` jika sudah basi.
Sinyal bukan order dan bukan persetujuan eksekusi. Proses dapat sudah berhenti meskipun
sinyal baru beberapa detik; periksa juga `demo-health`.

Contoh interpretasi: `trend=true`, `pullback=true`, `recovery=false` berarti tren dan
pullback terlihat tetapi konfirmasi pulih belum ada. Jangan menganggapnya sinyal beli
hanya karena candle hijau. Detail aturan ada pada [panduan kurva scalping](ALL_COIN_SCALPING.md).

## Menyimpan hasil dan batasan

```bash
.venv/bin/python -m spotlab --config config/candle-study.yaml demo-export --output exports/candle-study
```

CSV signal memuat diagnostics dan entry_checks; candle dan quote tersimpan terpisah.
Simpan backup secara privat, jangan push file akun. Ikuti [panduan privasi](CODESPACES_PRIVACY.md).
Data dikumpulkan untuk evaluasi berikutnya; belum ada pembelajaran parameter otomatis,
belum ada WR terverifikasi untuk preset 1m ini, dan mode ini tidak menghasilkan trade
untuk menghitung WR. Codespaces harus tetap berjalan agar data bertambah; status collector
pada instance pengguna belum diverifikasi.
