# Ribuan bagian dataset, pengambilan bertahap

Satu candle adalah satu baris. Satu bagian dataset dalam antrean ini adalah
**satu pair × satu timeframe × satu bulan UTC**. Jadi 100 pair × 3 timeframe ×
12 bulan = 3.600 bagian, bukan 3.600 strategi atau contoh training independen.
Candle antar-timeframe berkorelasi; jumlah baris tidak membuktikan profitabilitas.

## Buat rencana dari Binance Spot

```bash
.venv/bin/python -m spotlab.research.batch plan --all-usdt --intervals 15m 1h 4h --start 2025-01-01 --end 2026-01-01
.venv/bin/python -m spotlab.research.batch status
```

Tanggal harus awal bulan UTC; end eksklusif. `plan` hanya mengambil katalog,
membuat antrean, menghitung calon baris dan perkiraan pemanggilan API, bukan mengunduh
seluruh histori. Rencana identik tidak menggandakan job. `--symbols BTCUSDT ETHUSDT`
bisa menggantikan `--all-usdt` untuk lingkup terpilih. Daftar ALL berasal dari pair
USDT Spot aktif sekarang, bukan seluruh listing masa lalu; survivorship bias tetap ada.

## Jalankan dalam anggaran tertentu

```bash
.venv/bin/python -m spotlab.research.batch run --jobs 5 --max-calls 30
.venv/bin/python -m spotlab.research.batch status
```

Satu runner, paling banyak lima job dan 30 pemanggilan metode API pada contoh ini.
Retry transport internal dapat membuat jumlah HTTP request sebenarnya lebih besar
(maksimal tiga percobaan per GET pada client sekarang). Anggaran bukan biaya uang.
Ulangi command untuk batch berikutnya; tidak perlu reset antrean. Budget habis
mengembalikan job ke pending dan cache parsial dipertahankan. Job crash yang masih
running diambil lagi pada run berikutnya setelah memperoleh lock OS. Dua runner
untuk antrean yang sama ditolak. Runner mendukung Linux/macOS; gunakan Codespaces
atau WSL untuk Windows. Proses tetap butuh mesin aktif, bukan layanan 24/7 otomatis.

Data ditempatkan di `data/research-batch/parts/<job-id>.db`; setiap shard memakai
importer resmi, pemeriksaan OHLCV, jumlah dan kontinuitas bar. Daftar job ada di
`queue.db`. Status complete hanya setelah audit, incomplete untuk histori kosong,
gap atau kegagalan yang memerlukan pemeriksaan. Ringkasan rows adalah jumlah baris
hasil audit job, bukan penghitung semua cache parsial. Tidak ada interpolasi/padding.
Jangan menghapus atau menyalin shard ke database akun demo.

```bash
# Hanya setelah penyebab kegagalan diperiksa:
.venv/bin/python -m spotlab.research.batch retry-incomplete
```

Jangan ulang terus jika token memang belum listing pada periode itu. Pilih periode
lain atau subset coin; tidak ada retry tak terbatas untuk missing history.

## Gabungkan untuk riset

```bash
.venv/bin/python -m spotlab.research.batch assemble --interval 1h --symbols BTCUSDT ETHUSDT --database data/research-large-1h.db
```

Seluruh bulan terencana untuk interval/coin pilihan harus complete. Tanpa `--symbols`,
semua coin interval tersebut wajib lengkap. Shard diaudit ulang dan gap antarbulan
ditolak. Output wajib database baru; database yang sudah ada tidak ditimpa. Hasilnya
bisa digunakan oleh `research` setelah `data.research_database`, interval dan daftar
universe pada salinan config riset diarahkan ke output tersebut. Filter order memakai
snapshot saat pengambilan, bukan aturan historis. Penggabungan bukan pelatihan model.

Batch terpisah bisa menggunakan `--root data/riset-lain` **sebelum** subcommand.
Pisahkan studi scalping 1m dari studi 1h; kebutuhan request/storage 1m jauh lebih besar.
Semua queue/database/raw data tetap diabaikan Git; update repo tidak mengisi data
Codespace secara otomatis. Jangan membagikan database akun demo atau `.env`.

## Bukti eksekusi sesi ini

Pada 25 September 2026, katalog menghasilkan **496 pair**, **17.856 job** untuk
15m/1h/4h sepanjang 2025, estimasi **22.811.040 candle** dan sedikitnya **47.616
pemanggilan API** sebelum retry. Itu rencana, bukan klaim download selesai.
Dataset resmi yang sebelumnya benar-benar lengkap tetap **70.080 candle** dari
8 pair pada 1h. Uji batch terbatas menemukan histori Januari 2025 kosong untuk
0GUSDT dan menandainya incomplete. Ini membuktikan missing history tidak disamarkan.
Tidak ada promosi strategi, order atau training ML otomatis dari antrean.
