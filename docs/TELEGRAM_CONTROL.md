# Kontrol demo dari Telegram

Fitur ini mengendalikan akun **demo internal** yang sedang berjalan. Tidak mempunyai
perintah order Binance asli, tidak mengubah API key, dan tidak membuka gate live.

## Aktifkan

Simpan token dan chat ID privat numerik pada `.env`/Codespaces Secrets, seperti
[panduan gambar candle](TELEGRAM_CANDLES.md). Pada config akun yang dijalankan:

```yaml
candle_alerts:
  enabled: true
  commands_enabled: true
  setups_only: true
  symbols: []
  bars: 60
  min_interval_seconds: 60
  symbol_cooldown_seconds: 900
```

Gunakan `config/all-scalping-demo.yaml` dan `bash scripts/all-scalping-demo.sh` untuk
simulasi auto-buy. `config/candle-study.yaml` tetap khusus analisis dan menolak `/auto on`.
Tunggu bootstrap/collector siap, lalu kirim `/start` ke bot. Gunakan satu bot Telegram
khusus untuk satu collector aktif: dua proses yang memanggil getUpdates akan bersaing.
Webhook yang sudah dipakai aplikasi lain perlu ditinjau sendiri; kode tidak menghapusnya.

Perintah hanya diterima dalam **chat pribadi** dengan chat ID dan ID pengirim sama
seperti `TELEGRAM_CHAT_ID`. Grup/channel tidak didukung untuk kontrol. Jangan memakai
username sebagai ID kontrol. Semua pesan sebelum startup, lebih dari dua menit,
atau update yang sudah diproses diabaikan. Pada awal polling, backlog lama dilewati.

## Mulai tanpa menghafal command

1. Kirim `/start`: bot menjelaskan mode akun dan menampilkan tombol.
2. Tekan **Lihat candle**, lalu ketik `BTC 15m` untuk grafik. Coin saja membuka
   pilihan timeframe; contoh pair lengkap `ETHUSDT 1h` juga diterima.
3. Tekan **Analisis coin**, ketik `SOL`, lalu pilih preset **Scalping**, **Intraday**
   atau **Swing**. Input lengkap `BTC 1m 5m 15m` juga diterima.
4. Tekan **Cari coin**, lalu ketik `USDT`, `SOL`, atau `bitcoin`.
5. Tekan **Status akun** untuk hasil virtual; **Cara pakai** menjelaskan istilahnya.
6. **Atur demo** membuka kontrol entry, daftar eligible dan notifikasi otomatis.

Tombol tampil sebagai keyboard di bawah kolom pesan. Bila tersembunyi, tekan ikon
keyboard Telegram atau kirim `/menu`. Command lama tetap berfungsi. Balasan input
berlaku lima menit, hanya untuk pemilik chat; **Batal**, **Menu utama** atau command
baru membatalkan permintaan input sebelumnya. Jika salah input, pilih tombol lagi.
Saat memilih timeframe, **Kembali** mengganti coin; **Batal** membuka menu utama.
Interval tidak valid tetap berada di langkah pemilihan agar bisa diperbaiki. Deadline
lima menit dihitung dari mulai alur, tidak diperpanjang oleh input berulang.
Sesudah grafik terkirim, menu utama ditampilkan kembali.
Setelah restart bot, gunakan `/menu` untuk memulai kembali dengan jelas.

`/start` tidak menyalakan atau mematikan auto-buy. Tombol **Aktifkan auto-buy demo**
setara `/auto on`; **Jeda auto-buy demo** setara `/auto off`. Tombol tetap tunduk
pada mode belajar, halt dan kill-switch. Memilih coin demo tidak memaksa pembelian.
Jeda bukan perintah menutup posisi. Posisi hanya dikelola selama proses berjalan.

## Memuat pembaruan pada proses yang sudah berjalan

Push GitHub tidak memperbarui proses Python yang sedang berjalan. Di terminal repo,
jalankan `git pull --ff-only`; jika Git menolak karena perubahan lokal, jangan reset
paksa karena config lokal perlu dipertahankan. Hentikan proses lama secara normal
(Ctrl+C pada terminal proses), lalu jalankan kembali launcher/config yang sama.
Jangan jalankan dua collector dengan bot Telegram yang sama. Database dan `.env`
tetap digunakan; jangan dihapus. Setelah collector siap, kirim `/start` lagi.
Selama proses berhenti, posisi demo tidak dikelola.

## Menu command

