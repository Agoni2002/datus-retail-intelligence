# Local Superset deployment

From the retail repository root, run `./superset/scripts/up.sh`, then open [Superset](http://127.0.0.1:8088/). The first startup creates `superset/.env` with generated local credentials. Use the administrator username and password from that file. Docker Compose and Python 3.11 or newer are required.

- `./superset/scripts/status.sh` shows container health and port binding.
- `./superset/scripts/verify_connection.sh` verifies the live deployment against the published snapshot.
- `./superset/scripts/import_dashboards.sh` reapplies the dashboard and dataset definitions.
- `./superset/scripts/down.sh` stops the services and preserves the metadata volume.

See the [BI runbook](../docs/superset_bi.md) for dashboard links, metric definitions, SSH forwarding and snapshot refresh.
