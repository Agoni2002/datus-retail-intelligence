#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
umask 077
runtime=deployment/.runtime
mkdir -p "$runtime" superset/.runtime
if [[ ! -s superset/.runtime/demo-signing-key ]]; then
    python3 -c 'import secrets; print(secrets.token_urlsafe(48))' > superset/.runtime/demo-signing-key
fi
uv venv --allow-existing "$runtime/venv"
uv pip install --python "$runtime/venv/bin/python" -r web/backend/requirements.txt
npm --prefix web/frontend ci --no-audit --no-fund
npm --prefix web/frontend run build
if [[ ! -s superset/.runtime/provision.json ]]; then
    ./superset/scripts/up.sh
else
    ./superset/scripts/compose.sh up -d --wait metadata superset
    ./superset/scripts/compose.sh restart superset
    ./superset/scripts/compose.sh up -d --wait superset
fi
docker compose -f deployment/compose.yml up -d
./deployment/scripts/refresh-origin.sh
systemctl --user stop retail-public-api.service 2>/dev/null || true
systemd-run --user --unit=retail-public-api --property=Restart=on-failure \
    --property=UMask=0077 --property=MemoryMax=1200M --working-directory="$PWD" \
    --property="EnvironmentFile=-$PWD/deployment/.env" \
    "$PWD/$runtime/venv/bin/python" -B -m uvicorn web.backend.app:APP \
    --host 127.0.0.1 --port 8091 --no-access-log --no-proxy-headers --limit-concurrency 32
printf 'Demo URL %s\n' "$(cat "$runtime/origin")"
