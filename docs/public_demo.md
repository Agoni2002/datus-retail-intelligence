# Public interview demo

The demo presents Olist overview metrics, six live Superset dashboards, the guarded analyst status, quality findings, and snapshot and metric documentation. The verification run used [this temporary HTTPS endpoint](https://watches-turbo-empire-vegetable.trycloudflare.com). The current public URL is recorded in `deployment/.runtime/origin` and in the ignored deployment status JSON. This deployment uses Cloudflare Quick Tunnel. Cloudflare assigns a temporary hostname when the connector starts.

## Start and stop

Requires the validated Olist publication, Docker with Compose, a systemd user session, uv, Node.js 18.19 or newer, npm, and ripgrep. Run from the repository root.

```bash
./deployment/scripts/up.sh
curl --fail "$(cat deployment/.runtime/origin)/api/health"
./deployment/scripts/down.sh
```

The startup script builds the production React assets, starts the existing Superset deployment, starts Caddy and the tunnel, and provisions six embedded dashboards for the active HTTPS origin. Caddy and cloudflared have Docker restart policies. FastAPI uses a detached, restartable systemd user service. The running VM and user systemd manager must remain available. To refresh the hostname after a Quick Tunnel restart, run `./deployment/scripts/refresh-origin.sh`. Stopping the demo retains the Superset containers, metadata, snapshot, and local evidence.

```bash
systemctl --user status retail-public-api
docker compose -f deployment/compose.yml ps
docker compose -f deployment/compose.yml logs --tail=20 tunnel
./superset/scripts/status.sh
./superset/scripts/verify_connection.sh
./deployment/.runtime/venv/bin/python -B -m web.backend.verify
```

## Public boundary

Cloudflare terminates TLS and sends outbound tunnel traffic to Caddy on loopback. Caddy serves only built frontend assets, approved API routes and the narrowly scoped Superset embed gateway. Superset and FastAPI listen on loopback. PostgreSQL has no published host port. The warehouse directory is mounted read-only by Superset, and the public gateway has no data filesystem mount.

The independent `retail_demo` identity has only `RetailDemoRole`. It has no SQL Lab, data management, dataset editing, dashboard editing, or user management grants. Embedded guests inherit the same limited role and obtain query access via the dashboard's approved charts and filters. The server discovers actual embedded UUIDs from Superset. Each signed guest token lasts 180 seconds and authorizes one UUID. The exact public origin is configured in Superset and checked at the gateway. The gateway does not relay browser authentication cookies or administrative sessions to Superset. Superset login and administration routes are outside the public route allowlist.

FastAPI has no docs, ReDoc or OpenAPI routes. It checks origin, validates JSON bodies and request scopes, limits sizes and timeouts, and emits generic errors. The public API serves aggregates and publication metadata. Raw CSVs and DuckDB files are outside the web root.

## Analyst controls

Live AI defaults to disabled and chat returns 503 when provider configuration is unavailable. No scripted responses are sent to the browser. To configure live service, supply the provider credential and current model pricing in the optional, ignored `deployment/.env` systemd environment file. The example lists the configuration keys. Keep the file private. The Datus checkout stays separate.

The server enforces a persistent UTC daily spending ledger, five requests per IP per minute, 20 requests per IP and per visitor per day, 50 requests globally per day, a 4,000-character question, a 1,000-token output budget per turn, one concurrent live request, and a 60-second ceiling. The per-request reservation must fit the configured daily budget. A timed-out or unmetered request retains its reservation. Cloudflare supplies the client address to the loopback gateway, which overwrites the application's private address header. A live answer must have evidence from the existing Agents SDK → stdio MCP → SQL Guard path.

## Snapshot and operational evidence

The current publication is `20261125T082335510967Z-d82ffee2` with SHA-256 `3e56b48cb40cb61eca8c8fc4761ab3138a3b8f1fc33e6c130fba43795f37b590`. Publication facts and warehouse layer counts are computed from this snapshot and its original quality report. See the [BI runbook](superset_bi.md) for metric definitions and source coverage.

The public source repository is [Agoni2002/datus-retail-intelligence](https://github.com/Agoni2002/datus-retail-intelligence). The local deployment status records the active hostname, last verification, source publication, GitHub push and measured process/container memory. One startup verification sample showed 196.3 MiB for Superset, 23.4 MiB for PostgreSQL, 16.69 MiB for Caddy, 21.64 MiB for cloudflared, and approximately 40.5 MiB for FastAPI. The Quick Tunnel does not guarantee a persistent hostname or availability when the VM is offline. See [Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/) and [Superset embedding](https://superset.apache.org/user-docs/using-superset/embedding/).
