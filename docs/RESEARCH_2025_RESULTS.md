# Hasil pengujian data resmi 2025

Dataset: 70.080 candle 1h, delapan pair USDT, Januari-Desember 2025.
Modal simulasi 1.000 USDT; fee 10 bps dan slippage 5 bps per sisi.
Seleksi dilakukan pada Januari-Juni, embargo satu bar, evaluasi lima window bulanan
mulai 1 Juli 2025 01:00 UTC sampai 1 Desember 2025 01:00 UTC. Sisa Desember tidak
termasuk periode penilaian ini. Tidak ada kandidat yang lolos seleksi training.
Angka OOS berikut hanya diagnostik, bukan strategi yang akan diaktifkan.

| Kandidat | Trade | WR | PF | Return net | Max DD | Expectancy USDT/trade |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | 60 | 26.67% | 0.85 | -4.62% | 10.22% | -0.7695 |
| adaptive | 37 | 29.73% | 0.62 | -7.29% | 10.15% | -1.9708 |
| adaptive_selective | 17 | 29.41% | 0.64 | -3.43% | 6.40% | -2.0185 |

**Semua RESEARCH_FAIL; kebijakan riset NO_TRADE.** Ini tidak menonaktifkan proses
akun demo pengguna dari jarak jauh. Tidak ada model ML dilatih atau perubahan
strategi otomatis. Ketiganya memiliki expectancy negatif dan gagal stress biaya.
Adaptive selective juga memiliki trade OOS terlalu sedikit. Lebih banyak data
belum menunjukkan strategi yang profitable. Jangan menaikkan risiko untuk mengejar
hasil; perubahan berikutnya perlu hipotesis tertulis dan holdout baru.

[Detail hasil](research-2025-results.json), [cakupan dataset](research-2025-coverage.json)
dan [reproduksi](DATA_RESEARCH.md). Batasan: universe saat ini, filter order saat ini,
fill OHLCV perkiraan dan belum termasuk pajak. Bukan bukti untuk scalping 1m.
