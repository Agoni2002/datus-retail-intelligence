"""Fixture evaluation through the real Datus custom node, SDK and stdio MCP."""

import argparse
import asyncio
import hashlib
import json
import os
import resource
from contextlib import AsyncExitStack
from datetime import date
from decimal import Decimal
from pathlib import Path
from time import monotonic
from uuid import uuid4

import sqlglot
import yaml
from datus.models.mcp_utils import multiple_mcp_servers

from etl.config import ROOT
from etl.snapshot import Snapshots, atomic_json
from ingestion.olist_loader import source_hashes
from retail_agents.analyst import SDK_TOOLS, answer_is_grounded, run
from retail_agents.context_index import build, retrieve
from retail_agents.mcp_server import SERVER
from retail_agents.scripted_transport import ScriptedTransport
from retail_agents.safe_query import validate_sql, Limits

BENCHMARK = ROOT / "benchmark/questions.yml"
DICTIONARY = ROOT / "metrics/definitions.yml"
REFERENCES = ROOT / "agents/reference_sql"
MONEY_TOLERANCE = Decimal("0.005")
RATE_TOLERANCE = Decimal("0.000001")


def tool(name, **arguments):
    return f"mcp__retail__retail_{name}", arguments


def context(text, kind="metric"):
    return tool("context", question=text, kind=kind)


def statement(text):
    return tool("query", sql=text)


def reference(name):
    return statement((REFERENCES / f"{name}.sql").read_text())


def rows_match(actual, expected):
    if len(actual) != len(expected):
        return False
    for left, right in zip(actual, expected, strict=True):
        if len(left) != len(right):
            return False
        for value, gold in zip(left, right, strict=True):
            if type(gold) is bool or gold is None:
                if type(value) is not type(gold) or value != gold:
                    return False
            elif isinstance(gold, (int, float)):
                try:
                    error = abs(Decimal(str(value)) - Decimal(str(gold)))
                    if not error.is_finite() or error > RATE_TOLERANCE:
                        return False
                except ArithmeticError:
                    return False
            elif value != gold:
                return False
    return True


def metric_agreement(published, semantic, guarded):
    def normalize(result):
        return {str(day)[:10]: (Decimal(str(gmv)), Decimal(str(count))) for day, gmv, count in result}

    a, b, c = map(normalize, (published, semantic, guarded))
    if (not a or a.keys() != b.keys() or a.keys() != c.keys()
            or any(len(index) != len(raw) for index, raw in ((a, published), (b, semantic), (c, guarded)))):
        return False
    for actual in (b, c):
        for key, (amount, count) in actual.items():
            if abs(amount - a[key][0]) > MONEY_TOLERANCE or count != a[key][1]:
                return False
    return True


def evidence_of(results):
    return [{key: row[key] for key in ("request_id", "columns", "rows")}
            for row in results if row.get("ok") and "rows" in row]


def response_for(metrics, definitions, results, analysis=None):
    evidence = evidence_of(results)
    if analysis and evidence:
        answer, limitations = analysis([item["rows"] for item in evidence])
    elif evidence:
        first = definitions[metrics[0]]
        answer = f"{first['meaning']} {first['time_dimension']} Result: {evidence[-1]['rows']}."
        limitations = [first["limitations"]]
    else:
        answer, limitations = "The guarded tool did not produce result evidence.", ["No conclusion was drawn."]
    return {"answer": answer, "metric_ids": metrics, "evidence": evidence, "limitations": limitations}


def sales(parts):
    data = parts[0]
    return ("Monthly delivered GMV and delivered order counts: " + ", ".join(
        f"{str(month)[:7]} BRL {gmv}, {orders} orders" for month, gmv, orders in data
    ) + ".", ["Synthetic available months, grouped by purchase month. GMV excludes freight."])


def categories(parts):
    rows = parts[0]
    return ("Delivered merchandise by category across the available period: " + ", ".join(
        f"{category} BRL {value}" for category, value in rows
    ) + ".", ["Source category assignment can change between extracts."])


