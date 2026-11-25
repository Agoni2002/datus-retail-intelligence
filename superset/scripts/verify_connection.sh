#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
scripts/compose.sh exec -T superset /app/.venv/bin/python /app/retail/bootstrap/verify.py "$@"
