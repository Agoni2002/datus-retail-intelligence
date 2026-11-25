"""Retail SQL entry point for bounded, read-only queries over published tables."""

import argparse
import json
import re
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from threading import Timer
from time import monotonic

import duckdb
import sqlglot
from sqlglot import exp

from etl.snapshot import Snapshots

APPROVED = frozenset({
    ("ads", "ads_executive_dashboard"),
    ("ads", "ads_seller_scorecard"),
    ("ads", "ads_delivery_alerts"),
    ("ads", "ads_sales_anomaly"),
    ("ads", "ads_sales_category_movement"),
    ("dws", "dws_sales_daily"),
    ("dws", "dws_category_performance"),
    ("dws", "dws_delivery_performance"),
})

# Exact AST classes are intentional. Future SQLGlot syntax is denied until reviewed.
NODES = frozenset("""
    Select From Table TableAlias Identifier Column Alias Star Literal Boolean Null
    Where Group Having Order Ordered Limit Distinct Filter
    EQ NEQ GT GTE LT LTE Is In Between Like And Or Not Paren
    Add Sub Mul Div Mod Neg Case If
    TimestampTrunc Var Cast DataType DataTypeParam Count Sum Avg Min Max Round Abs Coalesce Nullif
""".split())
SCALAR_TYPES = frozenset({"DATE", "TIMESTAMP", "INT", "BIGINT", "DOUBLE", "DECIMAL", "BOOLEAN", "VARCHAR"})
SCANS = frozenset({"SEQ_SCAN", "COLUMN_DATA_SCAN"})
ESTIMATED_OPERATORS = frozenset({"FILTER", "HASH_GROUP_BY", "PERFECT_HASH_GROUP_BY", "SIMPLE_AGGREGATE"})
WRAPPERS = frozenset({"PROJECTION", "UNGROUPED_AGGREGATE", "ORDER_BY", "TOP_N", "STREAMING_LIMIT", "LIMIT"})


class UnsafeQuery(ValueError):
    def __init__(self, message: str, code: str = "INVALID_SQL"):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Limits:
    sql_bytes: int = 8192
    ast_nodes: int = 300
    plan_rows: int = 1_000_000
    result_rows: int = 500
    result_bytes: int = 256_000
    timeout_seconds: float = 5

    def __post_init__(self):
        for value in (self.sql_bytes, self.ast_nodes, self.plan_rows, self.result_rows, self.result_bytes):
            if type(value) is not int or value <= 0:
                raise ValueError("SQL limits must be positive integers")
        if not 0 < self.timeout_seconds <= 60:
            raise ValueError("Timeout must be positive and at most 60 seconds")


def validate_sql(sql: str, limits: Limits) -> tuple[str, str, str]:
    if len(sql.encode("utf-8")) > limits.sql_bytes:
        raise UnsafeQuery("SQL input exceeds the byte limit")
    try:
        statements = sqlglot.parse(sql, read="duckdb")
    except (sqlglot.errors.SqlglotError, RecursionError) as error:
        raise UnsafeQuery("Could not parse one supported DuckDB SELECT") from error
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        raise UnsafeQuery("Exactly one SELECT is required")
    statement = statements[0]
    nodes = list(statement.walk())
    if len(nodes) > limits.ast_nodes or sum(isinstance(n, exp.Select) for n in nodes) != 1:
        raise UnsafeQuery("Nested or complex SELECT statements are unsupported")
    from_clause = statement.args.get("from_")
    if from_clause is None or not isinstance(from_clause.this, exp.Table):
        raise UnsafeQuery("Query must select from one approved table")
    table = from_clause.this
    tables = list(statement.find_all(exp.Table))
    if (len(tables) != 1 or not isinstance(table.this, exp.Identifier) or table.catalog
            or (table.db.lower(), table.name.lower()) not in APPROVED):
        raise UnsafeQuery("Query must select from one schema-qualified approved table", "TABLE_NOT_ALLOWED")
    for node in nodes:
        if type(node).__name__ not in NODES or isinstance(node, exp.DataType) and node.this.value not in SCALAR_TYPES:
            raise UnsafeQuery(f"Unsupported SQL expression: {type(node).__name__}")
        if isinstance(node, exp.Var) and (
            not isinstance(node.parent, exp.TimestampTrunc) or node.parent.args.get("unit") != node
            or node.name.upper() != "MONTH"
        ):
            raise UnsafeQuery("Only MONTH is supported for date truncation")
    limit = statement.args.get("limit")
    if limit is not None:
        value = limit.expression
        if (not isinstance(value, exp.Literal) or not value.is_int or
                not 0 <= int(value.this) <= limits.result_rows):
            raise UnsafeQuery("LIMIT must be a literal within the result row limit", "RESULT_LIMIT")
    else:
        statement = statement.limit(limits.result_rows + 1)
    # Bind DuckDB to the parsed statement itself. Original comments, ambiguous
    # source spelling and any trailing statement text never reach the engine.
    return statement.sql(dialect="duckdb", comments=False), table.db.lower(), table.name.lower()


