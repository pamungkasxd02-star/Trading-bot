# Privasi data Codespaces

Repo ini publik pada pemeriksaan 24 September 2026. Semua file/commit yang dipush ke
repo publik dapat dibaca orang lain. README tidak mengatur izin akses. Codespace dan
file lokalnya tidak otomatis menjadi publik hanya karena repository sumber publik.

## Perlindungan dalam repository

- Git mengabaikan `.env` dan variannya (kecuali template kosong `.env.example`), database
  dan file WAL/SHM, log, private key, arsip, folder backup/exports, serta data runtime.
- Docker mengabaikan salinan file sensitif serupa agar tidak ikut build context.
- `scripts/privacy-check.py` memeriksa Git index: path runtime dan beberapa bentuk
  credential umum. Ia tidak mencetak isi atau nilai secret. Lolos bukan jaminan bebas
  secret: format custom, histori commit, isi artifact dan pengaturan akun tidak diaudit.
- Hook pre-commit menjalankan pemeriksaan pada file staged. Setup Codespaces baru
  memasangnya jika belum ada `core.hooksPath` lain; hook custom tidak ditimpa.
- CI memeriksa seluruh Git index. **CI terjadi setelah push**, jadi CI sendiri tidak
  mencegah paparan pertama. Hook lokal dapat dilewati; tinjau setiap commit.
- Forwarding port otomatis dinonaktifkan pada konfigurasi devcontainer. Ini tidak
  menutup port yang sudah dibagikan secara manual dan bukan aturan firewall.
- Script demo/setup memakai `umask 077`: file baru dibatasi pada pengguna pembuatnya
  pada Linux. Ini tidak mengubah izin file lama atau melindungi dari proses akun yang sama.

Laporan yang sengaja dipublikasikan di `reports/baseline`, `evaluation-v0_4`,
`evaluation-v0_5`, dan `evaluation-quality` berisi riset historis. Jangan menyimpan
export akun pribadi di folder tersebut. Gunakan `exports/` atau `backups/`.

## Terapkan pada Codespace yang sudah ada

Setelah menarik perubahan repository, dari terminal folder proyek:

```bash
# Lihat hook custom sebelum memilih pemasangan:
git config --get core.hooksPath
# Jika belum ada hook custom, pasang hook proyek:
git config --local core.hooksPath .githooks
python3 scripts/privacy-check.py
umask 077
# Berlaku untuk .env yang sudah ada:
[ ! -f .env ] || chmod 600 .env
```

Jangan menimpa hook custom jika dipakai tool lain; tambahkan pemanggilan
`python3 scripts/privacy-check.py --staged` ke hook yang dikelola tool itu.
Perubahan devcontainer perlu diterapkan melalui rebuild; backup dahulu bila diperlukan.
Status penerapan pada instance Codespace lama belum diverifikasi dari repository.

Di tab **Ports**, hentikan forwarding yang tidak diperlukan. Untuk port yang diperlukan,
pilih **Port Visibility → Private**. Jangan menjalankan `python -m http.server` pada root
proyek untuk membagikan file, sebab endpoint dapat menyajikan database atau `.env`.
Bot CLI tidak memerlukan port publik.

## Sebelum commit/push atau berbagi screenshot

```bash
git status --short
python3 scripts/privacy-check.py --staged
git diff --cached --stat
```

Tinjau isi perubahan di editor privat; jangan membagikan terminal yang menampilkan
secret, environment lengkap, metadata akun atau tautan akses. `.gitignore` tidak
menghapus file yang sudah tracked dan tidak membersihkan histori.

Tidak perlu key Binance untuk demo internal. Jika memakai Testnet kelak, simpan key
pada `.env` lokal atau Codespaces Secrets dengan cakupan repository yang diperlukan.
Jangan taruh key pada YAML, workflow, issue, README atau prompt. Batasi akses akun
GitHub, collaborator, aplikasi terhubung, dan gunakan autentikasi dua faktor.

## Backup dan artifact

Export dapat berisi saldo dan log transaksi. Simpan pada folder yang diabaikan Git,
lalu unduh ke penyimpanan pribadi yang terlindungi. Jangan mengunggah `.db`, backup,
atau hasil demo akun ke Releases, issue attachment, GitHub Pages, atau artifact publik.
Workflow CI/research yang ada hanya mengunggah replay historis dari runner bersih;
jangan mengubah path upload menjadi seluruh workspace atau folder data akun.

Jika secret pernah terunggah: revokasi/rotasi segera, lalu periksa commit, artifact,
log dan salinan yang sudah terlanjur dibagikan. Menghapus file pada commit terbaru
atau mengubah repo menjadi private tidak membatalkan credential yang sudah terekspos.
Pembersihan histori memerlukan peninjauan terpisah, terutama bila ada clone/fork.

Referensi resmi:
- [Keamanan Codespaces](https://docs.github.com/en/codespaces/reference/security-in-github-codespaces)
- [Atribut devcontainer](https://github.com/devcontainers/spec/blob/main/docs/specs/devcontainerjson-reference.md)
