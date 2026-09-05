# Multi-pair dan strategi adaptif — v0.4

Tambahan v0.5 tersedia pada [setup Codespaces](CODESPACES.md) dan
[laporan regime](../reports/evaluation-v0_5/README.md). Penjelasan v0.4 di bawah tetap
menjadi rujukan baseline; kandidat baru juga belum lolos riset.

Versi ini menambah scanner Binance Spot/USDT, ranking sinyal, strategi adaptif, dan
evaluasi portofolio. Dukungan pair tidak berarti semua coin layak ditradingkan. Universe
berisi pair yang tersedia di lingkungan exchange yang dipilih, masih TRADING, mengizinkan
Spot serta MARKET/OCO, dan memenuhi filter volume/spread. Quote selain USDT, futures,
leverage, dan order production untuk modul multi-pair belum diaktifkan.

## Menentukan coin

Template `config/multicoin.yaml` memuat BTC, ETH, BNB, SOL, XRP, ADA, AVAX, dan LINK.
Tiga pilihan universe:

| Pengaturan | Perilaku |
| --- | --- |
| `mode: single` | Pair dari `exchange.symbol` |
| `mode: explicit` | Daftar `universe.symbols` |
| `mode: all` | Temukan seluruh pair Spot/USDT yang lolos filter |

`max_symbols: 30` membatasi jumlah pair dengan volume terbesar yang dipindai. `null`
menghapus batas jumlah scanner; ini tidak menghapus batas posisi/risiko akun. Pemindaian
ratusan pair memerlukan lebih banyak RAM dan request daripada VM gratis. Daftar pada
Testnet bisa berbeda dari production. Universe disimpan saat fetch dan diperbarui ketika
fetch diulang; membership tidak diubah diam-diam ketika ada posisi terbuka.

```bash
spotlab --config config/multicoin.yaml universe --all
```

Laporan memuat alasan penolakan per pair, misalnya spread besar, volume kurang, atau OCO
tidak tersedia. Filter `min_history_days` juga diperiksa pada rentang bersama dataset riset.
Testnet hanya memerlukan candle yang cukup untuk warmup indikator; riwayat jangka panjang
untuk pembuktian strategi berasal dari data production.

## Logika strategi

Baseline EMA crossover tetap tersedia. `adaptive_trend_v2` membeli pemulihan pullback
atau bullish crossover ketika:

- EMA/SMA menunjukkan tren naik, EMA lambat meningkat, dan ADX melewati ambang;
- harga berada di atas EMA harian dari **hari UTC yang sudah selesai**;
- RSI, perubahan MACD histogram, relative volume, dan rentang ATR memenuhi syarat.

Sinyal diberi skor untuk mengurutkan peluang pada candle yang sama. Skor adalah aturan
ranking, **bukan probabilitas menang**. Ketika kondisi tidak memenuhi filter, strategi
menahan kas. Exit strategi, stop-loss, dan take-profit tetap tersedia.

`stop_mode: atr` menentukan jarak stop dari ATR candle sinyal, dengan batas minimum dan
maksimum persentase. Target mengikuti `reward_risk_ratio`. Risk budget tetap dihitung dari
equity akun, jarak stop sesudah pembulatan tick, dan cadangan biaya. Modal 20 USDT hanya
preset backtest; modal akun tidak dibatasi 20 USDT.

## Proses riset

Preset baru `config/regime.yaml` memakai `regime_reversion_v3`. Strategi membedakan
tren harian naik dan range yang tidak sedang turun tajam, kemudian mencari rebound
dengan RSI cepat, posisi close dalam candle, Bollinger Band, relative volume, dan ATR.
EMA hari sebelumnya juga memakai hari UTC yang selesai. Candle shock dan rebound
yang belum terkonfirmasi dilewati. Skor tetap merupakan ranking, bukan probabilitas.

