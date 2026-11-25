"""Verify live Superset assets against the immutable Phase 1C publication."""

import json
import math
import sys
from contextlib import redirect_stdout
from importlib.metadata import version
from pathlib import Path

from sqlalchemy.exc import DBAPIError

from common import API, CONNECT_ARGS, digest, read_runtime, warehouse

# Independent Phase 1C acceptance references. These are test expectations only.
BASELINE_VERSION = "20261125T082335510967Z-d82ffee2"
PHASE1C = {
    "gmv": (13221498.11, .005),
    "delivered": (96478, 0),
    "aov": (137.04, .005),
    "cancel_rate": (.006285, .0000005),
    "on_time_exec": (.932158, .0000005),
    "late_avg": (10.62, .005),
    "freight": (2198275.64, .005),
    "review": (4.1559, .00005),
    "repeat": (.012847, .0000005),
}


def rows(api, context):
    response = api.call("POST", "/chart/data", context)
    out = []
    for result in response["result"]:
        if result.get("error") or not isinstance(result.get("data"), list):
            raise RuntimeError(f"Chart data query failed: {result.get('error', result.get('status'))}")
        out.extend(result["data"])
    return out


def context(dataset_id, metrics, columns=None, filters=None, time_range="No filter"):
    return {
        "datasource": {"id": dataset_id, "type": "table"}, "force": True,
        "queries": [{"metrics": metrics, "columns": columns or [], "filters": filters or [],
                     "granularity":"month_start", "time_range":time_range,
                     "row_limit":100, "is_timeseries":False}],
        "result_type":"full", "result_format":"json",
    }


