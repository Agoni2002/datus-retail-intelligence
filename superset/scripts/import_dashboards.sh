#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
receipt="$(mktemp .runtime/provision.XXXXXX)"
trap 'rm -f -- "$receipt"' EXIT
scripts/compose.sh exec -T superset /app/.venv/bin/python /app/retail/bootstrap/provision.py >"$receipt"
python3 -m json.tool "$receipt" >/dev/null
chmod 644 "$receipt"
mv -- "$receipt" .runtime/provision.json
python3 - <<'PY'
import json
from pathlib import Path
data=json.loads(Path(".runtime/provision.json").read_text())
for dash in data["dashboards"].values():
    print(dash["title"], dash["path"], len(dash["charts"]), "charts")
PY