`research.candidate_set: regime` membandingkan enam kandidat. `evaluation_capitals`
menentukan skala modal yang **seluruhnya** harus lolos training dan validasi; target
WR dari `target_win_rate_pct` tidak menggantikan syarat profit factor, expectancy,
jumlah trade, dan drawdown. Konfigurasi tersebut ikut fingerprint. Nilai 55% pada
preset merupakan target yang diuji, bukan hasil yang dijanjikan.

Fetch data publik tanpa credential production ke database riset yang terpisah:

```bash
spotlab --config config/multicoin.yaml fetch-universe --production --months 24
spotlab --config config/multicoin.yaml research --output reports/research
spotlab --config config/multicoin.yaml scan
```

`scan` menampilkan sinyal dan waktu candle **cache**. Streaming dan order virtual berlangsung
melalui command `paper` setelah gate lolos. Untuk menguji modal lain:

```bash
spotlab --config config/multicoin.yaml research --initial-cash 1000 --output reports/research-1000
```

Riset membandingkan tiga kandidat yang ditetapkan sebelum melihat hasil: baseline,
adaptive, dan adaptive selective. Sembilan bulan pertama dipakai untuk seleksi dengan
syarat jumlah trade, profit factor, expectancy, dan drawdown. Parameter kemudian dibekukan.
Ada embargo satu candle sebelum OOS. Sisa periode dibagi menjadi window tiga bulan penuh;
window terakhir yang belum lengkap disimpan sebagai tail yang belum dievaluasi.

OOS disimulasikan sebagai **satu akun berkelanjutan**: kas, posisi terbuka, peak equity, dan
batas drawdown tidak direset pada batas window. Satu posisi dibagi oleh seluruh pair;
modal tidak digandakan untuk setiap coin. Fee dan slippage dikenakan dua sisi. Entry
menggunakan open berikutnya, gap menembus stop memakai harga open yang lebih buruk,
dan stop diasumsikan tersentuh lebih dahulu bila stop/target ada dalam candle yang sama.

Hasil per kandidat mencakup trade log, equity, grafik SVG, metrik, interval Wilson 95%
untuk WR, window positif, dan stress biaya 1,5× serta 2×. Order juga dibatasi sebagian kecil
dari volume quote candle sebelumnya. Kolom `min_notional_skips` adalah penghitung penolakan
sizing, termasuk kegagalan memenuhi notional proteksi dan batas likuiditas.

Tidak ada kandidat yang dipaksakan menjadi pemenang. Jika seleksi training tidak lolos,
manifest menyatakan `NO_TRADE`; angka OOS kandidat lain tetap hanya hasil eksperimen.

## Bukti dan batas hasil yang disertakan

Lihat [`reports/evaluation-v0_4/README.md`](../reports/evaluation-v0_4/README.md). Delapan CSV
berasal dari snapshot pihak ketiga yang sama dengan sumber baseline terdahulu. SHA blob
Git dan SHA-256 CSV dicatat. CSV dan filter historis belum diverifikasi independen ke
Binance; parameter lot/tick pada eksperimen ini dinyatakan sebagai asumsi.

Tidak ada kandidat yang lolos seleksi training. Adaptive menghasilkan WR 56,52% dan
return +6,66% pada 20 USDT, tetapi WR 35,71% dan return sekitar −5,8% pada 1.000 serta
10.000 USDT. Pada modal kecil, 30 kesempatan entry gagal memenuhi sizing; pada modal
besar seluruhnya menjadi layak, lalu urutan posisi dan hasil berubah. Hasil ini belum
mendukung klaim strategi yang stabil. Tidak dilakukan tuning ulang untuk memenangkan
periode OOS yang sudah dilihat.

Fingerprint mengikat parameter sizing persentase, bukan saldo akun. Kelulusan pada satu
nominal tidak membuktikan kelayakan nominal lain: ulangi riset dan paper dengan skala
saldo yang akan digunakan, serta periksa laporan sensitivitas modal sebelum deployment.

Reproduksi snapshot tanpa API key:

```bash
python scripts/reproduce_multicoin.py --download-snapshot --capital-sensitivity
```