def main():
    receipt = read_runtime("snapshot.json")
    deployment = read_runtime("provision.json")
    assert receipt["version"] == deployment["version"] and receipt["sha256"] == deployment["sha256"]
    uri, engine = warehouse(receipt)
    api = API()
    database_id = deployment["database_id"]
    registered = api.get("database", database_id)
    for key in ("allow_dml","allow_ctas","allow_cvas","allow_file_upload","allow_run_async","expose_in_sqllab"):
        assert registered[key] is False, key
    from superset.app import create_app
    from superset.extensions import db

    with redirect_stdout(sys.stderr):
        app = create_app()
    with app.app_context():
        from superset.models.core import Database

        source = db.session.get(Database, database_id)
        registered_args = source.get_extra()["engine_params"]["connect_args"]
        assert registered_args["read_only"] is True
        assert registered_args["config"].items() >= CONNECT_ARGS["config"].items()
        assert source.sqlalchemy_uri_decrypted == uri
        with source.get_sqla_engine() as actual_engine, actual_engine.connect() as actual_connection:
            assert str(actual_connection.exec_driver_sql("SELECT current_setting('access_mode')").scalar()).lower() == "read_only"
            assert not actual_connection.exec_driver_sql("SELECT current_setting('enable_external_access')").scalar()
            try:
                actual_connection.exec_driver_sql("CREATE TABLE ads.retail_bi_read_only_probe (probe INTEGER)")
            except DBAPIError as error:
                assert "read-only" in str(error).lower() or "read only" in str(error).lower()
            else:
                raise RuntimeError("Superset's registered warehouse engine accepted a write")
    verified_charts = {}
    dashboard_filters = {}
    for slug, dash in deployment["dashboards"].items():
        metadata = api.get("dashboard", dash["id"])
        assert metadata["published"] and metadata["slug"] == slug
        filters = json.loads(metadata["json_metadata"])["native_filter_configuration"]
        dashboard_filters[slug] = [f["name"] for f in filters]
        assert "Purchase date range" in dashboard_filters[slug]
        for item in filters:
            assert set(item["chartsInScope"]) | set(item["scope"]["excluded"]) == {
                chart["id"] for chart in dash["charts"].values()
            }
        verified_charts[slug] = {}
        for key, chart in dash["charts"].items():
            stored = api.get("chart", chart["id"])
            payload = json.loads(stored["query_context"])
            payload["force"] = True
            result = rows(api, payload)
            if not result:
                raise RuntimeError(f"Published chart returned no rows: {slug}/{key}")
            verified_charts[slug][key] = len(result)
    assert len(verified_charts) == 6

    quality = api.get("dashboard", deployment["dashboards"]["retail-quality"]["id"])
    position = json.loads(quality["position_json"])
    panels = "\n".join(x["meta"]["code"] for x in position.values()
                       if isinstance(x,dict) and x.get("type") == "MARKDOWN")
    required = ["source rows", "blockers", "warnings", "no geographic match", "no category translation",
                "timestamp anomalies", "on-time denominator", "missing payment", "Latest review date",
                "publication manifest timestamp", receipt["version"]]
    if receipt["version"] == BASELINE_VERSION:
        required += ["1,550,922", "132 checks", "0 blockers", "5 warnings", "261,831", "278 customers", "7 sellers",
                     "13 products", "189 timestamp", "188 delivered, 1 shipped", "8 delivered", "196 delivered",
                     "264 delivered", "1 missing payment", "263 differences", "2018-08-31",
                     "47 days", "September 2018 and October 2018 contain 20 orders and 0 delivered",
                     "sparse extract coverage"]
    assert all(value in panels for value in required), [value for value in required if value not in panels]

    ds = {key: obj["id"] for key, obj in deployment["datasets"].items()}
    summaries = rows(api, context(ds["executive"], list(PHASE1C)))
    assert len(summaries) == 1
    values = summaries[0]
    with engine.connect() as conn:
        assert str(conn.exec_driver_sql("SELECT current_setting('access_mode')").scalar()).lower() == "read_only"
        assert not conn.exec_driver_sql("SELECT current_setting('enable_external_access')").scalar()
        schemas = {row[0] for row in conn.exec_driver_sql("SELECT schema_name FROM information_schema.schemata")}
        assert {"ads","dws"} <= schemas
        evidence = {
            "date": (context(ds["executive"],["gmv"],time_range="2018-01-01 : 2018-02-01"), "gmv",
                     "SELECT SUM(delivered_gmv_brl) FROM ads.ads_executive_dashboard WHERE month_start=DATE '2018-01-01'"),
            "category": (context(ds["category"],["category_gmv"],filters=[{"col":"category_name","op":"IN",
                                                                        "val":["health_beauty"]}]), "category_gmv",
                         "SELECT SUM(category_sales_brl) FROM dws.dws_category_performance WHERE category_name='health_beauty'"),
            "geography": (context(ds["fulfillment"],["eligible"],filters=[{"col":"state","op":"IN","val":["SP"]}]),
                          "eligible","SELECT SUM(eligible_orders) FROM dws.dws_delivery_performance WHERE state='SP'"),
        }
        seller = conn.exec_driver_sql("SELECT seller_id FROM ads.ads_seller_scorecard ORDER BY seller_id LIMIT 1").scalar()
        assert seller.isalnum()
        evidence["seller"] = (
            context(ds["seller"],["seller_orders"],filters=[{"col":"seller_id","op":"IN","val":[seller]}]),
            "seller_orders",f"SELECT SUM(seller_orders) FROM ads.ads_seller_scorecard WHERE seller_id='{seller}'",
        )
        filter_results = {}
        for label, (payload, key, sql) in evidence.items():
            reference = conn.exec_driver_sql(sql).scalar()
            actual = rows(api,payload)[0][key]
            assert reference is not None and math.isclose(float(actual),float(reference),abs_tol=.005), (label,actual)
            filter_results[label] = actual
        empty = context(ds["fulfillment"],["eligible"],["state"],[{"col":"state","op":"IN","val":["XX"]}])
        assert not rows(api,empty)
        filter_results["no_matching_state_rows"] = 0
    engine.dispose()
    if receipt["version"] == BASELINE_VERSION:
        for name, (expect, tol) in PHASE1C.items():
            assert math.isclose(float(values[name]),expect,rel_tol=0,abs_tol=tol), (name,values[name],expect)
    assert digest(Path(receipt["container_path"])) == receipt["sha256"]
    print(json.dumps({
        "snapshot":receipt["version"], "snapshot_sha256":receipt["sha256"],
        "versions":{n:version(n) for n in ("apache-superset","duckdb","duckdb-engine","SQLAlchemy","psycopg2-binary")},
        "dashboard_count":len(verified_charts),"chart_count":sum(map(len,verified_charts.values())),
        "charts":verified_charts,"filters":dashboard_filters,"filter_results":filter_results,"kpis":values,
        "quality_panels":True,"read_only_write_rejected":True,"administrator_authenticated":True,
    }, indent=2))


if __name__ == "__main__":
    main()
