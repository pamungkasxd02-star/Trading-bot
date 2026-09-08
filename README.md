# Binance Spot Lab

Bot riset dan **akun demo real-time** untuk Binance Spot. Modal virtual bebas ditentukan,
strategi modular, data tersimpan di SQLite, dan tersedia mode scalping satu menit.
Fokus proyek: menguji strategi secara jujur sebelum mempertimbangkan uang sungguhan.

**Status:** demo internal tersedia; collector di Codespaces **belum terverifikasi aktif**.
Strategi belum membuktikan hasil stabil, paper Testnet 14 hari belum selesai, dan live
masih dikunci. Kode yang berhasil dites bukan bukti profit atau bukti bot berjalan 24/7.

## Mulai dari demo tanpa API key

Di [GitHub Codespaces](docs/CODESPACES.md), tunggu setup selesai lalu jalankan:

```bash
bash scripts/scalping-demo.sh
```

Untuk komputer sendiri, clone dan instal terlebih dahulu:

```bash
git clone https://github.com/pamungkasxd02-star/Trading-bot.git
cd Trading-bot
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m spotlab --config config/scalping-demo.yaml demo-run
```

Memerlukan Python 3.11+. Di Windows PowerShell, setelah clone dan masuk folder:

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe -m spotlab --config config/scalping-demo.yaml demo-run
```

Tidak perlu mengaktifkan virtual environment atau membuat `.env` untuk demo internal.
Bot menunggu sinyal pada candle tertutup; tidak harus membuka trade setiap menit.
Saldo, posisi, dan data akun sebelumnya dipulihkan ketika dijalankan kembali.

Untuk **semua pair Spot/USDT yang layak**, tersedia `bash scripts/all-scalping-demo.sh`.
Preset terpisah ini memakai filter kurva/tren/pullback, tanpa batas top 30.
Lihat [panduan semua coin dan scalping](docs/ALL_COIN_SCALPING.md), termasuk
alasan penolakan coin, beban data, dan biaya/pajak yang belum masuk PnL demo.

## Pilih mode yang tepat

| Mode | Harga dan order | Status / penggunaan |
| --- | --- | --- |
| Demo belajar | Harga Binance publik real-time; order virtual internal | Belajar dan mengumpulkan data, tanpa key |
| Scalping demo | Candle 1m, quote dipoll tiap 5 detik; order virtual | Eksperimen cepat, belum terbukti profitable |
| Replay / backtest | Data historis; fill simulasi dengan biaya | Evaluasi dan pembanding strategi |
| Paper Testnet | Order pada Binance Spot Testnet, saldo virtual exchange | Memerlukan research gate yang cocok |
| Live | Order sungguhan Binance Spot | Terkunci sampai seluruh gate terpenuhi |

Demo internal **tidak dihitung** sebagai bukti paper Testnet, tidak otomatis melatih ML,
dan tidak membuka izin live. Seluruh mode Spot long-only, tanpa leverage/futures.

## Kontrol dan data demo

Jalankan perintah berikut di terminal kedua dari folder repository:

```bash
# Saldo, posisi, WR aktual, PnL, dan jumlah data:
.venv/bin/python -m spotlab --config config/scalping-demo.yaml demo-status
# Kesehatan proses dan kesegaran data tiap coin; exit 2 bila stale/offline:
.venv/bin/python -m spotlab --config config/scalping-demo.yaml demo-health
# Hentikan trading virtual, lanjutkan pengumpulan data:
.venv/bin/python -m spotlab --config config/scalping-demo.yaml demo-stop-trading
# CSV dan backup SQLite:
.venv/bin/python -m spotlab --config config/scalping-demo.yaml demo-export --output reports/scalping-learning
```

Windows: ganti `.venv/bin/python` dengan `.venv\Scripts\python.exe`.
Ctrl+C menghentikan proses. Kill-switch dievaluasi pada quote valid berikutnya;
ketika koneksi putus, exit virtual tidak bisa langsung terjadi.

| Preset | Demo belajar | Scalping demo |
| --- | --- | --- |
| Config | `config/demo.yaml` | `config/scalping-demo.yaml` |
| Saldo awal default | 1.000 USDT virtual | 1.000 USDT virtual |
| Candle / polling quote | 1m / 15 detik | 1m / 5 detik |
| Stop-loss / take-profit | 3% / 6% | 0,6% / 1,2% |
| Batas waktu posisi | Tidak ditetapkan | 15 menit |
| Risiko / alokasi maksimum | 1% / 50% equity | 0,25% / 25% equity |
| Database | `data/learning.db` | `data/learning-scalping.db` |

Preset demo delapan pair tersebut maksimal satu posisi, daily loss limit 3%, drawdown limit 10%, fee 10 bps dan
slippage 5 bps per sisi. SL/TP virtual hanya bekerja saat proses hidup dan menerima
harga; saat restart setelah gap, posisi ditutup pada harga baru yang teramati, bukan
pada harga stop yang diasumsikan. Gap dapat membuat kerugian melewati batas konfigurasi.

Untuk modal lain, ubah `demo.initial_cash` **sebelum akun dibuat**. Untuk eksperimen baru,
gunakan nama/path database dan kill-switch baru. Bot menolak perubahan strategi/risiko
pada akun lama agar hasil tidak tercampur. Tidak ada hard cap modal 20 USDT.

Preset memindai delapan pair. `universe.mode: all` tersedia untuk pair Spot/USDT yang
lolos filter volume, spread, dan batas jumlah simbol; bukan seluruh coin tanpa seleksi.
Mulai dengan jumlah kecil agar kebutuhan jaringan dan penyimpanan dapat dipantau.
Detail: [akun demo dan scalping](docs/LEARNING_DEMO.md).

## Strategi dan target win rate

| Strategi | Pendekatan |
| --- | --- |
| `rule_based_v1` | EMA crossover, SMA, RSI, MACD, Bollinger, volume |
| `adaptive_trend_v2` | Tren/pullback, ADX, ATR, tren harian yang sudah selesai |
| `regime_reversion_v3` | Rebound terkonfirmasi pada tren atau range |
| `quality_cross_v1` | Filter crossover: ADX, ATR, volume, kemiringan SMA, batas lonjakan |
| `curve_scalping_v1` | Kurva tren, pullback, pemulihan candle, efisiensi gerakan; eksperimen 1m |

`quality_cross_v1` adalah hipotesis baru, bukan preset yang otomatis menggantikan demo.
Dua varian kualitas diuji bersama baseline dengan biaya dan aturan risiko yang sama.
Tidak ada skor sinyal yang boleh dibaca sebagai probabilitas menang.

WR harus dilihat bersama **profit factor, expectancy setelah biaya, drawdown, jumlah
trade, dan interval ketidakpastian WR**. WR tinggi dari sedikit trade atau target profit
sangat kecil belum membuktikan keunggulan. Seleksi dilakukan pada training; evaluasi
kronologis, beberapa modal, serta stress biaya tetap wajib.

Laporan yang dapat diperiksa:

- [Eksperimen filter kualitas terbaru](reports/evaluation-quality/README.md): hasil batch,
  log trade, equity, sensitivitas modal dan biaya; termasuk kegagalan.
- [Evaluasi v0.5](reports/evaluation-v0_5/README.md): seluruh kandidat gagal; pada modal
  1.000 USDT, hybrid WR 38,33%, PF 0,708, return −9,20%.
- [Evaluasi v0.4](reports/evaluation-v0_4/README.md) dan [baseline awal](reports/baseline/README.md)
  dipertahankan sebagai riwayat. Angka dari protokol berbeda tidak langsung sebanding.

Snapshot riset lama berasal dari pihak ketiga; hash diperiksa, data/filter belum
terverifikasi langsung ke Binance. Periode tersebut sudah dilihat sebelumnya. Eksperimen
ulang tetap **eksploratif**, bukan fresh holdout atau alasan membuka live.

## Reproduksi backtest dan riset

Setelah instalasi, gunakan `.venv/bin/python` (atau padanan Windows):

```bash
# Data publik historis dan backtest baseline dari cache:
.venv/bin/python -m spotlab fetch --months 24
.venv/bin/python -m spotlab backtest --months 24 --initial-cash 1000 --output reports/my-run
# Reproduksi batch kualitas pada snapshot yang identitasnya diperiksa:
.venv/bin/python scripts/research_regime.py --config config/quality-research.yaml --download-snapshot --output reports/my-quality-run
```

Backtest memakai sinyal candle tertutup, fill candle berikutnya, fee/slippage, pembulatan
lot dan minimum notional. Jika SL dan TP tersentuh pada candle sama, SL didahulukan.
Riset multi-coin menggunakan satu saldo bersama. Output mencakup CSV metrik/trade/equity,
kurva equity, konfigurasi, protokol, serta alasan gate lulus/gagal.
**Hasil candle 4h tidak memvalidasi scalping 1m.** Data demo 1m yang terkumpul harus diuji
terpisah; jangan membuat metrik scalping dari replay 4h.

## Testnet dan live

Alur validasi: data → backtest/riset → Testnet minimal 14 hari aktif → evaluasi live.
Untuk kandidat yang lolos riset terverifikasi, ikuti
[panduan riset multi-coin](docs/MULTICOIN_RESEARCH.md) dan [metodologi](docs/METHODOLOGY.md).
`research-readiness` dan `readiness` pada config terkait adalah sumber status gate.

Key hanya di `.env` lokal, gunakan `.env.example` sebagai template. Key Testnet terpisah
dari production; key production harus trade-only tanpa withdrawal. Jangan menaruh key
pada kode, commit, screenshot, atau issue. Demo internal tidak membaca key tersebut.

Adapter exchange memakai SL/TP OCO dan rekonsiliasi order; demo internal memakai stop
virtual. Live memerlukan research gate, bukti Testnet, metrik minimum dan acknowledgement.
Dukungan live multi-pair masih dikunci untuk peninjauan. Tidak ada perintah bypass gate.

## Menjalankan dan menyimpan data

Codespaces cocok untuk mencoba di browser; **bukan jaminan server gratis 24/7**.
Proses berhenti bila Codespace berhenti. Data bertahan pada instance yang sama sampai
instance dihapus; ekspor dan unduh backup secara berkala. Data lokal tidak ikut push Git.

Untuk server persisten tersedia [panduan deployment](docs/DEPLOY_FREE_24_7.md).
Periksa mode/config script deployment: script paper Testnet tidak otomatis menjalankan
akun demo internal. Belum ada klaim collector real-time aktif di server persisten.

## Pengembangan

```bash
.venv/bin/python -m pytest -W error::DeprecationWarning
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
```

Core berada di `src/spotlab/`: data/exchange, strategies, backtest/portfolio,
research, learning, risk, execution/journal, reporting, dan CLI. Strategi yang sama
menghasilkan sinyal untuk simulator maupun executor; broker menangani order secara terpisah.
Lihat [arsitektur](docs/ARCHITECTURE.md) dan [keamanan](SECURITY.md).

Ini perangkat lunak eksperimen, bukan janji profit. Validasi historis maupun demo tidak
menghilangkan risiko kerugian ketika kelak memakai uang sungguhan.
