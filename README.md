# Datus Retail Data Intelligence

A DuckDB warehouse for sales and fulfillment analysis over the Olist e-commerce extract. Phase 1A includes a synthetic warehouse, deterministic quality gates, incremental source refresh, immutable publication, a guarded query interface, and a Datus datasource smoke test.

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

## Repository guide

- [Business requirements](docs/business_requirements.md) and [metric dictionary](docs/metric_dictionary.md)
- [Dimensional model](docs/dimensional_model.md) and [data dictionary](docs/data_dictionary.md)
- [Quality and reconciliation](docs/data_quality.md)
- [Datus, Dosi, and guarded SQL](agents/README.md)
- [Phase 1B integration plan](docs/implementation_roadmap.md)
