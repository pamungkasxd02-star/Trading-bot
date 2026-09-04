# Metodologi baseline

## Sampel dan provenance

Alur normal mengambil candle langsung dari `/api/v3/klines` dan filter dari
`/api/v3/exchangeInfo`. Report yang dikomit menyebutkan rentang, jumlah candle, parameter,
biaya, dan provenance snapshot-nya agar hasil tidak dibaca tanpa konteks.

## Pencegahan look-ahead

- Indikator memakai operasi rolling/EMA satu arah.
- Sinyal baru berlaku sesudah candle tutup.
- Backtest mengisi order pada open candle berikutnya.
- ML opsional membentuk label dengan shift masa depan, tetapi fitur tidak memakai nilai
  masa depan dan cross-validation memakai gap sebesar horizon.

## Biaya dan fill

Baseline mengenakan fee 0,10% dan slippage 0,05% pada entry serta exit. Intrabar hanya
memiliki OHLCV sehingga urutan high/low tidak diketahui; saat SL dan TP sama-sama tersentuh,
simulasi memilih SL. Stop-limit live memiliki limit sedikit di bawah trigger dan karena itu
tetap memiliki risiko tidak terisi saat gap tajam.

## Risiko statistik

Rolling window bukan out-of-sample murni bila parameter dipilih setelah melihat keseluruhan
periode. Angka baseline mengandung selection bias dan tidak boleh dianggap estimasi return
masa depan. Tahap berikutnya wajib forward paper test yang tidak ikut dipakai memilih
parameter.

## Gate

Research gate dan paper gate adalah pemeriksaan minimum, bukan sertifikat aman. Live juga
memerlukan acknowledgement string, config production terpisah, API key trade-only tanpa
withdrawal, dan tidak adanya kill-switch.

Paper gate menghitung drawdown dari snapshot equity akun, bukan dari asumsi modal 20 USDT.
Karena deposit, withdrawal, dan order manual dapat mengubah equity tanpa berasal dari
strategi, forward test sebaiknya memakai akun atau sub-account khusus bot.
