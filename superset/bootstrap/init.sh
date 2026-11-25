#!/usr/bin/env bash
set -euo pipefail
superset db upgrade
/app/.venv/bin/python /app/retail/bootstrap/admin.py
superset init
