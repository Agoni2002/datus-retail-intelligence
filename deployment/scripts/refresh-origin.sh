#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
umask 077
runtime=deployment/.runtime
mkdir -p "$runtime"
container=$(docker compose -f deployment/compose.yml ps -q tunnel)
started=$(docker inspect --format '{{.State.StartedAt}}' "$container")
for attempt in {1..35}; do
    docker logs --since "$started" "$container" > "$runtime/tunnel.log" 2>&1
    origin=$(rg -o 'https://[a-z][a-z0-9-]+\.trycloudflare\.com' "$runtime/tunnel.log" | tail -1 || true)
    if [[ -n "$origin" ]]; then
        break
    fi
    sleep 2
done
[[ -n "$origin" ]] || { printf '%s\n' 'Quick Tunnel URL unavailable' >&2; exit 1; }
receipt=$(mktemp "$runtime/public-data.XXXXXXXX")
trap 'rm -f -- "$receipt"' EXIT
./superset/scripts/compose.sh exec -T superset /app/.venv/bin/python /app/retail/bootstrap/public_demo.py "$origin" > "$receipt"
python3 -m json.tool "$receipt" > /dev/null
mv -- "$receipt" "$runtime/public-data.json"
printf '%s\n' "$origin" > "$runtime/origin.new"
mv -- "$runtime/origin.new" "$runtime/origin"
