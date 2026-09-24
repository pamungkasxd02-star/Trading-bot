#!/usr/bin/env bash
set -euo pipefail
umask 077
cd "$(dirname "$0")/.."
exec .venv/bin/python -m spotlab --config config/candle-study.yaml demo-run "$@"