| Perintah | Hasil |
| --- | --- |
| `/start` atau `/menu` | Menu tombol dan penjelasan mode akun |
| `/guide` | Panduan pemula |
| `/demo` | Menu kontrol akun demo |
| `/why` | Pemeriksaan mode, pause, data, posisi dan setup entry |
| `/position` | Entry, quantity, waktu entry, SL/TP posisi demo |


| Perintah | Hasil |
| --- | --- |
| `/help` | Daftar perintah |
| `/status` atau `/health` | Health, equity virtual, jumlah trade, WR, PF, expectancy, posisi, halt |
| `/coins 1` atau `/coins bitcoin 1` | Cari semua pair Binance Spot aktif, 40 per halaman |
| `/eligible 1` | Pair yang lolos scanner untuk watchlist dan trading demo |
| `/signals` | Sampai 20 analisis tersimpan terbaru; stale ditandai |
| `/signals BTCUSDT` | Analisis terakhir coin yang dipilih |
| `/settings` | Watchlist, cakupan auto-buy, mode dan jeda gambar |
| `/watch BTCUSDT ETHUSDT` | Batasi notifikasi gambar otomatis ke coin tersebut |
| `/watch ALL` | Gambar dari semua pair yang dipindai, tetap dibatasi frekuensi |
| `/chart bitcoin 15m` | Grafik terbaru coin dan interval pilihan dari API publik |
| `/chart ETH/BTC 4h` | Pair eksplisit, dengan sumbu harga dalam BTC |
| `/intervals` | Interval candle yang didukung |
| `/analyze bitcoin` | Analisis default 1m, 5m, 15m |
| `/analyze SOL 5m 15m 1h 4h` | Bandingkan maksimal empat timeframe |
| `/mode observe` | Gambar pengamatan, tidak harus menunggu setup |
| `/mode setups` | Gambar hanya ketika setup entry terdeteksi |
| `/alerts off` atau `/alerts on` | Matikan/hidupkan gambar otomatis |
| `/tradecoins BTCUSDT ETHUSDT` | Batasi entry demo baru pada coin tersebut |
| `/tradecoins ALL` | Semua pair eligible boleh dipilih strategi untuk entry demo |
| `/auto off` | Hentikan entry demo baru; posisi yang ada tetap dikelola SL/TP |
| `/auto on` | Izinkan entry demo dari sinyal baru bila risk halt/kill-switch tidak aktif |

Perubahan watchlist/mode/auto disimpan di database, bertahan saat restart. `/watch`
tidak mengubah coin trading; `/tradecoins` tidak menutup posisi yang sudah ada.
`/alerts off` tidak mematikan balasan command atau pesan order demo. Pesan DEMO BUY/SELL
menyatakan eksekusi virtual; lihat `/status` untuk hasil akun. Setting ini berlaku hanya
pada database akun terkait, bukan akun lain atau konfigurasi Testnet/live.

Akun demo trading sebelumnya memang melakukan entry otomatis saat memenuhi syarat.
Mengaktifkan command tidak otomatis mem-pause akun tersebut; periksa `/status`, gunakan
`/auto off` jika ingin menunda. `/auto on` tidak memaksa buy dan membersihkan pending
lama agar entry berikutnya menunggu sinyal baru. Risk halt/kill-switch tidak dapat
reset melalui Telegram. Posisi offline tidak dilindungi stop exchange.

## Seleksi coin dan entry

Harga yang naik saja tidak cukup. Scanner memfilter status Spot, volume 24 jam,
spread, dukungan order dan base pengecualian. Strategi kurva memerlukan tren, pullback,
pemulihan terkonfirmasi, ADX/ATR/volume dan skor minimum. Sebelum entry, engine mengecek
spread saat itu, umur sinyal, pergeseran harga, lot/minimum notional, partisipasi volume,
saldo dan batas risiko. Maksimal satu posisi untuk akun; fee/slippage tetap dihitung.

Filter ini mengurangi sebagian kondisi trading buruk; bukan penilaian fundamental,
audit token, pemeriksaan manipulasi atau jaminan bebas scam. Volume 24 jam dan daftar
coin berasal dari snapshot startup, belum hot-refresh. Tidak semua crypto/exchange
tercakup. Kurva masa lalu tidak menjamin harga akan terus naik. WR dan profitabilitas
preset masih perlu diuji pada data 1m forward; pajak belum termasuk PnL simulator.

## Ketahanan dan privasi