Opsi download mengambil delapan blob Git yang dipin dan memeriksa SHA-nya. CSV disimpan
di `data/snapshots/`, yang tidak ikut commit. Bila sudah memiliki CSV, gunakan
`--snapshot-dir PATH`. Unduhan tidak dilakukan jika file sudah ada; hash aktual tetap
dicatat di manifest hasil. Snapshot ini **tidak** meloloskan gate paper/live.

Universe statis mengandung survivorship bias. Backtest tidak merekonstruksi coin yang
delisting atau komposisi seluruh Binance pada setiap tanggal. Spread/depth historis,
market impact, dan fill order stop-limit juga tidak tersedia dalam OHLCV. Angka hasil
bukan janji WR di semua coin atau pada semua besar modal.

## Paper dan deployment

Setiap laporan ditautkan ke versi engine, parameter strategi/risiko/biaya, interval,
filter execution, dan daftar pair melalui fingerprint. Laporan BTC lama tidak dapat
meloloskan konfigurasi baru. Hari paper dan trade juga dihitung hanya untuk fingerprint
yang sama. Runtime lama tanpa identitas konfigurasi tidak dikreditkan ke eksperimen baru.

Setelah sebuah kandidat **lolos training dan semua gate OOS** pada data terverifikasi,
salin konfigurasi kandidat itu ke folder `config/`:

```bash
# Ganti <candidate> sesuai kandidat yang benar-benar dipilih dan berstatus RESEARCH_PASS.
cp reports/research/<candidate>/config.yaml config/validated.yaml
spotlab --config config/validated.yaml fetch-universe
spotlab --config config/validated.yaml research-readiness
spotlab --config config/validated.yaml paper
```

API key Testnet hanya di `.env`. Jika suatu pair tidak tersedia di Testnet, validasi ulang
universe yang benar-benar akan dijalankan. Jangan mengedit fingerprint atau status hasil
untuk memaksa gate. Versi ini tetap memblokir live untuk multi-pair/strategi adaptif sampai
paper minimal 14 hari dan peninjauan berikutnya selesai.

Untuk server, salin konfigurasi tervalidasi ke `config/paper-server.yaml`. Compose memuat
`config/` dan `reports/` secara read-only serta menyimpan database di named volume.
`server-start.sh` memeriksa research gate sebelum menyalakan daemon. Gunakan satu runner
dan satu database runtime untuk satu akun; dua database/VM tidak menyediakan lock akun
lintas server.

## Pemulihan gangguan

Order protection dipantau berkala, termasuk ketika tidak ada sinyal entry. WebSocket
digabung dalam kelompok dengan reconnect, antrian terbatas, serta penolakan sinyal basi
dan duplikat. Gap candle dipulihkan melalui REST sebelum memproses sinyal. Pencatatan
trade dan penghapusan posisi dilakukan dalam satu transaksi SQLite.

Intent disimpan sebelum order. Jika proses mati ketika hasil order belum pasti, bot
menolak restart otomatis. Periksa intent dan status order/posisi pada Testnet:

```bash
spotlab --config config/validated.yaml inspect-intent
# Hanya setelah status order, quantity, OCO dan jurnal benar-benar direkonsiliasi:
spotlab --config config/validated.yaml clear-intent --ack I_RECONCILED_TESTNET_ORDERS
spotlab --config config/validated.yaml clear-kill
```

OCO partial fill, cancellation tak terduga, atau market exit tidak penuh menghentikan
runner untuk rekonsiliasi. Jangan menganggap posisi pasti tertutup ketika request timeout.
Stop-limit dapat tidak terisi jika pasar melompati limit. Daily loss stop pada paper
memerlukan pemeriksaan operator; backtest melanjutkan entry pada hari UTC berikutnya,
sedangkan max drawdown stop tetap aktif sampai akhir evaluasi. Angka durasi paper berasal
dari heartbeat yang mendapat market data segar, bukan sekadar waktu proses menyala.

Referensi implementasi API: [Binance symbol filters](https://developers.binance.com/docs/binance-spot-api-docs/filters),
[combined WebSocket streams dan batas koneksi](https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md),
[Binance public data](https://github.com/binance/binance-public-data).
