# Data dahulu, evaluasi kemudian

Data tersimpan bukan model yang sudah belajar. Import berikut mengambil candle
historis resmi melalui REST publik Binance tanpa API key. Tidak ada order atau
aktivasi strategi otomatis. Universe awal delapan pair adalah bootstrap, bukan
klaim telah mengumpulkan semua coin atau data scalping 1m.

```bash
.venv/bin/python -m spotlab.research.dataset --symbols BTCUSDT ETHUSDT BNBUSDT SOLUSDT XRPUSDT ADAUSDT AVAXUSDT LINKUSDT --start 2025-01-01 --end 2026-01-01 --interval 1h --workers 2
.venv/bin/python -m spotlab --config config/official-research.yaml research --output reports/official-research
```

Rentang bersifat UTC, start inklusif dan end eksklusif. Tambah/ganti `--symbols`
dengan ticker pair USDT lain dan gunakan database terpisah untuk eksperimen lain.
Listing baru mungkin tidak punya histori penuh; laporan harus menunjukkan tidak
lengkap, bukan mengisi candle palsu. Timeframe 1m membutuhkan jauh lebih banyak
request/storage; data 1h tidak membuktikan strategi scalping 1m.

Pengambilan menyimpan SQLite privat dalam `data/official-research.db`, filter order
saat pengambilan, dan laporan `reports/dataset/coverage.json`. Database, raw data dan
runtime report diabaikan Git. Clone/update repo tidak otomatis membawa database atau
menjalankan pengambilan; jalankan command di server/Codespace tempat bot akan bekerja.

Restart mengambil sisa rentang jika cache membentuk prefix lengkap. Jika ada gap,
rentang diminta ulang dan upsert mencegah duplikat. Setiap coin diperiksa jumlah bar,
batas awal/akhir, kontinuitas, OHLCV dan durasi candle; laporan mencatat SHA256 data
ternormalisasi. Kegagalan satu coin tidak membatalkan coin lain. Worker dibatasi 1-4;
exit code 2 berarti ada dataset belum lengkap. Jangan jalankan dua bootstrap pada
file database yang sama. Data dari sumber lama/tidak berprovenance ditolak agar tidak
dilabel ulang sebagai data resmi.

Config riset membandingkan baseline EMA dan dua varian adaptive yang sudah tersedia:
parameter dipilih dari enam bulan awal, dibekukan, lalu diuji pada window satu bulan
berikutnya dengan embargo satu candle. Statistik OOS dan stress biaya berasal dari
engine walk-forward yang sama. Jangan memilih ulang pemenang dari hasil OOS berulang;
perubahan berikutnya perlu periode holdout/forward baru.

Perhatikan keterbatasannya: universe dipilih sekarang (survivorship bias), lot/tick
berasal dari filter exchange sekarang (bukan snapshot historis), slippage tetap,
dan pajak tidak dimodelkan. Laporan mengukur hipotesis, bukan jaminan profit.
Tidak ada training ML otomatis atau promosi ke live. ML tetap terkunci sampai
baseline lolos research gate; paper Testnet dan gate lain tetap terpisah.

## Dataset yang benar-benar diambil pada sesi ini

Sebanyak **70.080 candle 1h** dari API publik resmi Binance: BTCUSDT, ETHUSDT,
BNBUSDT, SOLUSDT, XRPUSDT, ADAUSDT, AVAXUSDT dan LINKUSDT. Setiap pair berisi
8.760 bar dari 1 Januari 2025 sampai 31 Desember 2025 (UTC), tanpa gap pada audit.
Rincian jumlah, rentang, sumber dan hash ada di [laporan cakupan](research-2025-coverage.json).
Data ini diperoleh di workspace pengembangan, bukan bukti database Codespace kamu
sudah diperbarui. Gunakan paket dataset terpisah atau command reproduksi di atas.

[Hasil eksperimen pertama: semua gagal](RESEARCH_2025_RESULTS.md).