Polling memakai request keluar, tanpa port publik/webhook. Satu update diproses per
putaran (sekitar 5 detik setelah request selesai), lalu pesan order baru bila ada.
Gangguan command diberi jeda 60 detik; collector tetap berjalan. Grafik manual menolak histori berlubang dan data basi berdasarkan interval yang dipilih.
Timestamp gambar tetap perlu dibaca.

Perubahan state dan nomor update disimpan sebelum balasan dikirim. Jika jaringan gagal,
perintah bisa sudah berlaku meski balasan tidak sampai: cek `/status` dan `/settings`.
Pesan order dicatat sebelum kirim, tidak diulang setelah timeout/restart, sehingga
notifikasi bisa hilang. Pesan lama tidak dikirim sebagai transaksi baru.

`/status` mengirim ringkasan akun virtual ke chat pemilik yang dikonfigurasi. Perlakukan
chat/perangkat Telegram sebagai akses kontrol akun demo. Token dan detail error jaringan
tidak dicetak ke chat/log. Riwayat pengaturan lokal bukan pengganti backup privat.
Tes lokal memakai Telegram tiruan; aktivasi/pengiriman pada chat pengguna belum diverifikasi.

## Coin dan timeframe grafik

Contoh: `/chart BTC 1m`, `/chart ethereum 15m`, `/chart SOLUSDT 1h`,
`/chart ETH/BTC 4h`, `/chart BTC 1M`. Tanpa interval, gunakan interval config demo.
Interval: `1s 1m 3m 5m 15m 30m 1h 2h 4h 6h 8h 12h 1d 3d 1w 1M`.
Huruf besar penting: `1m` menit, `1M` bulan kalender.

Ticker dan pair mengikuti katalog Binance Spot aktif; nama umum seperti bitcoin,
ethereum, solana, dogecoin juga dikenali. Nama lengkap semua token belum tersedia:
gunakan ticker jika nama tidak dikenali. Coin tanpa pair USDT meminta pilihan pair
bila ada beberapa pasangan. `/coins SOL` mencari pasangan, `/eligible` menampilkan
universe trading akun. Tidak mencakup crypto yang tidak terdaftar di Binance Spot.

Grafik mengambil hingga 500 candle publik dan menggambar candle tertutup terbaru
sebanyak `candle_alerts.bars`. Tidak meminta API key exchange, tidak menyimpan hasil
on-demand ke dataset strategi. Coin baru dengan kurang dari dua candle ditolak.
Interval grafik tidak mengubah timeframe strategi, watchlist, atau izin auto-buy.
`/watch BTC ethereum` dan `/tradecoins BTC` menerima alias tetapi tetap hanya eligible.
Grafik manual juga bisa melihat pair yang tidak lolos filter trading.

## Analisis beberapa timeframe

`/analyze BTC 1m 5m 15m` mengambil candle tertutup terbaru untuk setiap interval.
Laporan berisi susunan harga/EMA dan arah EMA lambat, RSI, MACD histogram dan
perubahannya, ATR sebagai persen harga, serta volume relatif terhadap rata-rata
candle sebelumnya. Body/wick ditampilkan sebagai persen rentang high-low candle.
Harga juga dibandingkan dengan high/low `strategy.bb_period` candle sebelumnya;
rentang tersebut hanya deskripsi historis, bukan level support/resistance terjamin.

Periode indikator mengikuti `strategy` pada config akun. Volume referensi dan range
tidak memasukkan candle yang sedang dinilai. RSI pada jendela benar-benar datar
ditampilkan 50; volume pembanding nol ditampilkan N/A. Histori pendek, stale atau
berlubang tidak menghasilkan konfirmasi. Kegagalan satu timeframe ditandai DATA TIDAK
LENGKAP; timeframe lain tetap bisa ditampilkan. Error transport tidak dibocorkan.

Default bisa diatur dalam blok `candle_alerts` yang sudah ada:

```yaml
analysis_intervals: [1m, 5m, 15m]
```

Maksimal empat interval unik per request; interval duplikat hanya diambil sekali.
Permintaan dilakukan berurutan untuk membatasi beban API, jadi timestamp terakhir
tiap timeframe bisa berbeda; laporan bukan snapshot simultan atau sinyal backtest.
Analisis berjalan dalam worker kontrol Telegram, terpisah dari collector demo.
Permintaan jaringan lambat dapat menunda balasan command berikutnya.

Keselarasan tren adalah ringkasan aturan, bukan skor probabilitas, rekomendasi buy,
atau bukti peningkatan win rate. Perintah ini tidak mengubah auto-buy, pending order,
strategi, watchlist atau gate live. Tetap uji strategi lewat backtest dan paper trading.

