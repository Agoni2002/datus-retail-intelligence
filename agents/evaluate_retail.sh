#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONDONTWRITEBYTECODE=1
export OPENAI_AGENTS_DISABLE_TRACING=1
exec /home/userz/Projects/Datus-agent/.venv/bin/python -B -m retail_agents.evaluate "$@"
