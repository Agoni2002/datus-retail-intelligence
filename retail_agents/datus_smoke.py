"""Smoke-test this checkout through the existing Datus Python environment."""

import json
import os
import sys
from pathlib import Path

import dosi_engine
import duckdb

from datus.configuration.agent_config_loader import load_agent_config
from datus.tools.db_tools.db_manager import DBManager
from datus.tools.semantic_tools.dosi.authoring import validate_dosi_document
from datus.tools.sql_guard import estimate_rows_from_explain
from datus.tools.skill_tools.skill_config import SkillConfig

from etl.snapshot import Snapshots


def smoke(output: Path):
    snapshots = Snapshots(output)
    state = snapshots.latest()
    if state is None:
        raise SystemExit("Publish a warehouse snapshot first")
    os.environ["RETAIL_DUCKDB_PATH"] = str(snapshots.directory / state["database"])
    config = load_agent_config(config="configs/datus.example.yml")
    manager = DBManager(config.datasource_configs)
    connector = manager.get_conn("retail")
    try:
        if not connector.read_only or connector.enable_external_access:
            raise RuntimeError("Unexpected datasource security settings")
        select = connector.execute_query(
            "SELECT count(*) AS months FROM ads.ads_executive_dashboard", result_format="list",
        )
        if not select.success or not select.sql_return:
            raise RuntimeError("Read-only ADS query failed")
        plan = connector.execute_query("EXPLAIN SELECT sum(i) FROM range(10000) t(i)", result_format="list")
        if not plan.success or "~10,000 rows" not in str(plan.sql_return):
            raise RuntimeError("Expected DuckDB 1.5.2 plan formatting was absent")
        legacy_estimate = estimate_rows_from_explain("duckdb", plan.sql_return)
        if legacy_estimate is not None:
            raise RuntimeError("Datus EXPLAIN behavior changed; recheck compatibility notes")
        with connector.exclusive_connection() as conn:
            # TEMP DDL would be writable even on a read-only database. Use a
            # zero-row persistent write so unexpected behavior changes no rows.
            try:
                conn.execute("DELETE FROM ads.ads_executive_dashboard WHERE false")
            except duckdb.Error as error:
                if "read-only" not in str(error).lower():
                    raise
            else:
                raise RuntimeError("Datus datasource permitted a persistent write")
        model = Path("agents/semantic/retail_fulfillment.yml").resolve()
        validate_dosi_document(model.read_text())
        compiled = dosi_engine.Engine(model_path=str(model)).compile({
            "metrics": ["delivered_gmv", "delivered_order_count"],
            "group_by": [{"field": "metric_time", "grain": "month"}],
        }, dialect="duckdb")
        semantic = connector.execute_query(compiled["sql"], result_format="list")
        expected = connector.execute_query("""
            SELECT month_start::TIMESTAMP AS metric_time__month, delivered_gmv_brl AS delivered_gmv,
                   delivered_orders AS delivered_order_count FROM ads.ads_executive_dashboard
        """, result_format="list")
        def order_key(row):
            return row["metric_time__month"]

        if (not semantic.success or not expected.success
                or sorted(semantic.sql_return, key=order_key) != sorted(expected.sql_return, key=order_key)):
            raise RuntimeError("Dosi and ADS monthly results disagree")
        print(json.dumps({
            "published_version": state["version"], "read_only": connector.read_only,
            "external_access": connector.enable_external_access, "ads_query_result": select.sql_return,
            "dosi_model_validated": True, "dosi_metrics_reconciled": ["delivered_gmv", "delivered_order_count"], "datus_legacy_cardinality": legacy_estimate,
            "project_skill_directory": SkillConfig().directories[0],
        }, default=str))
    finally:
        connector.close()


if __name__ == "__main__":
    smoke(Path(sys.argv[1]))