def sellers(parts):
    rows = parts[0]
    return ("Cancellation rates across the available period: " + ", ".join(
        f"{seller} {rate:.1%} ({canceled}/{orders} seller orders)" for seller, canceled, orders, rate in rows
    ) + ".", ["One order may involve multiple sellers. Order cancellation does not establish seller fault."])


def fulfillment(parts):
    rows = parts[0]
    return ("On-time delivery rates by customer state across the available period: " + ", ".join(
        f"{state} {rate:.1%} ({on_time}/{eligible} eligible deliveries)" for state, on_time, eligible, rate in rows
    ) + ".", ["Small eligible populations and missing dates limit comparisons."])


def retention(parts):
    return ("Monthly repeat purchase: " + ", ".join(
        f"{str(month)[:7]} {rate:.1%} ({repeat}/{customers} delivered customers)"
        for month, repeat, customers, rate in parts[0]
    ) + ".", ["This is within-month repeat purchasing."])


def investigation(parts):
    if len(parts) < 4:
        return "The guarded tools did not return all comparison data.", ["The change was not decomposed."]
    monthly, category, seller, geography = parts[:4]
    if len(monthly) != 2:
        return "Two adjacent purchase months are required.", ["A one-month snapshot cannot support the comparison."]
    current, previous = monthly
    this_day, last_day = (date.fromisoformat(item[0]) for item in (current, previous))
    if (this_day.year - last_day.year) * 12 + this_day.month - last_day.month != 1:
        return "The available months are not adjacent.", ["A month-over-month comparison could not be made."]
    change = Decimal(current[1]) - Decimal(previous[1])
    if not current[2] or not previous[2]:
        return "The delivered GMV change is available, but the AOV split needs deliveries in each period.", [
            "Zero delivered orders makes the relevant average undefined."
        ]
    prior_aov = Decimal(previous[1]) / previous[2]
    now_aov = Decimal(current[1]) / current[2]
    volume = (current[2] - previous[2]) * prior_aov
    mix = current[2] * (now_aov - prior_aov)
    if abs(change - volume - mix) > MONEY_TOLERANCE:
        raise ValueError("GMV volume and AOV terms did not reconcile")

    def changes(records):
        present = {}
        for month, group, value, *_ in records:
            if month in (current[0], previous[0]):
                direction = 1 if month == current[0] else -1
                present[group] = present.get(group, 0) + direction * Decimal(value)
        return ", ".join(f"{group} {value:+.2f}" for group, value in sorted(present.items(), key=lambda item: item[1]))

    category_changes = ", ".join(f"{group} {Decimal(value):+.2f}" for month, group, value in category
                                 if month == current[0])
    return (f"{previous[0][:7]} to {current[0][:7]}: delivered GMV changed from BRL {previous[1]} to "
            f"BRL {current[1]} ({change:+.2f}). Delivered orders changed from {previous[2]} to {current[2]}. "
            f"At prior AOV the volume effect was BRL {volume:+.2f}, and the AOV effect was BRL {mix:+.2f}. "
            f"Category changes in BRL: {category_changes}. Seller changes in BRL: {changes(seller)}. "
            f"Regional delivered-order changes: {changes(geography)}.",
            ["Regional GMV is unavailable on the approved serving surface. The data describes contributions "
             "and cannot establish a cause or support a causal hypothesis."])


