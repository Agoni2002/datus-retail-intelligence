#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONDONTWRITEBYTECODE=1
datus=/home/userz/Projects/Datus-agent/.venv/bin/datus
"$datus" --version
/home/userz/Projects/Datus-agent/.venv/bin/python -B -m retail_agents.datus_smoke "${1:-data/processed/fixture}"
