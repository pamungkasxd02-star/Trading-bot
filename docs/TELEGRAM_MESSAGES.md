# Tampilan pesan Telegram

Pesan memakai judul pendek, satu informasi per baris, dan baris kosong antarblok.
Status akun, posisi, dan rencana entry dipisahkan agar mudah dibaca di layar ponsel.

## Contoh posisi

Contoh format berikut memakai angka ilustrasi, bukan transaksi atau hasil bot:

```text
Posisi demo · BTCUSDT

Entry: 60000 USDT
Jumlah: 0.0001

Stop-loss: 59400
take-profit: 61200

Dibuka: 25 Sep 2026, 10:00:00 UTC

SL/TP virtual memerlukan bot aktif dan data harga tersedia.
```

## Cara membaca

- **Mode** menunjukkan akun demo atau belajar tanpa order.
- **Auto entry ON** mengizinkan pemeriksaan sinyal; belum berarti sudah buy.
- **Posisi** menunjukkan coin yang sedang dipegang akun virtual.
- **Win rate dan profit factor** berasal dari trade yang sudah selesai.
- **N/A** berarti nilai belum tersedia atau belum dapat dihitung, bukan nol.
- **Rencana entry** merupakan perhitungan skenario, bukan konfirmasi order.

Harga dan jumlah ditulis sebagai desimal biasa. Harga coin kecil tidak dibulatkan
menjadi nol. Equity diringkas sampai dua desimal. Waktu ditulis dengan zona UTC;
waktu tanpa zona tidak otomatis dianggap sebagai waktu lokal pengguna.

## Pedoman penulisan

Tulis kondisi lebih dulu, lalu angka atau alasan, terakhir tindakan yang tersedia.
Gunakan nama tombol yang sama dengan menu. Hindari pembuka berulang, emoji dekoratif,
dan klaim seperti “pasti naik” atau “akurasi tinggi”. Penjelasan penggunaan panjang
ada di bantuan, sedangkan batasan yang menentukan arti pesan tetap ada di pesan itu.

Setelah kode diperbarui dan proses bot dimulai ulang, kirim `/start` untuk menu,
`/status` untuk ringkasan, atau `/position` untuk posisi terbuka.
