# Retail integration with Datus 0.4.3

This companion uses the editable Datus checkout at `/home/userz/Projects/Datus-agent`, commit `be4b714d385ad87968e867182db27281078a03a5`. Its CLI and configuration were inspected before integration. Datus dependencies stay in the existing virtual environment. The project guard runs in the retail virtual environment.

## Datasource and verification

[The base configuration](../configs/datus.example.yml) uses `agent.services.datasources.retail`, a local project runtime home, a selected schema, a native read-only DuckDB connection, and external access disabled. The tracked [project overlay](../.datus/config.yml) selects the datasource and uses an empty plugin allowlist for this phase. Agent datasource and Subagent definitions belong in the base config. Supply LLM configuration separately in an ignored `configs/datus.local.yml` only when interactive model use is needed. Start from the example and add the provider settings supported by the existing checkout. Keep credentials in environment references.

```bash
cd /home/userz/Projects/datus-retail-intelligence
bash agents/datus_smoke.sh data/processed/fixture
```

The smoke uses the absolute Datus CLI for the version check and its existing Python environment for the no-LLM datasource check. It resolves the approved published version from the manifest, loads Datus's actual configuration, reads ADS, confirms rejection of a persistent write, reproduces the legacy guard mismatch, verifies the local Skill discovery path, validates the example Dosi YAML, and compares two Dosi-compiled monthly metrics with the ADS values.

For a manual trusted operator session, pin a single publication as follows. For actual chat, use a configured provider in `configs/datus.local.yml`.

```bash
export RETAIL_DUCKDB_PATH="$(.venv/bin/python - <<'PY'
from pathlib import Path
from etl.snapshot import Snapshots
state = Snapshots(Path("data/processed/fixture"))
print(state.directory / state.latest()["database"])
PY
)"
/home/userz/Projects/Datus-agent/.venv/bin/datus --config configs/datus.local.yml --datasource retail
```

On a new publication, update the environment value and restart the session to pick up the version. A Datus connection with access to this full DuckDB file can read any warehouse schema available to DuckDB. Use the project query entry point for untrusted SQL.

## Dosi, Context Engine, Skills, and Subagents

[The example model](semantic/retail_fulfillment.yml) has the delivered GMV and delivered-order-count metrics at purchase-date grain. Both are additive across purchase dates. For Datus Knowledge Base registration, place it at `subject/semantic_models/retail/retail_fulfillment.yml` and run the existing batch CLI with the version pinned above.

```bash
mkdir -p subject/semantic_models/retail
cp agents/semantic/retail_fulfillment.yml subject/semantic_models/retail/
/home/userz/Projects/Datus-agent/.venv/bin/datus-agent bootstrap-kb \
  --config configs/datus.example.yml --datasource retail \
  --components semantic_model --kb_update_strategy sync-yaml
```

This commit documents `sync-yaml` for republishing the metric and semantic dataset projections without generating a new model. For the first metadata index on a curated serving datasource, set `kb.search.mode: fts` in the base config and run the existing batch CLI with `--components metadata --kb_update_strategy overwrite`. The later refresh strategy is `incremental`. The `--kb_search_mode fts` flag overrides the mode for one invocation. Review descriptions, sampled values, and reference SQL before indexing. Vector mode needs an embedding runtime. Knowledge Base synchronization and indexing are prepared here for Phase 1B. The Phase 1A smoke exercises schema validation, compile and execution directly.

[The project Skill](../.datus/skills/retail-metrics/SKILL.md) defines the business usage guidance. For a later custom analyst use the `/agent` or `/subagent` wizard and a `gen_sql` style with scoped tables/metrics/reference SQL. Select the guarded MCP tool once it is registered. With that configuration, use the tool's scope as an additional routing filter and reserve the base connector for trusted execution. Subagent context filters and prompt guidance are not an authorization boundary. The release provides the local SQL interface for wrapping in an MCP tool and leaves the actual Subagent registration to Phase 1B. The name and tool below are planned identifiers to use after the MCP tool exists.

```yaml
agent:
  agentic_nodes:
    retail_analyst:
      system_prompt: retail_analyst
      node_class: gen_sql
      prompt_version: "1.0"
      agent_description: Answer reviewed Olist fulfillment and sales questions.
      tools: context_search_tools.list_subject_tree
      mcp: retail_query.query
      scoped_context:
        datasource: retail
        tables: ads.ads_executive_dashboard, ads.ads_seller_scorecard
```

Use the wizard to create the corresponding `retail_analyst_system_1.0.j2` prompt and confirm that the runtime presents only the intended tools.

## SQL safety and the Datus compatibility issue

The pinned DuckDB 1.5.2 text plan reports cardinality as `~10,000 rows` for the regression probe. Datus at the audited commit only matches `EC: N` for DuckDB, returns `None` for this output, and fails open on unknown estimates in the artifact guard.

The project interface at `retail_agents.safe_query` is a standalone, testable enforcement point. It accepts exactly one supported SELECT against one explicitly permitted schema-qualified serving table. It denies writes, external/table functions, nested queries, CTEs, joins, raw tables and retention identifiers. It re-serializes a restricted SQLGlot AST and independently checks the engine statement type. It uses a read-only connection with external access off.

Only known physical JSON plan shapes are accepted. Both base-table row estimates from DuckDB metadata and operator estimates have a one-million-row cap. A planner compatibility mismatch declines the query. Default limits are 8 KiB of SQL, 300 AST nodes, 500 result rows, 256,000 output bytes, a five-second planning/execution deadline, one engine thread and a 256 MB DuckDB memory setting. DuckDB's interrupt is cooperative and memory settings do not bound total process RSS. The guard assumes a trusted warehouse published by this pipeline. It is not a general-purpose database sandbox.

```bash
uv run --locked python -m retail_agents.safe_query --output data/processed/fixture \
  "SELECT month_start, delivered_gmv_brl FROM ads.ads_executive_dashboard ORDER BY month_start"
```

Datus supports a registered plugin `policy_runtime` for applicable SQL reads, and `tool_transformers` for LLM-driven calls. A transformer alone does not cover direct Python or other execution paths. No plugin is installed or activated in Phase 1A. Before serving untrusted agents, expose only the guarded tool and test for access through native SQL, filesystem, shell, and Dosi routes. If native artifact queries must have the same cost guarantee, a separate Datus change should use supported DuckDB JSON `EXPLAIN` fields, handle unknown plans according to explicit policy, and add tests with the pinned engine and actual guarded call sites.
