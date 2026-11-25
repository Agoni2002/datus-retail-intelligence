# Phase 1B deployment plan

## Airflow

Provision Airflow in a separate environment, and let its task runner call the companion environment through its existing launcher. Proposed task dependencies:

```text
wait_for_completed_extract → inspect_source_contract → build_validate_publish → verify_published_snapshot
                                                        ↘ issue_reconciliation_report
```

Use a ready marker or upstream handoff on complete extracts. Start with a manual trigger for the static Olist download. For a recurring feed, use a daily run after its agreed arrival window, with `catchup=False`, `max_active_runs=1`, and one writer pool slot. Keep build, reconciliation and publication together in the existing pipeline transaction. The publish step is the final internal action of `build_validate_publish`. Verify its output with the versioned manifest and a guarded KPI query before announcing the release.

Retry transient file or infrastructure failures twice with a five-minute initial delay and backoff. Route deterministic quality failures directly to operator review with the JSON report version. Retries use the last good manifest and hash state. The same accepted extract returns the previously published snapshot.

The upstream Airflow Compose quickstart budgets at least **4 GB** to Docker and prefers **8 GB**. Treat that as a capacity limit for this VM. Validate a small single-worker setup in isolation and observe peak memory before running it with other services. [Airflow Compose requirements](https://airflow.apache.org/docs/apache-airflow/stable/howto/docker-compose/)

## Superset

Use a separate Superset environment and install `duckdb-engine` there in Phase 1B. Keep the Superset application metadata store separate from the analytics file. Mount published analytics files read-only at `/warehouse/snapshots/`. Configure a versioned path such as `duckdb:////warehouse/snapshots/<version>.duckdb`, with the following starting engine settings in the database connection Extra JSON. Verify them against the chosen Superset and driver versions.

```json
{
  "engine_params": {
    "connect_args": {
      "read_only": true,
      "config": {"enable_external_access": "false", "memory_limit": "256MB", "threads": "1"}
    }
  }
}
```

Use approved ADS marts for dashboard datasets. Keep SQL Lab and upload access disabled for dashboard-only roles, and isolate raw and identity-bearing data if a BI role will have arbitrary SQL access. Advance the connection to the new immutable version after successful publication, then refresh connection pools and dashboard caches. Keep the previous path available during rollover and compare a fixed KPI in DuckDB, Dosi, and Superset.

Reserve an initial **1.5–2 GiB** for a minimal prebuilt Superset app plus metadata store as a planning budget. This is unmeasured on the VM. Measure worker RSS and DuckDB query memory during Phase 1B. Avoid the development frontend build on this host. [Superset DuckDB setup](https://superset.apache.org/user-docs/databases/supported/duckdb/) · [Superset Compose options](https://superset.apache.org/admin-docs/installation/docker-compose/)

## Acceptance for Phase 1B

1. Validate an original full Olist extract and document remediation of source exceptions, observed peak memory, and snapshot sizes.
2. Run and retry the DAG against a published version while a read-only consumer holds the previous version.
3. Publish the fulfillment dashboard and reconcile independent warehouse SQL, Dosi, and Superset.
4. Connect the guarded SQL tool to a scoped Retail Analyst Subagent and exercise all exposed routes before accepting untrusted prompts.