SCENARIOS = (
    ("A-sales", "Show monthly delivered GMV for the available period.", ["delivered_gmv", "delivered_order_count"],
     [tool("metric", metrics=["delivered_gmv", "delivered_order_count"])],
     [[["2018-01-01 00:00:00", 200, 3], ["2018-02-01 00:00:00", 80, 1]]], sales, ("BRL 200", "BRL 80")),
    ("B-category", "Which product categories contribute most to delivered GMV?", ["category_sales"],
     [reference("top_categories_delivered_gmv")],
     [[["electronics", 190], ["home", 90]]], categories, ("electronics", "BRL 190")),
    ("C-seller", "Which sellers have the highest cancellation rates?", ["seller_performance"],
     [reference("seller_cancellation")],
     [[["s1", 2, 4, .5], ["s2", 1, 4, .25]]], sellers, ("50.0%", "2/4", "seller fault")),
    ("D-fulfillment", "Which regions have the worst on-time delivery performance?", ["on_time_delivery_rate"],
     [reference("regional_on_time_delivery")],
     [[["RJ", 0, 1, 0], ["SP", 1, 2, .5]]], fulfillment, ("RJ", "0/1", "missing dates")),
    ("E-customer", "What is the repeat purchase rate?", ["repeat_purchase_rate"], [reference("monthly_repeat_purchase")],
     [[["2018-01-01", 1, 2, .5], ["2018-02-01", 0, 1, 0]]], retention, ("within-month", "1/2", "0/1")),
    ("F-investigation", "Why did delivered GMV decrease compared with the previous month?",
     ["delivered_gmv", "delivered_order_count", "average_order_value", "category_sales", "seller_performance"],
     [reference("monthly_gmv_volume_and_order_value"), reference("category_gmv_contribution"),
      reference("seller_gmv_contribution"), reference("regional_fulfillment")],
     [[["2018-02-01", 80, 1, 80], ["2018-01-01", 200, 3, 66.66666666666667]],
      [["2018-02-01", "home", -90], ["2018-02-01", "electronics", -30]],
      [["2018-02-01", "s1", 0], ["2018-02-01", "s2", 80], ["2018-01-01", "s1", 110], ["2018-01-01", "s2", 90]],
      [["2018-02-01", "RJ", 1, 1, 0], ["2018-01-01", "RJ", 1, 0, 0], ["2018-01-01", "SP", 2, 2, 1]]],
     investigation, ("-120.00", "-133.33", "+13.33", "home -90", "s1 -110", "SP -2", "cannot establish a cause")),
)

NEGATIVE = (
    ("insert", "INSERT INTO ads.ads_executive_dashboard SELECT * FROM ads.ads_executive_dashboard WHERE false", "INVALID_SQL"),
    ("update", "UPDATE ads.ads_executive_dashboard SET orders=0 WHERE false", "INVALID_SQL"),
    ("delete", "DELETE FROM ads.ads_executive_dashboard WHERE false", "INVALID_SQL"),
    ("drop", "DROP TABLE ads.ads_executive_dashboard", "INVALID_SQL"),
    ("alter", "ALTER TABLE ads.ads_executive_dashboard ADD COLUMN forbidden INT", "INVALID_SQL"),
    ("create", "CREATE TABLE ads.forbidden (id INT)", "INVALID_SQL"),
    ("attach", "ATTACH '/nonexistent-retail-fixture.duckdb'", "INVALID_SQL"),
    ("copy", "COPY ads.ads_executive_dashboard TO '/nonexistent-retail-fixture.csv'", "INVALID_SQL"),
    ("private-table", "SELECT * FROM ods.orders", "TABLE_NOT_ALLOWED"),
    ("external-file", "SELECT * FROM read_csv_auto('/nonexistent-retail-fixture.csv')", "TABLE_NOT_ALLOWED"),
    ("multiple", "SELECT * FROM ads.ads_executive_dashboard; SELECT * FROM ads.ads_sales_anomaly", "INVALID_SQL"),
    ("unknown-plan", "SELECT 1 FROM ads.ads_executive_dashboard LIMIT 1", "PLAN_UNRECOGNIZED"),
    ("oversized-result", "SELECT * FROM ads.ads_executive_dashboard LIMIT 501", "RESULT_LIMIT"),
)
BYPASS = ("execute_sql", "read_query", "query_metrics", "bash", "read_file", "task", "web_search", "load_skill")


def record(result):
    # Minimal persistent traces. The audit's IDs correlate tool actions without SQL or result payloads.
    return {key: result[key] for key in ("run_id", "tool_surface", "actions", "audit")}


