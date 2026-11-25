"""Build and retrieve curated retail context using Datus' LanceDB FTS backend."""

import fcntl
import hashlib
import json
import re
from contextlib import closing
from pathlib import Path

import duckdb
import pandas as pd
import pyarrow as pa
import yaml
from datus.storage.fts import FtsField, FtsSpec
from datus.storage.vector.lance_backend import LanceVectorBackend
from datus_storage_base.conditions import eq

from etl.config import ROOT
from etl.snapshot import atomic_json
from retail_agents.safe_query import APPROVED

DOCS = (
    "business_requirements", "data_dictionary", "dimensional_model", "metric_dictionary", "data_quality",
)
FIELDS = ("kind", "source", "title", "body")
INDEX = FtsSpec((FtsField("title", boost=3), FtsField("body")))
KINDS = frozenset({"business", "table", "column", "relationship", "metric", "reference"})
TABLE = "retail_context"

RELATIONSHIPS = {
    "order_items to orders": "Join dwd.fact_order_item.order_id to dwd.fact_order.order_id, many to one. "
                            "Aggregate item amounts to one row per order before joining payment or review summaries.",
    "payments to orders": "Join dwd.fact_payment.order_id to dwd.fact_order.order_id, many to one. "
                          "Never use payment entries as delivered merchandise GMV.",
    "reviews to orders": "Join dwd.fact_review.order_id to dwd.fact_order.order_id, many to one.",
    "orders to customers and geography": "Join dwd.fact_order.customer_id to dwd.dim_customer.customer_id, "
                                        "then dim_customer.zip_prefix to dim_geography.zip_prefix. "
                                        "Use the order customer's state for fulfillment and customer_unique_id for repeats.",
    "items to products and sellers": "Join dwd.fact_order_item.product_id to dwd.dim_product.product_id "
                                     "and seller_id to dwd.dim_seller.seller_id. Seller order counts overlap.",
}


def context_rows(snapshot: Path):
    def record(kind, source, title, body):
        return dict(kind=kind, source=source, title=title, body=body.strip())

    rows = []
    for name in DOCS:
        source = f"docs/{name}.md"
        text = (ROOT / source).read_text()
        sections = re.split(r"(?m)^(?:#{1,3}) (.+)\n", text)
        for title, body in zip(sections[1::2], sections[2::2], strict=True):
            if body.strip():
                rows.append(record("business", source, title, body))
    for title, body in RELATIONSHIPS.items():
        rows.append(record("relationship", "docs/dimensional_model.md", title, body))
    metrics = yaml.safe_load((ROOT / "metrics/definitions.yml").read_text())["metrics"]
    for metric, fields in metrics.items():
        rows.append(record("metric", "metrics/definitions.yml", metric.replace("_", " "),
                           yaml.safe_dump(fields, sort_keys=False).strip()))
    for case in yaml.safe_load((ROOT / "benchmark/questions.yml").read_text()):
        # Expected fixture outcomes stay in the evaluator. The agent retrieves SQL examples.
        rows.append(record("reference", "benchmark/questions.yml", case["question"], case["sql"]))
    for source in sorted((ROOT / "agents/reference_sql").glob("*.sql")):
        rows.append(record("reference", str(source.relative_to(ROOT)),
                           source.stem.replace("_", " "), source.read_text()))
    with closing(duckdb.connect(str(snapshot), read_only=True, config={"enable_external_access": "false"})) as conn:
        for schema, table in sorted(APPROVED):
            fields = conn.execute("""
                SELECT column_name, data_type FROM duckdb_columns()
                WHERE database_name = current_database() AND schema_name = ? AND table_name = ?
                ORDER BY column_index
            """, [schema, table]).fetchall()
            if not fields:
                raise ValueError(f"Published snapshot lacks approved table {schema}.{table}")
            table_name = f"{schema}.{table}"
            rows.append(record("table", "published warehouse schema", table_name,
                               "; ".join(f"{column} {kind}" for column, kind in fields)))
            for name, kind in fields:
                rows.append(record("column", "published warehouse schema", f"{table_name}.{name}",
                                   f"Column {name.replace('_', ' ')} in {table_name}. DuckDB type {kind}."))
    return rows


def database(directory: Path, index_id: str):
    if not re.fullmatch(r"retail-[0-9a-f]{24}", index_id):
        raise ValueError("Invalid retail context index identifier")
    backend = LanceVectorBackend()
    backend.initialize({"data_dir": str(directory)})
    return backend.connect(index_id)


def build(snapshot: Path, directory: Path):
    rows = context_rows(snapshot)
    digest = hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]
    index_id = f"retail-{digest}"
    # Serialize the build with the same local flock protocol used by warehouse publication.
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".index.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        marker = directory / f"{index_id}.json"
        if marker.exists():
            return json.loads(marker.read_text())
        db = database(directory, index_id)
        db.drop_table(TABLE, ignore_missing=True)
        table = db.create_table(TABLE, schema=pa.schema([pa.field(f, pa.string()) for f in FIELDS]))
        table.add(pd.DataFrame(rows, columns=FIELDS))
        table.create_fts_index(INDEX)
        report = {"index_id": index_id, "counts": {k: sum(r["kind"] == k for r in rows) for k in sorted(KINDS)},
                  "documents": sorted({r["source"] for r in rows})}
        atomic_json(marker, report)
        return report


def retrieve(directory: Path, index_id: str, question: str, kind: str = "", top_n: int = 3):
    if kind and kind not in KINDS:
        raise ValueError("Unknown context kind")
    if not question.strip() or len(question) > 300 or not 1 <= top_n <= 5:
        raise ValueError("Use 1–300 search characters and 1–5 results")
    table = database(directory, index_id).open_table(TABLE)
    result = table.search_fts(question.replace("_", " "), INDEX, top_n, eq("kind", kind) if kind else None,
                              select_fields=[*FIELDS, "_score"]).to_pylist()
    return [{k: item[k] for k in FIELDS if k != "body"} | {"body": item["body"][:4800]} for item in result]
