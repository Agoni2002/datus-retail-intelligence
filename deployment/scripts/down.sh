#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
docker compose -f deployment/compose.yml down
systemctl --user stop retail-public-api.service 2>/dev/null || true
