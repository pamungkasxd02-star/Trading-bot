#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"
if [[ ! -x .venv/bin/python ]]; then
  echo "Jalankan bash scripts/codespaces-setup.sh dahulu." >&2
  exit 2
fi
exec .venv/bin/python scripts/research_regime.py --demo --download-snapshot \
  --output reports/codespaces-demo "$@"
