import json
import re
from dataclasses import replace
from decimal import Decimal

import duckdb
import pytest
import yaml

from retail_agents.safe_query import Limits, UnsafeQuery, estimated_rows, query, validate_sql
from etl.config import ROOT

Q = "SELECT month_start, delivered_gmv_brl FROM ads.ads_executive_dashboard ORDER BY month_start"


@pytest.mark.parametrize("sql", [
    "UPDATE ads.ads_executive_dashboard SET delivered_gmv_brl=0",
    "SELECT * FROM ads.ads_executive_dashboard; SELECT * FROM ads.ads_sales_anomaly",
    "SELECT * FROM ods.orders",
    "SELECT * FROM dws.dws_customer_retention",
    "SELECT * FROM duckdb_tables()",
    "SELECT * FROM ads.ads_executive_dashboard a JOIN ads.ads_sales_anomaly b USING(month_start)",
    "SELECT (SELECT 1) FROM ads.ads_executive_dashboard",
    "WITH x AS (SELECT * FROM ads.ads_executive_dashboard) SELECT * FROM x",
    "SELECT current_setting('home_directory') FROM ads.ads_executive_dashboard",
    "SELECT * FROM ads.ads_executive_dashboard LIMIT 1000",
    "SELECT * FROM read_csv_auto('/example.csv')",
    "SELECT * FROM main.ads.ads_executive_dashboard",
    "SELECT * FROM ads.ads_executive_dashboard OFFSET 1",
])
def test_sql_denies_unsupported_statements(sql):
    with pytest.raises(UnsafeQuery):
        validate_sql(sql, Limits())


def test_guard_executes_bounded_reads(built):
    _, _, db = built
    assert query(db, Q)["rows"][0][1] == Decimal("200")
    assert query(db, Q + " LIMIT 1")["rows"][0][1] == Decimal("200")
    assert query(db, "SELECT COUNT(*) FROM ads.ads_executive_dashboard")["rows"] == [(2,)]
    for limit, match in (("plan_rows", "cardinality"), ("result_rows", "row or byte"),
                         ("result_bytes", "byte limit"), ("sql_bytes", "SQL input")):
        with pytest.raises(UnsafeQuery, match=match):
            query(db, Q, replace(Limits(), **{limit: 1}))


def test_guard_rejects_non_finite_result(built):
    _, _, db = built
    with pytest.raises(UnsafeQuery, match="non-finite"):
        query(db, "SELECT delivered_gmv_brl / 0 FROM ads.ads_executive_dashboard ORDER BY month_start LIMIT 1")


def test_duckdb_152_explain_regression():
    assert duckdb.__version__ == "1.5.2"
    with duckdb.connect(":memory:", config={"enable_external_access": "false"}) as conn:
        conn.execute("CREATE TABLE x AS SELECT i FROM range(10000) t(i)")
        plan = conn.execute("EXPLAIN SELECT sum(i) FROM x").fetchone()[1]
        assert "~10,000 rows" in plan
        assert not re.search(r"\bEC:\s*([0-9]+)", plan, re.IGNORECASE)
        structured = conn.execute("EXPLAIN (FORMAT JSON) SELECT sum(i) FROM x").fetchone()[1]
        assert estimated_rows(structured) == 10_000


@pytest.mark.parametrize("plan", [
    "not-json",
    "[]",
    json.dumps([{"name": "SEQ_SCAN", "children": [], "extra_info": {}}]),
    json.dumps([{"name": "HASH_JOIN", "children": [], "extra_info": {"Estimated Cardinality": "100"}}]),
    json.dumps([{"name": "SEQ_SCAN", "children": [], "extra_info": {"Estimated Cardinality": "unknown"}}]),
])
def test_guard_fails_closed_when_plan_is_untrusted(plan):
    with pytest.raises(UnsafeQuery, match="cannot be established"):
        estimated_rows(plan)


BENCHMARK = yaml.safe_load((ROOT / "benchmark/questions.yml").read_text())
DICTIONARY = yaml.safe_load((ROOT / "metrics/definitions.yml").read_text())["metrics"]


def test_benchmark_and_metric_metadata():
    assert len({case["id"] for case in BENCHMARK}) == len(BENCHMARK) >= 15
    assert len(DICTIONARY) == 11
    assert {case["metric"] for case in BENCHMARK} == set(DICTIONARY)
    for metric in DICTIONARY.values():
        assert set(metric) == {"meaning", "formula", "numerator", "denominator", "time_dimension",
                               "statuses", "null_handling", "sources", "sql", "limitations"}


@pytest.mark.parametrize("case", BENCHMARK, ids=[case["id"] for case in BENCHMARK])
def test_benchmark_sql_is_executable(built, case):
    _, _, db = built
    result = query(db, case["sql"])
    actual = [[float(value) if isinstance(value, Decimal) else value for value in row] for row in result["rows"]]
    assert actual == case["expected"]
