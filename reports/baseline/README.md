# Baseline report — BTCUSDT Spot 4h

Status: **RESEARCH_PASS, PAPER PENDING, LIVE BLOCKED**.

## Sampel

- 4.381 candle, 10 Juli 2024 08:00 UTC sampai 10 Juli 2026 08:00 UTC.
- Source: snapshot `data/markets/BTCUSDT_4h.csv` dari repository publik
  `Ilnyr2006-droid/python-paper-trading-agent-1-data`, Git blob
  `f5c4edf585bcbe76a1e8c17ab06659cd961a587d`.
- File tersebut dibuat oleh downloader repository yang memanggil Binance Spot
  `/api/v3/klines`; SHA-256 byte CSV yang dipakai:
  `b0ed49ee1dc5d83c847b951e73d3f44852f624b587afb23f8a6d0ea0af1fe98a`.
- Dataset mentah tidak dikomit. Alur normal `spotlab fetch` mengambil ulang data resmi dan
  menyimpan cache SQLite lokal.

## Konfigurasi terpilih

- EMA 20/56, SMA trend 100.
- RSI 14 rentang 44–70, MACD 12/26/9, Bollinger 20×2, volume SMA 20.
- Fresh bullish cross + trend dan minimal 3 dari 4 konfirmasi.
- Stop-loss 2,5%, take-profit 5%, maksimal satu posisi.
- Fee 10 bps/sisi, slippage 5 bps/sisi.
- Modal awal 20 USDT, risk budget 1% dan alokasi maksimum 50% per trade.

## Hasil utama

| Metrik | Nilai |
| --- | ---: |
| Final equity | 22,020734 USDT |
| Net return | +10,1037% |
| Trade | 27 |
| Win rate | 48,1481% |
| Profit factor | 1,7081 |
| Max drawdown | 6,0524% |
| Average win | +0,374956 USDT |
| Average loss | −0,203835 USDT |
| Expectancy/trade | +0,074842 USDT |
| Total fee | 0,446042 USDT |
| Min-notional skip | 0 |

Rolling tiga bulanan: **6/8 positif (75%)**. Window terburuk adalah −4,237%. Ini hanya
ambang minimum research gate, bukan bukti stabilitas masa depan.

## Selection-bias warning

Kandidat dipilih setelah bounded sweep 432 kombinasi di sampel yang sama; 80 kandidat
full-sample terbaik kemudian dibandingkan per window. Karena itu angka ini in-sample dan
optimistis. Parameter tidak boleh diubah lagi selama forward paper test. Testnet minimal 14
hari runtime aktif dan 20 trade tertutup tetap wajib sebelum live dipertimbangkan.

## Berkas

- `summary.json` / `summary.csv`: metrik full-sample.
- `trades.csv`: trade-level ledger.
- `equity.csv` dan `equity_curve.png`: mark-to-market curve.
- `validation_summary.json` / `validation_windows.csv`: rolling validation.
- `cost_sensitivity.csv`: tekanan biaya tambahan.