def estimated_rows(raw_plan: str) -> int:
    try:
        roots = json.loads(raw_plan)
        if not isinstance(roots, list) or len(roots) != 1:
            raise ValueError
        pending = list(roots)
        highest = 0
        while pending:
            node = pending.pop()
            name = node["name"]
            children = node["children"]
            extra = node["extra_info"]
            if not isinstance(children, list) or not isinstance(extra, dict):
                raise ValueError
            value = extra.get("Estimated Cardinality")
            if name in SCANS:
                if value is None or children:
                    raise ValueError
            elif name in ESTIMATED_OPERATORS:
                if value is None or len(children) != 1:
                    raise ValueError
            elif name == "EMPTY_RESULT":
                if children:
                    raise ValueError
            elif name not in WRAPPERS or len(children) != 1:
                raise ValueError
            if value is not None:
                if not re.fullmatch(r"[0-9]{1,19}", str(value)):
                    raise ValueError
                highest = max(highest, int(value))
            pending.extend(children)
        return highest
    except (ValueError, TypeError, KeyError, RecursionError) as error:
        raise UnsafeQuery("DuckDB cardinality cannot be established from this plan", "PLAN_UNRECOGNIZED") from error


def query(snapshot: Path, sql: str, limits: Limits = Limits()):
    statement, schema, table = validate_sql(sql, limits)
    with closing(duckdb.connect(str(snapshot), read_only=True, config={
        "enable_external_access": "false", "threads": "1", "memory_limit": "256MB",
        # Keep single-table TOP_N plans single-scan on DuckDB 1.5.2.
        "late_materialization_max_rows": "0",
    })) as conn:
        deadline = monotonic() + limits.timeout_seconds
        cancellation = Timer(limits.timeout_seconds, conn.interrupt)
        cancellation.start()
        try:
            parsed = conn.extract_statements(statement)
            if len(parsed) != 1 or parsed[0].type != duckdb.StatementType.SELECT:
                raise UnsafeQuery("DuckDB rejected the statement type")
            sizes = conn.execute("""
                SELECT estimated_size FROM duckdb_tables()
                WHERE schema_name = ? AND table_name = ? AND database_name = current_database()
            """, [schema, table]).fetchall()
            if len(sizes) != 1 or sizes[0][0] is None or sizes[0][0] < 0:
                raise UnsafeQuery("Approved source must be a materialized table with known size")
            if sizes[0][0] > limits.plan_rows:
                raise UnsafeQuery("Base table cardinality exceeds the plan row limit", "COST_LIMIT")
            plan = conn.execute(f"EXPLAIN (FORMAT JSON) {statement}").fetchall()
            if len(plan) != 1 or plan[0][0] != "physical_plan":
                raise UnsafeQuery("DuckDB did not return a physical plan", "PLAN_UNRECOGNIZED")
            if estimated_rows(plan[0][1]) > limits.plan_rows:
                raise UnsafeQuery("Estimated operator cardinality exceeds the plan row limit", "COST_LIMIT")
            if monotonic() >= deadline:
                raise UnsafeQuery("Query planning exceeded the time limit", "QUERY_TIMEOUT")
            result = conn.execute(statement)
            columns = [item[0] for item in result.description]
            size = len(json.dumps(columns, default=str, ensure_ascii=False).encode()) + 40
            if size > limits.result_bytes:
                raise UnsafeQuery("Result exceeds the byte limit", "RESULT_LIMIT")
            rows = []
            while (row := result.fetchone()) is not None:
                try:
                    encoded = json.dumps(row, default=str, ensure_ascii=False, allow_nan=False)
                except ValueError as error:
                    raise UnsafeQuery("Query returned a non-finite result") from error
                size += len(encoded.encode()) + 2
                if len(rows) >= limits.result_rows or size > limits.result_bytes:
                    raise UnsafeQuery("Result exceeds the row or byte limit; narrow the query", "RESULT_LIMIT")
                rows.append(row)
            if monotonic() >= deadline:
                raise UnsafeQuery("Query execution exceeded the time limit", "QUERY_TIMEOUT")
            return {"columns": columns, "rows": rows}
        except duckdb.InterruptException as error:
            raise UnsafeQuery("Query execution exceeded the time limit", "QUERY_TIMEOUT") from error
        except duckdb.Error as error:
            raise UnsafeQuery("DuckDB could not safely plan or execute the query") from error
        finally:
            cancellation.cancel()
            cancellation.join()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Publication directory containing latest.json")
    parser.add_argument("sql")
    args = parser.parse_args()
    snapshots = Snapshots(args.output)
    state = snapshots.latest()
    if state is None:
        parser.exit(1, "No published snapshot\n")
    try:
        result = query(snapshots.directory / state["database"], args.sql)
    except UnsafeQuery as error:
        parser.exit(1, f"Query declined: {error}\n")
    print(json.dumps(result, default=str, ensure_ascii=False))


if __name__ == "__main__":
    main()
