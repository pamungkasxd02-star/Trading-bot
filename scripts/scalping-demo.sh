#!/usr/bin/env bash
set -euo pipefail
umask 077
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"
exec .venv/bin/python -m spotlab --config config/scalping-demo.yaml demo-run "$@"
