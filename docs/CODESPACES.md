# GitHub Codespaces: buka, install otomatis, jalankan demo

Repository memakai `.devcontainer/devcontainer.json`. Saat Codespace baru dibuat,
`scripts/codespaces-setup.sh` menyiapkan virtual environment, memasang dependency,
menyalin template `.env` jika belum ada, lalu menjalankan replay historis enam bulan.
Tidak ada API key yang diperlukan untuk demo ini.

## Mulai

1. Buka repository di GitHub, pilih **Code → Codespaces → Create codespace on main**.
2. Pilih mesin terkecil yang tersedia (2 core) dan periksa kuota akun terlebih dahulu.
3. Tunggu tahap `postCreateCommand` selesai. Hasil demo ada di `reports/codespaces-demo/`:
   summary, trade CSV, equity CSV, dan grafik PNG.

Ulangi demo di terminal Codespaces:

```bash
bash scripts/codespaces-demo.sh
# Saldo simulasi lain:
bash scripts/codespaces-demo.sh --initial-cash 10000
```

Task **Trading bot: historical demo** tersedia melalui menu **Terminal → Run Task**.
Untuk menjalankan seluruh eksperimen kandidat dengan tiga modal dan stress biaya:

```bash
.venv/bin/python scripts/research_regime.py --download-snapshot --output reports/regime
```

Jika download terputus, jalankan ulang command demo. Blob yang sudah tersimpan tidak
diunduh ulang, lalu SHA-256 seluruh CSV diperiksa sebelum dipakai. Tidak ada upaya
mempertahankan proses dengan keep-alive buatan.

## Arti demo

Demo menjalankan strategi dan simulasi fill pada OHLCV historis. Fee, slippage, stop-loss,
take-profit, minimum order, saldo bersama, dan batas drawdown tetap digunakan. Demo ini
**bukan streaming harga hari ini, bukan transaksi Binance Testnet, dan bukan bukti WR
masa depan**. Ia tidak menulis heartbeat/hari paper atau membuka research/live gate.

Sumbernya adalah delapan CSV pihak ketiga yang dipin di laporan v0.4. Data dan asumsi
filter tidak berubah diam-diam menjadi "terverifikasi" saat dijalankan di GitHub.

Untuk Testnet realtime, gunakan konfigurasi yang benar-benar lulus riset pada data
terverifikasi, isi credential Testnet di `.env` Codespace, lalu ikuti
[alur paper](MULTICOIN_RESEARCH.md#paper-dan-deployment). Sampai validasi lolos,
command `paper` tetap menolak entry. Live untuk strategi baru juga tetap dikunci.

## Kuota dan 24/7

Codespaces merupakan lingkungan development dengan kuota compute/storage, dan timeout
idle default 30 menit. Kuota GitHub Free personal tercantum 120 core-hours per bulan;
mesin 2 core menghabiskan dua core-hours per jam. Jadi jangan menganggap Codespaces
sebagai server gratis tanpa batas. Stop Codespace saat selesai dan periksa halaman
billing akun. Proses terminal dapat memengaruhi idle timeout; jangan mengandalkannya
untuk membatasi tagihan.

Untuk paper 24/7 setelah validasi, gunakan [panduan VM](DEPLOY_FREE_24_7.md) dengan
penyimpanan persisten. Repository menyediakan setup, tetapi tidak membuat VM, rekening
exchange, atau saldo Testnet secara otomatis.

## Riset di GitHub Actions

Workflow **Research replay** menjalankan eksperimen tanpa credential exchange dan
mengunggah laporannya sebagai artifact. Ia berjalan ketika kode riset berubah, atau
melalui **Actions → Research replay → Run workflow**. Workflow **CI** juga menjalankan
script setup Codespaces dan demo di runner bersih.

Keberhasilan workflow berarti program selesai dan artifact tersedia; status strategi
tetap dibaca dari `manifest.json` (`RESEARCH_PASS` atau `RESEARCH_FAIL`). GitHub Actions
tidak menyalakan Codespace dan tidak menjalankan paper bot 24/7.

Referensi: [billing Codespaces](https://docs.github.com/billing/managing-billing-for-github-codespaces/about-billing-for-github-codespaces),
[timeout idle](https://docs.github.com/en/codespaces/setting-your-user-preferences/setting-your-timeout-period-for-github-codespaces),
[spesifikasi dev container](https://containers.dev/implementors/json_reference/).
