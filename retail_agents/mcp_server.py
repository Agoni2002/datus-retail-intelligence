"""Datus stdio MCP server for curated retail context and guarded execution."""

import argparse
import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from uuid import uuid4

from datus.tools.semantic_tools.dosi.config import DosiConfig
from datus.tools.semantic_tools.dosi.runtime import DosiRuntime
from mcp.server.fastmcp import FastMCP

from etl.config import ROOT
from retail_agents.context_index import retrieve
from retail_agents.safe_query import Limits, UnsafeQuery, query, validate_sql

SERVER = "retail"
TOOLS = frozenset({"retail_context", "retail_query", "retail_metric"})
SDK_TOOLS = frozenset(f"mcp__{SERVER}__{name}" for name in TOOLS)
METRICS = frozenset({"delivered_gmv", "delivered_order_count"})


class RetailTools:
    def __init__(self, snapshot: Path, index_dir: Path, index_id: str, audit: Path, run_id: str):
        self.snapshot = snapshot
        self.index_dir = index_dir
        self.index_id = index_id
        self.audit = audit
        self.run_id = run_id
        self.dosi = DosiRuntime(DosiConfig(
            dialect="duckdb",
            semantic_model_path=str(ROOT / "agents/semantic/retail_fulfillment.yml"),
        ))

    def audit_result(self, tool, request_id, started, outcome, *, rows=None, code=None):
        # The audit is deliberately independent of model text and tool payloads.
        event = {
            "ts_utc": datetime.now(UTC).isoformat(), "run_id": self.run_id,
            "request_id": request_id, "tool": tool, "outcome": outcome,
            "elapsed_ms": round((monotonic() - started) * 1000, 2),
            "snapshot_version": self.snapshot.stem, "row_count": rows, "error_code": code,
        }
        fd = os.open(self.audit, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, separators=(",", ":")) + "\n")

    def failure(self, tool, request_id, started, code, message):
        self.audit_result(tool, request_id, started, "denied", code=code)
        return {"ok": False, "request_id": request_id, "error": {"code": code, "message": message}}

    def execute(self, tool, request_id, started, statement):
        try:
            _, schema, table = validate_sql(statement, Limits())
            result = query(self.snapshot, statement)
        except UnsafeQuery as error:
            return self.failure(tool, request_id, started, error.code, str(error))
        except Exception:
            return self.failure(tool, request_id, started, "QUERY_UNAVAILABLE",
                                "The published retail query could not be completed.")
        self.audit_result(tool, request_id, started, "allowed", rows=len(result["rows"]))
        return {"ok": True, "request_id": request_id, "snapshot_version": self.snapshot.stem,
                "source_table": f"{schema}.{table}", **json.loads(json.dumps(result, default=str, allow_nan=False))}

    def retail_query(self, sql: str) -> dict:
        """Query one approved serving table with a single bounded DuckDB SELECT."""
        return self.execute("retail_query", uuid4().hex, monotonic(), sql)

    async def retail_metric(self, metrics: list[str]) -> dict:
        """Run monthly delivered_gmv and/or delivered_order_count using the published Dosi model."""
        request_id, started = uuid4().hex, monotonic()
        if not metrics or len(metrics) > len(METRICS) or len(set(metrics)) != len(metrics) or not set(metrics) <= METRICS:
            return self.failure("retail_metric", request_id, started, "UNKNOWN_METRIC",
                                "Select distinct supported metrics: delivered_gmv and delivered_order_count.")
        try:
            # This is AskMetrics' Dosi runtime in compilation-only mode, with no DB connection.
            compiled = await self.dosi.query_metrics(
                metrics, dimensions=["metric_time"], time_granularity="month",
                dry_run=True,
            )
            statement = compiled.data[0]["sql"]
        except Exception:
            return self.failure("retail_metric", request_id, started, "SEMANTIC_UNAVAILABLE",
                                "Dosi could not compile the published metric definitions.")
        result = self.execute("retail_metric", request_id, started, statement)
        if result["ok"]:
            result["rows"].sort(key=lambda row: row[0])
            result["metric_ids"] = metrics
        return result

    def retail_context(self, question: str, kind: str = "", top_n: int = 3) -> dict:
        """Find curated business, table, column, relationship, metric, or reference context."""
        request_id, started = uuid4().hex, monotonic()
        try:
            items = retrieve(self.index_dir, self.index_id, question, kind, top_n)
        except ValueError as error:
            return self.failure("retail_context", request_id, started, "INVALID_CONTEXT_REQUEST",
                                str(error) if str(error) in {"Unknown context kind", "Use 1–300 search characters and 1–5 results"}
                                else "The context request is invalid.")
        except Exception:
            return self.failure("retail_context", request_id, started, "CONTEXT_UNAVAILABLE",
                                "The published retail context index could not be read.")
        self.audit_result("retail_context", request_id, started, "allowed", rows=len(items))
        return {"ok": True, "request_id": request_id, "items": items}


def main():
    # Reserve stdout for the MCP JSON-RPC transport.
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--index-dir", type=Path, required=True)
    parser.add_argument("--index-id", required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    service = RetailTools(args.snapshot, args.index_dir, args.index_id, args.audit, args.run_id)
    server = FastMCP(SERVER)
    for name in sorted(TOOLS):
        server.add_tool(getattr(service, name), name=f"mcp__{SERVER}__{name}")
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