## Pilihan timeframe dan diagnosis

Preset menu **Analisis coin** hanya memilih interval laporan:

| Preset | Timeframe |
| --- | --- |
| Scalping | 1m, 5m, 15m |
| Intraday | 15m, 1h, 4h |
| Swing | 4h, 1d, 1w |

Preset tidak mengganti strategi atau mode trading. Semua interval yang didukung
juga bisa diketik manual; `1M` bulan berbeda dari `1m` menit. Shortcut command
langsung `/chart BTC` tetap memakai interval akun; pemilihan bertahap berlaku saat
masuk lewat tombol **Lihat candle**. `/analyze BTC` tetap memakai default config.

**Kenapa belum buy?** menampilkan pemeriksaan akun berdasarkan state saat dibaca:
mode belajar, auto entry dijeda, risk halt/kill-switch, heartbeat, kesehatan data,
posisi terbuka, dan hitungan analisis/sinyal segar dalam pilihan coin entry. Data
sinyal dibatasi maksimal 2000 coin terbaru, bukan pemindaian baru ke exchange.
Riwayat `entry_skipped` dicari dalam 200 event terakhir dan diberi timestamp;
kejadian lama tidak dianggap alasan penolakan saat ini. Detail error jaringan tidak
dikirim. Laporan ini tidak merekonstruksi setiap keputusan engine atau menjamin
order ketika semua pemeriksaan terlihat baik.

**Posisi aktif** menampilkan ukuran, entry, SL dan TP dari posisi virtual yang
tersimpan. Bukan order proteksi di exchange: bot harus berjalan dan menerima harga
untuk mengelolanya. Semua menu diagnosis hanya membaca data, tidak reset halt atau
mengubah posisi, sinyal, dan auto-buy.

## Teknik strategi per coin

**Daftar strategi** (`/strategies`) menjelaskan lima implementasi yang tersedia dan
nama strategi aktif. **Cek teknik coin** meminta coin lalu timeframe, misalnya SOL
lalu 15m. Shortcut: `/techniques SOL 15m`. Nama umum dan pair eksplisit mengikuti
resolver chart. Berlaku untuk pair Binance Spot aktif, termasuk pair USDT.

| Implementasi | Teknik entry |
| --- | --- |
| `rule_based_v1` | EMA cross baru, tren SMA, konfirmasi RSI/MACD/Bollinger/volume |
| `quality_cross_v1` | Baseline plus ADX, rentang ATR, volume relatif, filter candle ekstrem dan jarak harga |
| `adaptive_trend_v2` | Tren EMA harian, pullback/persilangan pulih, momentum dan kualitas |
| `regime_reversion_v3` | Rebound terkonfirmasi pada tren/range, RSI dan Bollinger; hindari regime bearish |
| `curve_scalping_v1` | Kemiringan tren, pullback EMA, recovery melewati high sebelumnya, efisiensi gerak dan kualitas candle |

Perbandingan menjalankan `build_strategy(...).prepare(...)` yang sama dengan engine,
bukan meniru logika lewat teks. Parameter tiap evaluasi mengikuti config strategi
akun saat ini, sehingga ini bukan kompetisi preset yang sudah dioptimalkan. Hasil:

- `SETUP ENTRY`: aturan entry terpenuhi pada candle tertutup terakhir.
- `EXIT CONDITION`: aturan exit terpenuhi; diprioritaskan bila entry juga benar.
- `WAIT`: indikator siap tetapi entry/exit tidak terpenuhi.
- `DATA KURANG` / `DATA TIDAK VALID`: belum bisa menilai; bukan sinyal negatif.

Curve scalping juga menampilkan cek trend, pullback, recovery, quality dan score.
Detail `signal_reason` mengikuti nama alasan di engine. Grafik publik dibatasi 500
candle; pada timeframe kecil ini biasanya tidak cukup untuk EMA harian. Dua strategi
yang memerlukan histori harian akan ditandai DATA KURANG. Gunakan data historis
untuk backtest lengkap, jangan menurunkan warmup demi memaksa sinyal.

Perbandingan ini tidak menambahkan pending order, memilih strategi terbaik otomatis,
mengubah config aktif, atau melatih model. Teknik yang berkorelasi tidak dihitung
sebagai voting probabilitas. Exit adalah kondisi keluar posisi long, bukan short.
Setup tetap memerlukan validasi fresh price, spread, likuiditas, saldo, fee/slippage,
SL/TP dan risk limits saat eksekusi. Uji out-of-sample dan demo tetap diperlukan.

