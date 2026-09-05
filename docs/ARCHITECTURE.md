# Arsitektur

v0.5 menambah `regime_reversion_v3`, validasi beberapa modal, dan setup Codespaces.
Fingerprint juga mengikat syarat riset. Demo Codespaces menggunakan replay historis,
tanpa broker exchange dan tanpa kredit runtime paper. Workflow GitHub hanya menjalankan
riset serta mengunggah artifact; lihat [panduan Codespaces](CODESPACES.md).

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
3. Runner membaca saldo USDT (`free` + `locked`) dan menambahkan mark-to-market posisi bot.
4. Risk manager mengecek persistent daily loss/drawdown, saldo tersedia, dan filter.
5. Broker mengirim market buy.
6. Broker segera mengirim OCO sell (take-profit + stop-loss-limit).
7. Hanya setelah OCO sukses posisi ditulis sebagai `PROTECTED`.
8. Jika langkah 6 gagal, emergency market sell dijalankan dan runtime melempar error.

## Modal dinamis

Backtest memakai `initial_cash` eksplisit agar eksperimen dapat direproduksi. Paper dan
live tidak memakai angka itu: keduanya membaca balance akun melalui endpoint account.
Sizing dihitung dari persentase equity, lalu di-clamp oleh saldo `free`, buffer harga,
optional notional cap, `maxQty`, dan `maxNotional`. Snapshot equity disimpan ke jurnal dan
menjadi sumber drawdown paper gate.

## Restart dan kill-switch

Posisi terkelola beserta order list ID disimpan di SQLite. Runner memuat ulang state itu,
sehingga tidak menganggap akun flat setelah restart. Supervisor mencatat heartbeat tiap 30
detik; session basi dapat dipulihkan, sedangkan dua runner aktif untuk mode sama ditolak.

Kill-switch berupa file sengaja sederhana dan dapat diaudit. Ia menghentikan runner, tetapi
tidak membatalkan OCO exchange-side.

## Runtime container

Versi 0.4 menambah `universe`, `selection`, `portfolio`, dan `research.walkforward`.
Portofolio memakai satu kas untuk semua pair dan ranking yang sama dengan runner.
Data riset production dan execution Testnet memakai database berbeda; jurnal akun tetap
dibagi oleh runner single/multi untuk mempertahankan lock satu posisi.

Laporan riset serta session paper diikat ke fingerprint konfigurasi. `candle_decisions`
mencegah duplikasi lintas restart dan `execution_intents` menahan operasi yang statusnya
belum diketahui. Durasi aktif berasal dari heartbeat terbatas dengan market data segar.

Compose menjalankan satu paper worker tanpa inbound port. Root filesystem read-only;
market cache, journal, posisi, dan kill-switch berada di named volume `/app/data`.
Healthcheck membaca heartbeat SQLite tanpa menganggap paper gate harus sudah lulus.
Restart policy menangani reboot/crash, sementara entrypoint memblokir subcommand `live`
untuk mencegah deployment demo berubah menjadi production secara tidak sengaja.
