#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

if [[ ! -f .env ]]; then
  cp .env.example .env
  chmod 600 .env
  echo "File .env dibuat. Isi API key Binance Spot Testnet, lalu jalankan ulang script ini." >&2
  exit 2
fi

chmod 600 .env
if ! grep -Eq '^BINANCE_API_KEY=.+$' .env || ! grep -Eq '^BINANCE_API_SECRET=.+$' .env; then
  echo "BINANCE_API_KEY dan BINANCE_API_SECRET Testnet wajib diisi di .env" >&2
  exit 2
fi

if [[ ! -f config/paper-server.yaml ]]; then
  cp config/default.yaml config/paper-server.yaml
fi

if docker info >/dev/null 2>&1; then
  docker_cmd=(docker)
elif command -v sudo >/dev/null 2>&1 && sudo docker info >/dev/null 2>&1; then
  docker_cmd=(sudo docker)
else
  echo "Docker daemon tidak dapat diakses. Jalankan server-bootstrap-ubuntu.sh dahulu." >&2
  exit 1
fi

"${docker_cmd[@]}" compose up --detach --build paper
"${docker_cmd[@]}" compose ps
echo "Paper bot dimulai. Pantau dengan ./scripts/server-status.sh"
