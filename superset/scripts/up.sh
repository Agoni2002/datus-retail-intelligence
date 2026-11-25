#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 bootstrap/pin_snapshot.py
scripts/compose.sh build superset
scripts/compose.sh up -d --wait metadata
scripts/compose.sh run --rm --no-deps superset bash /app/retail/bootstrap/init.sh
scripts/compose.sh up -d --wait superset
scripts/import_dashboards.sh
