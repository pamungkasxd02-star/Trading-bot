# Arsitektur

## Batas modul

| Modul | Tanggung jawab | Tidak boleh |
| --- | --- | --- |
| `data.py` | Cache candle/filter exchange di SQLite | Menentukan sinyal |
| `strategies/` | Indikator dan sinyal deterministik | Mengakses credential/order |
| `backtest.py` | Fill event-driven, biaya, SL/TP, metrik | Memanggil exchange |
| `risk.py` | Sizing dan batas kerugian | Membulatkan quantity ke atas |
| `execution/realtime.py` | State machine bersama | Menghilangkan live gate |
| `execution/paper.py` | Binance Spot Testnet | Endpoint production |
| `execution/live.py` | Binance Spot production | Key berizin withdrawal |
| `journal.py` | Session/signal/order/trade/risk/position | Menyimpan API secret |
| `gates.py` | Research, paper, acknowledgement | Menilai profit masa depan |

## Urutan entry

1. WebSocket mengirim candle berstatus tutup.
2. Strategy menghasilkan sinyal dari paling banyak candle itu.
3. Risk manager mengecek persistent daily loss/drawdown, modal terkelola, dan filter.
4. Broker mengirim market buy.
5. Broker segera mengirim OCO sell (take-profit + stop-loss-limit).
6. Hanya setelah OCO sukses posisi ditulis sebagai `PROTECTED`.
7. Jika langkah 5 gagal, emergency market sell dijalankan dan runtime melempar error.

## Restart dan kill-switch

Posisi terkelola beserta order list ID disimpan di SQLite. Runner memuat ulang state itu,
sehingga tidak menganggap akun flat setelah restart. Supervisor mencatat heartbeat tiap 30
detik; session basi dapat dipulihkan, sedangkan dua runner aktif untuk mode sama ditolak.

Kill-switch berupa file sengaja sederhana dan dapat diaudit. Ia menghentikan runner, tetapi
tidak membatalkan OCO exchange-side.
