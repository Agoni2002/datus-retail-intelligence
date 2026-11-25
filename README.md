# Datus Retail Intelligence

A portfolio application for analyzing the Brazilian Olist marketplace. It combines a reproducible DuckDB warehouse, six interactive Superset dashboards, and a Datus Retail Analyst that runs governed analytical queries through MCP.

## Architecture

```text
Olist CSVs → ODS → DWD → DWS → ADS → immutable DuckDB publication
                                      ├─ Superset + PostgreSQL metadata
                                      └─ Datus Agent → Agents SDK → stdio MCP → SQL Guard
Cloudflare HTTPS → Caddy → React / FastAPI → approved Superset embeds and analytical APIs
```

React and TypeScript with Vite provide the public interface. FastAPI serves approved aggregates and short-lived, dashboard-scoped Superset guest tokens. PostgreSQL stores Superset metadata on its internal network. See the [public demo runbook](docs/public_demo.md) for the active endpoint and local deployment procedure.

The [SQL Guard](docs/retail_analyst.md) restricts the MCP surface to permitted queries against the current immutable warehouse. The public API accepts natural-language questions only. Live inference is available only with configured provider credentials, model pricing, and usage limits.

## Dashboards

| Dashboard | Focus |
| --- | --- |
| Executive Overview | GMV, orders, order value, cancellation, delivery and reviews |
| Product & Category | Category ranking, market contribution and sales trends |
| Seller Performance | Seller order participation, delivered value, freight and cancellation |
| Delivery & Fulfillment | Delivery eligibility, lateness and regional performance |
| Customer & Review | Same-month repeat purchase, basket bands and review scores |
| Data Quality & Governance | Validation results, warehouse counts and coverage gaps |

The verified full Olist run processed 1,550,922 source rows in 45.07 seconds on the project VM and produced a 183.76 MiB DuckDB snapshot. Validation recorded 132 checks, 0 blockers and 5 warnings. Late extract months have sparse coverage, and timestamps, payment reconciliation and geography have documented limitations. See the [warehouse quality notes](docs/data_quality.md) and [BI runbook](docs/superset_bi.md).

Original Olist CSVs, generated databases, credentials and local verification artifacts are excluded from this repository.

## Run on the synthetic data

Requires Python 3.12 and uv. All commands run from this repository.

```bash
cd /home/userz/Projects/datus-retail-intelligence
export UV_CACHE_DIR="$PWD/.uv-cache"
uv sync --locked --python /usr/bin/python3
uv run --locked python -m ingestion.schema_inspector data/fixtures/olist
uv run --locked python -m etl.pipeline --source data/fixtures/olist --output data/processed/fixture
uv run --locked python -m retail_agents.safe_query --output data/processed/fixture \
  "SELECT month_start, delivered_gmv_brl, on_time_delivery_rate FROM ads.ads_executive_dashboard ORDER BY month_start"
uv run --locked pytest -q --basetemp data/processed/test-runs
bash agents/datus_smoke.sh data/processed/fixture
```

The smoke test uses the existing Datus checkout and virtual environment at the path recorded in [Datus integration](agents/README.md). The warehouse and automated fixture tests can run independently.

January fixture results include **BRL 200 delivered GMV**, **3 delivered orders**, **25% cancellation**, and **50% on-time delivery** across 2 eligible orders. February GMV is **BRL 80**, with category movements of **−BRL 90 home** and **−BRL 30 electronics**. The [16 benchmark questions](benchmark/questions.yml) contain expected SQL and fixture results.

## Run on Olist files

Obtain the nine original, unmodified CSVs from Olist’s [Brazilian E-Commerce Public Dataset](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) and extract them into a directory of your choice. Olist and its dataset collaborators publish the source under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/). The repo includes an independently authored synthetic fixture. Raw extracts and generated databases are Git-ignored.

```bash
uv run --locked python -m ingestion.schema_inspector /absolute/path/to/olist-csvs
uv run --locked python -m etl.pipeline --source /absolute/path/to/olist-csvs --output data/processed/olist
```

The CLI expects a **complete extract**, including headers for empty relations. `OLIST_SOURCE_DIR` and `RETAIL_OUTPUT_DIR` can be set in the shell as defaults. Freshness, alert and reconciliation thresholds are in [warehouse.yml](configs/warehouse.yml). Successful runs report the version, database, and quality report path. See [Architecture](docs/architecture.md) for recovery and incremental semantics.

## Phase 1B Retail Analyst

Run the Datus-powered fixture evaluation with `bash agents/evaluate_retail.sh`. A live analyst session requires model credentials. See [Retail Analyst runbook](docs/retail_analyst.md) for both paths and the machine-readable evaluation report.

## Repository guide

- [Business requirements](docs/business_requirements.md) and [metric dictionary](docs/metric_dictionary.md)
- [Dimensional model](docs/dimensional_model.md) and [data dictionary](docs/data_dictionary.md)
- [Quality and reconciliation](docs/data_quality.md)
- [Datus, Dosi, and guarded SQL](agents/README.md)
- [Phase 1B integration plan](docs/implementation_roadmap.md)
