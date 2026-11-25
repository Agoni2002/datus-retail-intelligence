# Superset retail business intelligence

Phase 1D-A serves six native Apache Superset dashboards from the same published Olist snapshot as Datus. Superset runs as a local Docker Compose service. PostgreSQL stores users, datasets, chart definitions and dashboard metadata in the persistent `retail-superset_metadata` volume. Dashboard queries run synchronously through SQLAlchemy and DuckDB.

## Start, verify and stop

Run these commands from the retail repository root. Setup requires Docker with the Compose plugin and host Python 3.11 or newer.

```bash
cd /home/userz/Projects/datus-retail-intelligence
./superset/scripts/up.sh
./superset/scripts/status.sh
./superset/scripts/verify_connection.sh
./superset/scripts/down.sh
```

Open [Superset on the Ubuntu VM](http://127.0.0.1:8088/). On first startup, setup creates `superset/.env` with mode 0600 and random secrets. Sign in with `SUPERSET_ADMIN_USERNAME` and `SUPERSET_ADMIN_PASSWORD` from that file. Keep the file alongside the PostgreSQL volume across restarts. The first PostgreSQL initialization uses its configured password, and subsequent starts use the same stored credentials. Shutdown preserves the volume. Restart with `up.sh`. The provisioning script reapplies the repository definitions to the managed dashboards.

For access from another machine, connect through the VM's SSH service and open the same browser URL locally. Change the local forwarding port if it is already in use.

```bash
ssh -N -L 8088:127.0.0.1:8088 your-user@ubuntu-vm
```

## Runtime and warehouse connection

| Component | Version or setting |
| --- | --- |
| Apache Superset base | `apache/superset:6.0.0`, registry digest `sha256:6f6c9982bd64d81797bd4f33834f2ce4a4653c8ac8322f1e5f9df9b0332d092a` |
| Project image | `retail-superset:6.0.0-duckdb1.5.2` |
| PostgreSQL metadata | `postgres:16.11-alpine`, registry digest `sha256:4327b9fd295502f326f44153a1045a7170ddbfffed1c3829798328556cfd09e2` |
| DuckDB / SQLAlchemy dialect | DuckDB 1.5.2 and duckdb-engine 0.17.0 |
| PostgreSQL driver | psycopg2-binary 2.9.11 |
| Network | Superset host bind `127.0.0.1:8088`, PostgreSQL on the Compose network |
| Superset | One Gunicorn worker with four threads, 1.5 GiB RAM, two CPU cores, 60-second Gunicorn timeout and 45-second Superset web and SQL Lab timeout settings |
| PostgreSQL | 512 MiB RAM, 64 MB shared buffers and 30 configured connections |
| DuckDB | One thread, 256 MB memory setting per connection, external access disabled |
| Results | Synchronous chart requests, per-chart row limits of 2 to 2,500, global chart default 5,000 |
| SQLAlchemy | 1.4.54, supplied by the pinned Superset base |

Setup reads `data/processed/olist/latest.json`, verifies the named quality report and immutable file, and copies publication metadata plus the computed SHA-256 into the ignored `superset/.runtime/snapshot.json` receipt. Compose bind-mounts the snapshot directory read-only at `/warehouse/snapshots`. The registered SQLAlchemy URI uses the absolute-file form `duckdb:////warehouse/snapshots/<version>.duckdb`, with `read_only=True` in SQLAlchemy `connect_args`. File upload, SQL Lab exposure, DML and table or view creation are disabled for this registered database.

| Publication | Verified value |
| --- | --- |
| Snapshot version | `20261125T082335510967Z-d82ffee2` |
| Published file | `data/processed/olist/snapshots/20261125T082335510967Z-d82ffee2.duckdb` |
| SHA-256 | `3e56b48cb40cb61eca8c8fc4761ab3138a3b8f1fc33e6c130fba43795f37b590` |
| Publication time | 2026-11-25 08:24:12 UTC, from the atomically written manifest's modification time |

After Phase 1C publishes a new validated snapshot, refresh from the repository root and run the connection verification. Reapply during a maintenance window so viewers see a consistent set of dashboard panels.

```bash
python3 superset/bootstrap/pin_snapshot.py
./superset/scripts/import_dashboards.sh
./superset/scripts/compose.sh restart superset
./superset/scripts/compose.sh up -d --wait superset
./superset/scripts/verify_connection.sh
```

## Dashboards and source fields

The purchase date filter operates on `month_start` for all charts. Use month boundaries for complete monthly buckets. Chart descriptions and dashboard notes show grain and filter scope.

| Dashboard | Charts | Published relations and fields | Additional filters |
| --- | ---: | --- | --- |
| [E-Commerce Executive Overview](http://127.0.0.1:8088/superset/dashboard/retail-executive/) | 12 | `ads.ads_executive_dashboard` supplies order counts, GMV, freight and delivery denominators. `dws.dws_sales_daily.review_score_sum` and `dws.dws_delivery_performance.late_days_sum` supply additive numerators. Regional GMV uses delivered `dwd.fact_order.merchandise_brl` and `dwd.dim_customer.state`. | Category scopes to Top 10. State scopes to sales distribution and delivery performance. |
| [Product & Category Analytics](http://127.0.0.1:8088/superset/dashboard/retail-category/) | 6 | `dws.dws_category_performance` groups `category_sales_brl`, `delivered_orders` and `delivered_items` by `category_name` and month. Contribution divides selected category GMV by the selected total. Orders may include multiple categories. | Category scopes to all six charts. |
| [Seller Performance Analytics](http://127.0.0.1:8088/superset/dashboard/retail-seller/) | 6 | `ads.ads_seller_scorecard` provides `seller_id`, `seller_orders`, `canceled_orders`, `delivered_orders`, `delivered_gmv_brl` and `freight_revenue_brl`. Delivery uses distinct `seller_id, order_id` pairs in `dwd.fact_order_item` joined to order eligibility and outcomes. | Seller ID scopes to all six charts. |
| [Delivery & Fulfillment Analytics](http://127.0.0.1:8088/superset/dashboard/retail-fulfillment/) | 7 | `dws.dws_delivery_performance` provides state and counts for delivered, eligible, on-time, late and excluded orders plus `late_days_sum`. Average duration uses eligible `dwd.fact_order.purchased_at` and `delivered_at`. `ads.ads_delivery_alerts` supplies flagged state-months. | Customer state scopes to all seven charts. |
| [Customer & Review Analytics](http://127.0.0.1:8088/superset/dashboard/retail-customer/) | 6 | `dws.dws_customer_retention` supplies delivered orders per customer-month. ADS repeat and delivered customer counts drive repeat share. DWS review numerators drive the review trend. Fact-order merchandise and latest review score supply the basket and score distributions. State geography counts distinct delivered customers within each state-month. | Customer state scopes to the geography chart. |
| [Data Quality & Governance](http://127.0.0.1:8088/superset/dashboard/retail-quality/) | 1 | ADS coverage chart uses `orders`, `delivered_orders` and `reviewed_orders`. Read-only provisioning derives text panels from the publication, Phase 1C quality report, layer counts and narrowly scoped fallback queries. | Purchase month scopes to the live chart. Text panels summarize the publication. |

### Metric and data coverage details

- GMV is delivered merchandise in BRL. Freight is shown separately. AOV divides delivered GMV by delivered orders.
- Cancellation rate divides canceled orders by all observed orders. Seller cancellation uses distinct seller-order participations and the same status rule. Across sellers, counts can overlap.
- On-time rate uses eligible delivered records. Average late days uses only late eligible orders. The fulfillment table and trend show delivered, eligible, late and excluded orders separately.
- Average review score uses the latest qualifying review per delivered order. Monthly Same-Month Repeat Customer Share divides delivered customer-months with at least two delivered orders by all delivered customer-months.
- The report records 1,550,922 source rows, 132 checks, 0 blockers and 5 warnings. Geography and translation limitations are 261,831 exact duplicate geolocation rows, 278 customers and 7 sellers without geographic matches, and 13 products without a category translation.
- There are 189 delivery timestamp anomalies affecting 188 delivered orders and one shipped order. Another eight delivered orders lack an actual timestamp. In total, 196 delivered orders fall outside the on-time denominator.
- Payment reconciliation flagged 264 delivered orders. One lacks a payment record and 263 differ by more than BRL 0.02.
- Latest review date was 2018-08-31, 47 days before the latest purchase. September and October 2018 contain only 20 orders and zero delivered orders. All dashboards label sparse extract coverage.
- Customer geography is at state level. Each state-month counts distinct customers, and the same customer can contribute to multiple months or states. The repository definitions own provisioned assets, so reimport can replace edits made through the UI.

## Operational verification

`verify_connection.sh` signs in to the live Superset API and checks the registered source settings. It attempts a DDL write through Superset's own read-only engine, requests data for every managed chart, reconciles nine KPIs with Phase 1C, compares filtered API queries with direct warehouse SQL, verifies the governance panels, and checks the snapshot hash again. The deployment does not require access to an LLM.

During concurrent browser and chart checks, a Docker sample showed 444 MiB for Superset and 104 MiB for PostgreSQL. PostgreSQL reached 149 MiB in a separate provisioning sample. The Compose memory caps are 1.5 GiB and 512 MiB respectively.

[Superset Docker releases](https://superset.apache.org/docs/6.0.0/installation/docker-builds/) · [Database connectivity](https://superset.apache.org/docs/6.0.0/configuration/databases/) · [Configuration](https://superset.apache.org/docs/6.0.0/configuration/configuring-superset/) · [Superset REST API](https://superset.apache.org/developer-docs/api/)
