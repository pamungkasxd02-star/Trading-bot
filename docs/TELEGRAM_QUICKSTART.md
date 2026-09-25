# Mulai dari /start

Sesudah bot siap, buka chat pribadi bot dan kirim `/start`. Jika keyboard tidak
terlihat, tekan ikon keyboard Telegram atau `/menu`. Membuka menu tidak mengaktifkan
atau menjeda auto-buy. Mode belajar dan demo memakai akun yang berbeda sesuai config.

## Peta menu

| Bagian | Tombol dan kegunaan | Mengubah trading? |
| --- | --- | --- |
| Pintasan utama | Lihat candle; Status akun | Tidak |
| Pasar dan coin | Cari coin, Detail coin, Semua pair USDT/Spot, Lihat candle, Cakupan pasar | Tidak |
| Strategi dan analisis | Analisis coin, Sinyal terbaru, Daftar strategi, Cek teknik coin, Rencana entry demo | Tidak |
| Akun demo | Status akun, Posisi aktif, Kenapa belum buy?, Pengaturan, Coin eligible, Pilih coin demo, Jeda/Aktifkan auto-buy demo | Pilihan coin dan tombol auto mengubah entry demo baru |
| Notifikasi | Pilih notifikasi coin, Pengaturan, Gambar ON/OFF, Hanya setup, Semua pengamatan | Tidak; hanya pesan gambar otomatis |
| Panduan dan bantuan | Cara pakai, Arti istilah, Data dan riset, Bot tidak merespons | Tidak |

Nama tombol lama **Atur demo** dan semua command lama tetap diterima. Hasil tindakan
kembali ke keyboard bagian aktif; katalog mempertahankan tombol halaman. **Menu utama**
atau **Batal** kembali ke awal, **Kembali** pada pilihan timeframe mengganti coin.
Navigasi baru membatalkan input yang sedang ditunggu. Input berlaku lima menit.

## Contoh 1: belajar membaca candle

1. Tekan **Lihat candle**, pilih BTC atau ketik ticker coin lain.
2. Pilih **15m**. Bot mengirim gambar candle tertutup terbaru.
3. Buka **Strategi dan analisis → Analisis coin**, ketik BTC, lalu **Scalping**.
4. Baca arah tren dan timestamp. Preset Scalping hanya memilih timeframe laporan.
5. **Cek teknik coin** membandingkan aturan; **Rencana entry demo** memperkirakan
   ukuran, harga referensi, SL/TP dan biaya. Keduanya tidak mengirim order.

## Contoh 2: mengelola demo

1. **Akun demo → Status akun**: periksa mode, kondisi proses, auto entry dan risk halt.
2. **Coin eligible** menampilkan pilihan scanner. **Pilih coin demo** membatasi
   pilihan, misalnya `BTC ETH`. Memilih coin tidak memaksa buy.
3. **Aktifkan auto-buy demo** mengizinkan engine menunggu setup baru; mode belajar
   atau risk halt tetap menolak aktivasi. Tidak ada tombol untuk melewati batas itu.
4. **Kenapa belum buy?** membantu membedakan belum ada setup, data basi, pause,
   halt atau posisi yang masih terbuka.
5. **Posisi aktif** menunjukkan entry dan SL/TP virtual. **Jeda auto-buy demo**
   hanya menghentikan entry baru, bukan menutup posisi. Bot harus tetap berjalan
   dan menerima harga untuk mengelola posisi lama.

## Membaca status dan pengaturan

- ON berarti pilihan auto entry aktif; bukan janji akan membeli.
- Kondisi sehat/degraded/offline berkaitan dengan proses dan data, bukan kualitas investasi.
- N/A pada statistik berarti belum dapat dihitung; bukan nol atau 100% menang.
- Coin gambar adalah filter notifikasi. Coin entry demo adalah filter pembelian virtual.
- Gambar OFF tidak mematikan command atau pesan order demo.
- Mode pengamatan tidak mengubah strategi atau mengaktifkan order.
- Jumlah pair katalog berbeda dari data collector, dataset riset, dan job yang selesai.

## Memakai update menu

Di terminal repo jalankan `git pull --ff-only`, lalu restart proses bot dengan
launcher/config yang sama. Jika Git menolak perubahan lokal, jangan reset paksa.
Jangan membuat collector kedua. Setelah proses siap kirim `/start` lagi. Token,
`.env` dan database tidak perlu dikirim ke chat atau dihapus. Menu telah diuji
lokal dengan Telegram tiruan; tampilan pada chat pengguna perlu diperiksa setelah restart.
