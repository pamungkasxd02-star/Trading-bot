# Security Policy

## Secrets

- Simpan key hanya di `.env`; file itu sudah diabaikan Git.
- Gunakan key berbeda untuk Testnet dan production.
- Production key harus trade-only, tanpa withdrawal, dan sebaiknya dibatasi IP.
- Jangan unggah database runtime karena payload order dapat memuat metadata akun/order.
- Rotasi key segera bila pernah muncul di terminal recording, issue, commit, atau chat.

## Menjalankan live

Live trading tetap berisiko: koneksi putus, gap harga, stop-limit tidak terisi, exchange
downtime, perubahan filter, bug, dan kompromi key dapat menyebabkan kerugian. Mulai dari
Testnet, tinjau log manual, dan jangan menaruh dana lain pada key yang sama bila tidak siap
menanggung risiko aksesnya.

## Pelaporan kerentanan

Jangan membuka issue publik yang berisi secret atau detail akun. Revokasi credential lebih
dulu, lalu kirim laporan privat melalui fitur security advisory GitHub repository.
