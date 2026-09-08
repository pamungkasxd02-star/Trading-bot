#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
exec .venv/bin/python -m spotlab --config config/all-scalping-demo.yaml demo-run "$@"
