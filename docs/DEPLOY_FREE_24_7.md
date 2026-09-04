# Deployment paper trading 24/7 — free VM

Deployment ini hanya menjalankan **Binance Spot Testnet**. Container dikunci ke mode
`paper`, tidak membuka port aplikasi, berjalan sebagai user non-root, dan menyimpan
database dalam Docker named volume.

## Pilihan layanan

Pilihan utama adalah VM Ubuntu pada
[Oracle Cloud Always Free](https://docs.oracle.com/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm).
Pilih shape yang ditandai Always Free eligible di home region. Oracle menyediakan block
volume persisten, tetapi menyatakan bahwa instance Always Free yang dianggap idle dapat
direklamasi. Jangan membuat beban palsu untuk menghindari kebijakan itu; simpan backup dan
anggap layanan gratis tidak memiliki jaminan uptime.

Fallback adalah satu VM `e2-micro` pada region Always Free Google Cloud yang tercantum di
[dokumentasi Free Tier](https://cloud.google.com/free/docs/free-cloud-features).
Region gratis Google terbatas. Sebelum memasukkan secret, pastikan endpoint Testnet dapat
diakses dari region yang dipilih.

GitHub Actions dan free web service bukan pengganti VM ini. Job GitHub-hosted dibatasi
[maksimal enam jam](https://docs.github.com/en/actions/reference/limits), sementara free
web service yang tidur tidak menghitung 14 hari runtime aktif secara kontinu.

## 1. Buat VM

- Gunakan Ubuntu 24.04 LTS, arsitektur `amd64` atau `arm64`.
- Gunakan SSH key, bukan password sederhana.
- Buka inbound SSH port 22 hanya untuk IP Anda bila memungkinkan.
- Bot tidak membutuhkan inbound HTTP/HTTPS; jangan membuka database atau Docker socket.
- Periksa peraturan dan ketersediaan Binance di yurisdiksi serta region server Anda.

Masuk melalui SSH, lalu pastikan koneksi Testnet tersedia:

```bash
curl -fsS https://testnet.binance.vision/api/v3/time
```

## 2. Clone dan pasang Docker

```bash
git clone https://github.com/pamungkasxd02-star/Trading-bot.git
cd Trading-bot
chmod +x scripts/server-*.sh
./scripts/server-bootstrap-ubuntu.sh
```

Script memakai repository paket resmi Docker untuk Ubuntu/Debian. Jika membership group
Docker belum aktif, logout/login dapat dilakukan; script start juga dapat memakai `sudo`
sebagai fallback.

## 3. Tambahkan credential Testnet

Buat key di [Binance Spot Test Network](https://testnet.binance.vision/). Jangan gunakan
key production, jangan kirim key lewat chat, dan jangan commit `.env`.

```bash
cp .env.example .env
chmod 600 .env
nano .env
```

Isi minimal:

```dotenv
BINANCE_API_KEY=isi_key_testnet
BINANCE_API_SECRET=isi_secret_testnet
SPOTLAB_CONFIG=config/paper-server.yaml
SPOTLAB_HISTORY_MONTHS=24
```

Telegram bersifat opsional. `server-start.sh` membuat `config/paper-server.yaml` dari
default jika belum tersedia. File itu diabaikan Git sehingga parameter server lokal tidak
tertimpa atau terkirim ke repository.

## 4. Jalankan

```bash
./scripts/server-start.sh
./scripts/server-status.sh
```

Container akan melakukan fetch/upsert data dahulu, kemudian menjalankan `spotlab paper`.
Restart policy `unless-stopped`, WebSocket reconnect, persistent position state, dan OCO
exchange-side membuat proses dapat pulih dari reboot atau koneksi terputus. Setelah crash,
recovery session dapat menunggu sampai heartbeat lama dinyatakan stale.

Perintah pemantauan:

```bash
docker compose ps
docker compose logs --follow --tail 100 paper
docker compose exec --no-TTY paper spotlab-container health
docker compose exec --no-TTY paper spotlab-container readiness
```

`readiness` keluar dengan kode 3 selama paper gate belum memenuhi 14 hari runtime aktif,
20 trade tertutup, dan batas metrik. Itu normal dan tidak berarti container rusak.

## Backup jurnal

SQLite backup dilakukan melalui API backup, bukan menyalin file database yang sedang
aktif:

```bash
docker compose exec --no-TTY paper \
  spotlab-container backup --output data/runtime-backup.db
docker compose cp paper:/app/data/runtime-backup.db ./runtime-backup.db
```

Simpan hasil backup di tempat terpisah. Dataset market dapat di-fetch ulang; `runtime.db`
berisi durasi paper, signal, order, posisi, trade, dan equity yang dibutuhkan gate.

## Stop, kill-switch, dan update

Stop normal:

```bash
docker compose stop paper
```

Emergency stop sekaligus membuat kill-switch persisten:

```bash
docker compose exec --no-TTY paper spotlab-container kill
docker compose stop paper
```

OCO yang sudah dikirim tetap aktif di Binance. Periksa order/posisi Testnet sebelum
membersihkan kill-switch.

```bash
docker compose run --rm --no-deps paper clear-kill
docker compose up --detach paper
```

Update kode tanpa menghapus volume:

```bash
git pull --ff-only
docker compose up --detach --build paper
```

Jangan menjalankan `docker compose down --volumes`; opsi `--volumes` menghapus database
paper. Deployment gratis tidak menjamin uptime—cek health dan backup secara berkala.