def shell_stats(start):
    return {"seconds": round(monotonic() - start, 2),
            "runner_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "largest_reaped_child_peak_rss_kib": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss}


def expected_projection(sql):
    tree = sqlglot.parse_one(sql, read="duckdb")
    return tuple(expression.output_name or None for expression in tree.expressions)


def projection_matches(actual, expected):
    return len(actual) == len(expected) and all(
        want is None or have == want for have, want in zip(actual, expected, strict=True)
    )


def score_positive(result, metric_ids, expected, required_text=(), source_tables=(), expected_columns=(), context_kind="metric"):
    answer = result["answer"] or {}
    referenced = [result["tool_outputs"].get(item.get("request_id"), {}) for item in answer.get("evidence", [])
                  if isinstance(item, dict)] if isinstance(answer.get("evidence"), list) else []
    used = [event for event in result["audit"] if event["tool"] in {"retail_query", "retail_metric"}
            and event["outcome"] == "allowed"]
    provenance = {entry.get("source_table") for entry in referenced}
    projections = expected_columns or [None] * len(expected)
    matching = all(any(rows_match(entry.get("rows", []), rows)
                       and (columns is None or projection_matches(entry.get("columns", []), columns))
                       for entry in referenced)
                   for rows, columns in zip(expected, projections, strict=True))
    surfaced = bool(result["tool_surface"]) and all(set(tools) == SDK_TOOLS for tools in result["tool_surface"])
    rendered = " ".join([str(answer.get("answer", "")), *map(str, answer.get("limitations") or [])]).lower()
    checks = {
        "metric_identification": isinstance(answer.get("metric_ids"), list) and
        set(metric_ids) <= {value for value in answer["metric_ids"] if isinstance(value, str)},
        "guarded_execution": bool(used) and answer_is_grounded(result),
        "table_selection": not source_tables or set(source_tables) <= provenance,
        "column_and_value_match": matching,
        "explanation_checks": bool(answer.get("limitations")) and all(text.lower() in rendered for text in required_text),
        "safe_tool_surface": surfaced,
        "context_retrieved": any(item.get("kind") == context_kind for output in result["tool_outputs"].values()
                                 for item in output.get("items", [])),
    }
    return {"passed": all(checks.values()), "checks": checks, "expected_rows": expected,
            "observed": [{"columns": entry["columns"], "rows": entry["rows"], "source_table": entry["source_table"]}
                         for entry in referenced if entry.get("ok") and "source_table" in entry],
            **record(result)}


class BorrowedStdio:
    """Let each Datus node use the same locally connected evaluation transport."""

    def __init__(self, connection):
        self.connection = connection

    def __getattr__(self, name):
        return getattr(self.connection, name)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None


class EvaluationMCP:
    def __init__(self, stack, runtime):
        self.id = uuid4().hex
        self.stack = stack
        self.audit = runtime.resolve() / "audit" / f"{self.id}.jsonl"
        self.version = None
        self.servers = None

    async def borrow(self, servers, version):
        if self.servers is None:
            connected = await self.stack.enter_async_context(multiple_mcp_servers(servers))
            if set(connected) != {SERVER}:
                raise RuntimeError("The project MCP server did not connect")
            self.servers = {name: BorrowedStdio(connection) for name, connection in connected.items()}
            self.version = version
        if self.version != version:
            raise RuntimeError("The warehouse publication changed during evaluation; rerun on one version")
        return self.servers


def hash_file(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


async def evaluation(output, runtime, live=False, quick=False):
    start = monotonic()
    async with AsyncExitStack() as stack:
        mcp = EvaluationMCP(stack, runtime)
        result = await evaluate_cases(output, runtime, live, quick, mcp)
    return result | {"resources": shell_stats(start)}


async def evaluate_cases(output, runtime, live, quick, mcp):
    state = Snapshots(output)
    manifest = state.latest()
    if manifest is None:
        raise ValueError("Synthetic snapshot is missing")
    if manifest["source_sha256"] != source_hashes(ROOT / "data/fixtures/olist"):
        raise ValueError("Evaluation expects the published synthetic benchmark fixture")
    snapshot = state.directory / manifest["database"]
    original_hash = hash_file(snapshot)
    report = build(snapshot, runtime.resolve() / "context")
    definitions = yaml.safe_load(DICTIONARY.read_text())["metrics"]

    async def execute(question, calls, ids, analysis=None):
        scripted = None if live else ScriptedTransport(
            calls, lambda results: response_for(ids, definitions, results, analysis)
        )
        result = await run(question, output, runtime, scripted, index_report=report, mcp_session=mcp)
        if scripted is not None:
            result["scripted_sdk_feedback"] = [
                {"tool": name, "tool_not_found": scripted.sdk_feedback.get(call_id, False)}
                for call_id, name in scripted.calls_sent.items()
            ]
        return result

    retrieval_queries = {
        "business": ("delivery fulfillment data requirements", "docs/business_requirements.md"),
        "table": ("ads_executive_dashboard", "published warehouse schema"),
        "column": ("on_time_delivery_rate", "published warehouse schema"),
        "relationship": ("payments orders", "docs/dimensional_model.md"),
        "metric": ("repeat purchase rate", "metrics/definitions.yml"),
        "reference": ("seller cancellation", "agents/reference_sql/seller_cancellation.sql"),
    }
    retrieval = {}
    if live:
        for kind, (text, expected) in retrieval_queries.items():
            found = retrieve(runtime.resolve() / "context", report["index_id"], text, kind, top_n=5)
            retrieval[kind] = {"passed": any(row["source"] == expected for row in found),
                               "sources": [row["source"] for row in found]}
    else:
        result = await execute("Verify the six curated retail context lookups", [
            tool("context", question=text, kind=kind, top_n=5)
            for kind, (text, _) in retrieval_queries.items()
        ], ["delivered_gmv"])
        completed = {action["request_id"] for action in result["actions"] if action["status"] == "success"}
        events = [event for event in result["audit"] if event["tool"] == "retail_context"]
        for slot, (kind, (_, expected)) in enumerate(retrieval_queries.items()):
            event = events[slot] if slot < len(events) else {}
            receipt = event.get("request_id")
            items = result["tool_outputs"].get(receipt, {}).get("items", [])
            retrieval[kind] = {
                "passed": receipt in completed and any(row["source"] == expected and row["kind"] == kind
                                                       for row in items),
                "sources": [row["source"] for row in items],
                "receipt": event,
            }

    cases = yaml.safe_load(BENCHMARK.read_text())
    scores = {}
    for case in cases[:1] if quick else cases:
        metric = case["metric"]
        result = await execute(case["question"], [context(metric), statement(case["sql"])], [metric])
        _, schema, table = validate_sql(case["sql"], Limits())
        scores[case["id"]] = score_positive(result, [metric], [case["expected"]],
                                             source_tables=(f"{schema}.{table}",),
                                             expected_columns=[expected_projection(case["sql"])])
    scenarios = {}
    for name, question, metrics, calls, expected, analysis, cues in SCENARIOS[:1] if quick else SCENARIOS:
        result = await execute(question, [context(" ".join(metrics[:2])), *calls], metrics, analysis)
        tables, projections = [], []
        for target, args in calls:
            if target.endswith("__retail_query"):
                _, schema, table = validate_sql(args["sql"], Limits())
                tables.append(f"{schema}.{table}")
                projections.append(expected_projection(args["sql"]))
            else:
                tables.append("dws.dws_sales_daily")
                projections.append(("metric_time__month", *args["metrics"]))
        scenarios[name] = score_positive(result, metrics, expected, cues, source_tables=tables,
                                         expected_columns=projections)
        if not live and result["answer"]:
            scenarios[name]["scripted_explanation"] = result["answer"]["answer"]
            scenarios[name]["limitations"] = result["answer"]["limitations"]

    consistency = {"passed": None, "status": "not tested in live mode"}
    if not live:
        # Ask one actual Datus turn to exercise the semantic and both SQL paths.
        result = await execute("Reconcile the two monthly published fulfillment metrics", [
            context("delivered gmv"),
            statement("SELECT month_start, delivered_gmv_brl, delivered_orders FROM ads.ads_executive_dashboard ORDER BY month_start"),
            tool("metric", metrics=["delivered_gmv", "delivered_order_count"]),
            statement("SELECT purchase_date, delivered_gmv_brl, delivered_orders FROM dws.dws_sales_daily ORDER BY purchase_date"),
        ], ["delivered_gmv", "delivered_order_count"])
        outputs = [result["tool_outputs"][event["request_id"]] for event in result["audit"]
                   if event["tool"] != "retail_context" and event["outcome"] == "allowed"
                   and event["request_id"] in result["tool_outputs"]]
        if len(outputs) == 3:
            aggregate = {}
            for day, gmv, orders in outputs[2]["rows"]:
                key = day[:7] + "-01"
                amount, count = aggregate.get(key, (Decimal(0), 0))
                aggregate[key] = (amount + Decimal(gmv), count + orders)
            guarded = [(month, *values) for month, values in sorted(aggregate.items())]
            consistent = metric_agreement(outputs[0]["rows"], outputs[1]["rows"], guarded)
        else:
            consistent = False
        consistency = {"passed": consistent, "money_tolerance_brl": str(MONEY_TOLERANCE),
                       "count_tolerance": 0, **record(result)}

    security = {}
    if not live:
        cases = NEGATIVE[:1] if quick else NEGATIVE
        for offset in range(0, len(cases), 8):
            batch = cases[offset:offset + 8]
            result = await execute("Controlled SQL Guard checks", [statement(sql) for _, sql, _ in batch],
                                   ["delivered_gmv"])
            audit = result["audit"]
            for slot, (name, _, code) in enumerate(batch):
                matched = len(audit) == len(batch) and audit[slot]["error_code"] == code
                security[name] = {"passed": matched and audit[slot]["outcome"] == "denied"
                                  and not answer_is_grounded(result),
                                  "event": audit[slot] if matched else None, **record(result)}
        probes = BYPASS[:1] if quick else BYPASS
        result = await execute("Controlled native tool visibility checks", [(name, {}) for name in probes],
                               ["delivered_gmv"])
        feedback = {event["tool"]: event["tool_not_found"] for event in result["scripted_sdk_feedback"]}
        for name in probes:
            security[f"bypass-{name}"] = {"passed": bool(result["tool_surface"]) and feedback.get(name) is True
                                          and all(set(tools) == SDK_TOOLS for tools in result["tool_surface"])
                                          and not result["audit"] and not answer_is_grounded(result),
                                          "sdk_tool_not_found": feedback.get(name, False), **record(result)}

    audit_shape = {"ts_utc", "run_id", "request_id", "tool", "outcome", "elapsed_ms",
                   "snapshot_version", "row_count", "error_code"}
    events = []
    if mcp.audit.exists():
        with mcp.audit.open() as stream:
            events = [json.loads(line) for line in stream]
    security["metadata_only_audit"] = {"passed": bool(events) and all(set(row) == audit_shape for row in events)}
    security["published_snapshot_immutable"] = {
        "passed": hash_file(snapshot) == original_hash and snapshot.stat().st_mode & 0o222 == 0,
        "snapshot": manifest["version"],
    }
    groups = [scores, scenarios, security, retrieval]
    passed = all(row["passed"] for group in groups for row in group.values()) and consistency["passed"] is not False
    return {"mode": "live" if live else "scripted_provider_datus_sdk_mcp", "passed": passed,
            "live_reasoning_evaluated": live, "narrative_review_required": live,
            "snapshot_version": manifest["version"], "context_index": report, "retrieval": retrieval,
            "benchmark": scores, "scenarios": scenarios, "security": security, "metric_consistency": consistency}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data/processed/fixture")
    parser.add_argument("--runtime", type=Path, default=ROOT / ".datus-runtime/retail-analyst")
    parser.add_argument("--report", type=Path, default=ROOT / "data/processed/retail-agent-evaluation.json")
    parser.add_argument("--quick", action="store_true", help="Run a small end-to-end subset")
    parser.add_argument("--live", action="store_true", help="Use OPENAI_API_KEY for a real provider run")
    args = parser.parse_args()
    os.chdir(ROOT)
    if args.live and not os.getenv("OPENAI_API_KEY"):
        parser.exit(2, "Live evaluation requires OPENAI_API_KEY. Run without --live for scripted integration.\n")
    result = asyncio.run(evaluation(args.output, args.runtime, args.live, args.quick))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(args.report, result)
    print(json.dumps({"mode": result["mode"], "passed": result["passed"], "report": str(args.report),
                      "resources": result["resources"]}))
    if not result["passed"]:
        parser.exit(1)


if __name__ == "__main__":
    main()