## Di mana entry, SL, dan TP?

Tekan **Rencana entry demo**, pilih coin dan timeframe. Shortcut `/plan SOL 15m`.
Hanya pair USDT karena modal akun dihitung dalam USDT. Laporan memuat:

- Strategi akun dan hasil evaluasinya pada candle tertutup terakhir.
- Hambatan yang terlihat: mode belajar, pause, risk halt, kesehatan collector,
  posisi terbuka, coin di luar eligible/pilihan, timeframe berbeda, atau belum ada setup.
- Acuan buy hipotetis = close candle terakhir ditambah slippage config.
- Quantity, notional dan fee entry dari saldo kas virtual dengan RiskManager yang
  sama, termasuk lot size, tick, minimum notional, batas alokasi dan stop risk.
- SL/TP berdasarkan risk config (persen atau ATR), estimasi loss/PnL net fee serta
  slippage kedua sisi, dan rasio net TP/loss.

Ukuran yang tidak memenuhi minimum/aturan risiko ditolak. Batas partisipasi volume
juga diperiksa. Harga referensi bukan bid/ask aktual; spread, depth, pajak, umur
sinyal dan perubahan harga sebelum fill belum dihitung dalam preview. Estimasi loss
bukan batas kerugian terjamin, karena gap dan fill buruk dapat memperbesarnya.

Preview tetap bisa menunjukkan angka hipotetis saat ada penghalang; bukan persetujuan
entry. Ia tidak menaruh pending order dan tidak memanggil broker. Engine demo tetap
memakai quote aktual dan memeriksa seluruh batas sebelum entry. Tidak ada tombol
paksa BUY atau aktivasi live pada menu ini. Jangan menilai profitabilitas hanya dari
rasio rencana; statistik out-of-sample dan forward demo masih harus dibuktikan.

## Jelajahi semua coin/token Binance Spot

Menu **Semua pair USDT** (`/markets USDT`) menampilkan seluruh pair aktif dengan
quote USDT, 30 pair per halaman. **Semua pair Spot** (`/markets ALL`) juga mencakup
quote lain; `/markets BTC 1` memfilter quote BTC secara persis, bukan substring.
Gunakan **Halaman berikut** / **Halaman sebelumnya**; posisi halaman tersimpan per
akun. Halaman yang melebihi batas dikembalikan ke halaman terakhir. Daftar disortir
berdasarkan symbol; posisi halaman dapat bergeser setelah katalog diperbarui.

**Detail coin** (`/coin SOL`) menampilkan pasangan aktif, keikutsertaan dalam
collector, dan alasan filter scanner jika tersimpan. Bisa juga memakai pair lengkap
seperti `/coin ETHBTC`. Alasan merujuk snapshot startup, bukan klaim kondisi pasar
saat ini. Coin tanpa alasan tersimpan disebut belum masuk snapshot; tidak ditebak
sebagai coin berbahaya. `collector=ya` hanya berarti masuk daftar sumber akun,
bukan bukti runtime sehat; lihat Status akun untuk heartbeat/kesehatan data.

**Cakupan pasar** (`/coverage`) menampilkan jumlah base asset unik, pair per quote,
dan jumlah pair dalam collector akun. Katalog dimuat lewat API publik dan diperbarui
pada permintaan setelah cache berumur 15 menit, sehingga listing aktif baru bisa
muncul tanpa mengganti daftar ticker dalam kode. Ini tidak menambahkan subscription
atau order otomatis; collector masih menggunakan snapshot startup.

Semua pair dalam katalog dapat diminta chart, analisis dan perbandingan teknik;
histori terlalu pendek/invalid tetap ditolak. Bot tidak dibatasi tombol contoh
BTC/ETH/SOL: ketik ticker atau pair lain. Nama lengkap token tidak selalu tersedia;
gunakan ticker jika alias tidak dikenali. Detail coin membatasi tampilan 30 pair;
`/coins TICKER` menyediakan pencarian berhalaman.

Preset `config/all-scalping-demo.yaml` sudah memakai `universe.mode: all` dan
`max_symbols: null`, tetapi entry demo tetap hanya pair USDT yang lolos volume,
spread, status Spot, dukungan order dan pengecualian config. Melihat seluruh pair
bukan berarti merekam semua pair sekaligus atau membeli semuanya. Token DEX,
contract address, futures, delisted dan aset di luar Binance Spot belum didukung.
