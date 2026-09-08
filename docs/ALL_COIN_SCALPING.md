# Scalping semua pair yang layak

Preset `config/all-scalping-demo.yaml` membuat akun virtual baru pada
`data/learning-all-scalping.db`. Tidak mengubah akun demo lain, tidak mengirim order
ke Binance, dan belum mempunyai hasil backtest/forward yang membuktikan profitabilitas.

```bash
bash scripts/all-scalping-demo.sh
# Terminal lain:
.venv/bin/python -m spotlab --config config/all-scalping-demo.yaml demo-universe
.venv/bin/python -m spotlab --config config/all-scalping-demo.yaml demo-health
.venv/bin/python -m spotlab --config config/all-scalping-demo.yaml demo-status
.venv/bin/python -m spotlab --config config/all-scalping-demo.yaml demo-export --output reports/all-scalping-learning
```

Windows: jalankan `.venv\Scripts\python.exe -m spotlab --config config/all-scalping-demo.yaml demo-run`.

## Cakupan coin

`universe.mode: all`, `max_symbols: null`: tidak menggunakan daftar coin populer atau
batas top 30. Semua metadata pair Spot/USDT dipindai saat proses mulai, termasuk coin
lain yang memenuhi persyaratan. Filter tetap menolak pair nonaktif, non-Spot,
order market/OCO tidak tersedia, base yang dikecualikan, volume quote 24h di bawah
5 juta USDT, atau spread di atas 10 bps. Coin yang ditolak beserta alasannya dapat
diperiksa melalui `demo-universe`; snapshot juga disimpan dalam SQLite.

Daftar ini diperbarui saat proses dimulai, belum hot-refresh saat berjalan. Perubahan
listing/status bisa menuntut restart. Filter historis umur listing belum diberlakukan
pada demo ini; entry memerlukan 500 candle 1m kontigu. Jangan memakai daftar coin saat
ini untuk mengklaim backtest bebas survivorship bias pada masa lalu.

Lebih banyak pair berarti bootstrap, CPU, koneksi dan pertumbuhan data lebih besar.
Polling quote ditargetkan tiap 5 detik, bukan jaminan latensi eksekusi 5 detik. Bootstrap
menyiapkan data seluruh pair sebelum loop trading dimulai. WebSocket dibagi beberapa
koneksi; saat data stale, health menjadi degraded. Tidak menjadikan Codespaces server
24/7. Maksimal satu posisi virtual tetap berlaku untuk seluruh akun.

## Cara membaca kurva untuk entry

Strategi `curve_scalping_v1` memakai candle tertutup, dengan urutan:

1. EMA 9 di atas EMA 21, kemiringan EMA 21 positif, harga di atas SMA 50 yang naik.
2. Ada sentuhan/pullback ke EMA cepat dalam lima candle terdahulu.
3. Close sekarang melewati high candle sebelumnya dan kembali di atas EMA cepat.
4. Close berada pada bagian atas candle, RSI 45–68, histogram MACD membaik.
5. ADX minimal 20, ATR 0,15–1,5%, volume minimal rata-rata sebelumnya, dan batas
   candle lonjakan/jarak harga dari EMA membatasi entry yang mengejar harga.
6. Skor minimal 60 dari efisiensi gerakan, ADX dan posisi close dalam candle.

Efisiensi kurva = besar perpindahan harga lima candle / total gerakan absolut selama
lima candle. Gerakan bolak-balik cenderung mempunyai efisiensi lebih rendah. Kemiringan
EMA dinormalisasi dengan ATR agar besaran harga coin berbeda dapat dibandingkan.
Keduanya mendeskripsikan masa lalu, bukan prediksi kurva masa depan. Skor bukan persen WR.
Parameter skor menggunakan `strategy.min_reversion_score` yang sudah ada pada schema.

Log sinyal menyimpan `diagnostics`: curve_efficiency, curve_slope_atr, close_location,
ADX, ATR%, volume relatif. CSV equity berasal dari akun virtual, sedangkan kurva harga
berasal dari candle; keduanya tidak boleh dianggap hal yang sama. Tes sintetis memastikan
hasil prefix tidak berubah oleh candle masa depan; tes ini tidak mengukur profitabilitas.

SL 0,6%, TP 1,2%, maksimal hold 15 menit, risk budget 0,25%, alokasi maksimal 25%,
daily loss 3% dan drawdown 10%. Exit juga pada rusaknya tren atau risk halt. SL/TP
virtual hanya bekerja ketika proses menerima quote; gap bisa melewati batas stop.

## Biaya dan pajak sebelum mengejar frekuensi

Preset menghitung fee 10 bps dan slippage 5 bps per sisi, serta spread harga bid/ask.
**PnL simulasi belum memasukkan pajak.** Jangan membaca net_pnl sebagai laba setelah
pajak atau memilih strategi hanya dari WR. Dengan biaya ini, sekitar 0,3% pulang-pergi
sudah terpakai sebelum spread dan pajak. Target pendek perlu dievaluasi kembali jika
beban pajak berlaku.

Untuk subjek pajak Indonesia, [PMK 50/2025](https://www.pajak.go.id/en/node/117213),
Pasal 12 dan 20–22, mengatur PPh final 0,21% melalui PAKD dalam negeri dan 1% melalui
penyelenggara luar negeri, dari nilai transaksi terkait. Kewajiban setor sendiri dapat
berlaku jika tidak dipungut. Tukar-menukar aset juga perlu diperhatikan; jangan sekadar
menambahkan pajak pada penarikan fiat. Penentuan kewajiban pribadi memerlukan pemeriksaan
status pajak, platform dan jenis transaksi. Dokumentasi diperiksa 8 September 2026.
Bot tidak menghitung SPT dan tidak menawarkan cara menyembunyikan transaksi.

Bukti berikutnya: kumpulkan data 1m forward, audit gap/biaya, evaluasi strategi pada
periode terpisah, lalu bandingkan expectancy, PF, WR beserta intervalnya dan drawdown.
Laporan riset 4h sebelumnya tidak memvalidasi preset ini.
