#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"
python3 -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ required"'
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
if [[ ! -f .env ]]; then
  cp .env.example .env
  chmod 600 .env
fi
bash scripts/codespaces-demo.sh
echo "Setup selesai. Ulangi demo: bash scripts/codespaces-demo.sh"
echo "Riset lengkap: .venv/bin/python scripts/research_regime.py --output reports/regime"
