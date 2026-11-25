# Phase 1B Retail Analyst

## Run

Use the existing editable Datus 0.4.3 checkout at `/home/userz/Projects/Datus-agent`, verified at commit `be4b714d385ad87968e867182db27281078a03a5`. The launchers use its existing Python and the companion project. The regular warehouse tests still use the companion virtual environment.

```bash
cd /home/userz/Projects/datus-retail-intelligence
export UV_CACHE_DIR="$PWD/.uv-cache"
uv run --locked pytest -q --basetemp data/processed/test-runs
bash agents/datus_smoke.sh data/processed/fixture
bash agents/evaluate_retail.sh
```

The evaluator defaults to the synthetic publication and rejects a different source dataset. Use `--quick` for a smoke subset and `--report <path>` to set the JSON output. The default report is `data/processed/retail-agent-evaluation.json`. The evaluation uses one local stdio subprocess for the pinned warehouse version. Each question has a fresh Datus session.

To run a genuine model, set `OPENAI_API_KEY` through your shell or secret manager. The launcher defaults to `gpt-4.1-mini`; override the model ID with `RETAIL_MODEL`. Provide only data that the configured provider is authorized to process.

```bash
bash agents/retail_analyst.sh "Which regions have the worst on-time delivery performance?"
bash agents/evaluate_retail.sh --live --report data/processed/retail-agent-live.json
```

Offline fixture evaluation substitutes the model transport. It runs the real Datus custom node, configured permission hooks, Agents SDK, MCP transport, Context Engine index, and guarded DuckDB. The fixture supplies the tool choices and gold SQL to isolate execution. Scores therefore verify integration, exact fixture outputs, and prescribed evidence and explanation checks. They do not measure a live model's ability to plan independently. Live evaluation uses strict golden provenance and column checks. A substantively equivalent alternative route or narrative may require review.

## Actual Datus integration

The companion launcher loads the installed Datus `GenSQLAgenticNode` as the configured custom alias `retail_analyst`. Its [node config](../configs/retail_analyst.yml) uses the local `agent.agentic_nodes` and `agent.services.mcp_servers` formats. The launcher prepares the declared [versioned Jinja prompt](../agents/prompts/retail_analyst_system_1.0.j2) in a temporary Datus home, selects `retail`, keeps the project overlay plugin allowlist empty, and pins one read-only versioned DuckDB file. This is the supported launch path for the restricted Retail Analyst. The standalone Datus connector smoke remains a trusted operator check.

The stdio MCP tool names are explicitly namespaced because this SDK installation leaves raw MCP names unchanged by default, while Datus's permission hook classifies names in the `mcp__server__tool` format. The Datus MCP server filter, explicit deny-by-default permission rules, read-only datasource, and a model-boundary check restrict the actual SDK tool surface to these three MCP-origin functions:

| Tool | Behavior |
| --- | --- |
| `mcp__retail__retail_context` | Retrieve bounded curated context using the local Datus LanceDB FTS backend. |
| `mcp__retail__retail_query` | Execute a single approved statement through `retail_agents.safe_query`. |
| `mcp__retail__retail_metric` | Use the same Dosi interpreter used by native AskMetrics in compile-only mode, then execute the compiled statement through the companion guard. |

Datus can mount hosted web search outside native tool permission filtering. The companion suppresses hosted web capability on this node's model and fails closed if any extra tool, missing tool, or non-MCP tool reaches the SDK. No native SQL, AskMetrics execution, shell, filesystem, hosted web, or delegation tool is on the model-facing surface. The project Skill remains guidance for operators. The analyst gets curated content only through MCP.

The Dosi tool accepts the Phase 1A semantic metric IDs for monthly delivered GMV and delivered order count. The YAML defines a single additive daily dataset and has no relationship declarations. Custom questions and the remaining metric dictionary entries use guarded published SQL. The guard supports Dosi's month truncation expression within its existing single-table, read-only contract. The evaluator reconciles ADS, semantic and independently aggregated daily guarded SQL at **BRL 0.005** absolute tolerance, with exact order-count equality.

## Context and audit

The versioned retail context index uses Datus's native LanceDB backend and full-text search API with bounded result sizes. It includes the five project business and warehouse documents, eleven canonical metric definitions, the benchmark questions and reference SQL, serving-table and column records from the pinned snapshot, and curated relationship facts. Expected benchmark values remain in the evaluator. The index is content-addressed and local, and requires no embedding service. It does not populate Datus's global/native AskMetrics Knowledge Base projection tables. The configured analyst uses the dedicated retail Context Engine index via MCP.

Runtime artifacts are Git-ignored. Tool audit JSONL files under `.datus-runtime/retail-analyst/audit/` record timestamps, tool identifiers, request IDs, allowed or denied decisions, durations, snapshot version, row counts, and error codes. They exclude SQL, prompt text, arguments, credentials, and result rows. The evaluator correlates streamed Datus actions with those audit events through request IDs. A successful RPC can carry a denial, so use the audit outcome and structured error for SQL-policy decisions. Datus session state is temporary, and external SDK tracing is disabled.

For investigation, the controlled fixture comparison attributes the change to measured volume and AOV effects and locates category and seller movements. The serving surface supports regional delivered-order and fulfillment comparisons. Regional GMV and causal explanations require more evidence and are outside this slice.

## Supply the full Olist extract

1. Obtain the [Brazilian E-Commerce Public Dataset by Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) through Kaggle and extract the original ZIP yourself.
2. Place all nine CSVs together in `data/raw/` or another private directory. Do not rename files. The expected names are the eight `olist_<table>_dataset.csv` files for orders, order items, customers, products, sellers, order payments, order reviews, and geolocation, plus `product_category_name_translation.csv`.
3. Run the inspector, ETL, independent reconciliation, publication, and resource measurement using one command.

```bash
bash agents/full_olist.sh /absolute/path/to/extracted/csvs
```

This writes the source profile and the publication manifest under `data/processed/olist/`. The run's JSON quality report includes independent KPI reconciliation. A blocking finding leaves the last accepted version available. Start an authorized analyst session against that version with `bash agents/retail_analyst.sh --output data/processed/olist "Show monthly delivered GMV"`. Airflow and Superset remain separate deployment work. [Deployment plan](implementation_roadmap.md)
