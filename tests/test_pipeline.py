import csv
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import date
from decimal import Decimal

import duckdb
import pytest

from etl.config import Settings
from etl.pipeline import PipelineFailure, run
from etl.reconciliation import reconcile
from etl.snapshot import Snapshots
from ingestion.contract import source_filename
from ingestion.schema_inspector import inspect
from quality.checks import stage
from quality.reports import Report


def edit(source, name, fn):
    path = source / source_filename(name)
    with path.open(newline="") as stream:
        header, *rows = list(csv.reader(stream))
    with path.open("w", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(fn(rows))


def one(path, sql):
    with closing(duckdb.connect(str(path), read_only=True)) as conn:
        return conn.execute(sql).fetchone()


def failures(output):
    return [check for path in (output / "quality").glob("*.failed.json")
            for check in json.loads(path.read_text())["checks"] if check["violations"]]


def test_inspection_and_ingestion(source, built):
    _, _, db = built
    report = inspect(source)
    assert len(report["tables"]) == 9
    assert report["tables"]["orders"]["rows"] == 7
    assert report["tables"]["order_items"]["columns"][5]["expected_type"] == "DECIMAL(18,2)"
    assert report["tables"]["orders"]["columns"][7]["null_ratio"] == pytest.approx(4 / 7)
    assert report["candidate_relationships"][0]["unmatched_nonnull_rows"] == 0
    assert one(db, "SELECT count(*) FROM ods.geolocation") == (3,)
    assert one(db, "SELECT customer_zip_code_prefix FROM ods.customers WHERE customer_id='c1'") == ("01001",)
    assert one(db, "SELECT comment_message FROM dwd.fact_review WHERE review_id='r2'") == ("Follow-up.\nAll good.",)


def test_header_reordering_is_supported(source, tmp_path):
    path = source / source_filename("sellers")
    with path.open(newline="") as stream:
        rows = list(csv.reader(stream))
    with path.open("w", newline="") as stream:
        csv.writer(stream).writerows([row[::-1] for row in rows])
    out = tmp_path / "out"
    result = run(source, out)
    assert one(out / result["database"], "SELECT state FROM dwd.dim_seller WHERE seller_id='s1'") == ("SP",)


def test_original_export_zip_and_nullable_integer_formats(source, tmp_path):
    def zip_without_zero(rows):
        rows[0][2] = "1001"
        return rows

    def integer_with_decimal(rows):
        rows[0][2] = "12.0"
        rows[0][4] = "2.0"
        return rows

    edit(source, "customers", zip_without_zero)
    edit(source, "products", integer_with_decimal)
    out = tmp_path / "out"
    result = run(source, out)
    db = out / result["database"]
    assert one(db, "SELECT customer_zip_code_prefix FROM ods.customers WHERE customer_id='c1'") == ("1001",)
    assert one(db, "SELECT zip_prefix FROM dwd.dim_customer WHERE customer_id='c1'") == ("01001",)
    assert one(db, "SELECT name_length, photo_count FROM dwd.dim_product WHERE product_id='p1'") == (12, 2)
    report = inspect(source)
    assert report["tables"]["products"]["columns"][2]["invalid_casts"] == 0


def test_optional_header_only_source(source, tmp_path):
    edit(source, "order_reviews", lambda _: [])
    out = tmp_path / "out"
    result = run(source, out)
    assert one(out / result["database"], "SELECT count(*) FROM ods.order_reviews") == (0,)
    assert one(out / result["database"], "SELECT sum(average_review_score) FROM ads.ads_executive_dashboard") == (None,)


def test_schema_drift_fails_before_publication(source, tmp_path):
    path = source / source_filename("orders")
    path.write_text(path.read_text().replace("order_status", "status", 1))
    out = tmp_path / "out"
    with pytest.raises(PipelineFailure):
        run(source, out)
    assert not (out / "latest.json").exists()
    assert failures(out)[0]["detail"] == "SourceError"


@pytest.mark.parametrize(("table", "column", "value", "check"), [
    ("order_items", 1, "1.5", "order_items.order_item_id.type"),
    ("order_items", 5, "60.015", "order_items.price.type"),
    ("orders", 0, "", "orders.order_id.required"),
    ("orders", 3, "yesterday", "orders.order_purchase_timestamp.type"),
    ("orders", 3, "infinity", "orders.order_purchase_timestamp.supported_year"),
    ("orders", 2, "cancelled", "orders.valid_status"),
    ("order_items", 3, "missing_seller", "order_items.seller_id.foreign_key"),
    ("order_payments", 4, "-3", "payments.valid_amount_and_sequence"),
])
def test_bad_data_blocks_and_reports(source, tmp_path, table, column, value, check):
    def mutate(rows):
        rows[0][column] = value
        return rows

    edit(source, table, mutate)
    out = tmp_path / "out"
    with pytest.raises(PipelineFailure):
        run(source, out)
    assert check in {c["name"] for c in failures(out)}


def test_foreign_key_is_enforced_and_dedup_is_deterministic(tmp_path, source):
    out = tmp_path / "out"

    def duplicates(rows):
        older = rows[0].copy()
        older[5:7] = ["", ""]
        older[2] = "shipped"
        return [older, rows[0], *rows]

    edit(source, "orders", duplicates)
    result = run(source, out)
    db = out / result["database"]
    assert one(db, "SELECT count(*) FROM ods.orders") == (9,)
    assert one(db, "SELECT count(*), max(status) FROM dwd.fact_order WHERE order_id='o1'") == (1, "delivered")
    report = json.loads((out / result["quality_report"]).read_text())
    duplicates = next(c for c in report["checks"] if c["name"] == "orders.duplicate_key_rows")
    assert report["passed"] and duplicates["violations"] == 2
    # Use a private copy to exercise the table constraints without altering a published version.
    writable = tmp_path / "copy.duckdb"
    writable.write_bytes(db.read_bytes())
    with closing(duckdb.connect(str(writable))) as conn:
        with pytest.raises(duckdb.ConstraintException):
            conn.execute("INSERT INTO dwd.fact_order SELECT * FROM dwd.fact_order LIMIT 1")
        with pytest.raises(duckdb.ConstraintException):
            conn.execute("INSERT INTO dwd.fact_payment VALUES ('missing', 1, 'voucher', 1, 10)")


def test_fanout_nulls_and_reconciled_metrics(built):
    output, manifest, db = built
    assert one(db, """
        SELECT order_id, item_count, merchandise_brl, freight_brl, payment_brl, latest_review_score
        FROM dwd.fact_order WHERE order_id='o1'
    """) == ("o1", 2, Decimal("100"), Decimal("9"), Decimal("109"), 5)
    assert one(db, """
        SELECT delivered_gmv_brl, delivered_orders, cancellation_rate, delivery_eligible_orders,
               on_time_delivery_rate, average_late_delivery_days, average_review_score, repeat_purchase_rate
        FROM ads.ads_executive_dashboard WHERE month_start=DATE '2018-01-01'
    """) == (Decimal("200"), 3, .25, 2, .5, 3., 4., .5)
    assert one(db, "SELECT is_on_time, late_days FROM dwd.fact_order WHERE order_id='o3'") == (None, None)
    assert one(db, "SELECT category_name FROM dwd.dim_product WHERE product_id='p3'") == ("(unknown)",)
    report = json.loads((output / manifest["quality_report"]).read_text())
    assert report["passed"]
    assert all(c["passed"] for c in report["checks"] if c["name"].startswith("reconciliation."))


def test_independent_reconciliation_detects_metric_drift(tmp_path, built):
    _, manifest, db = built
    file = tmp_path / "copy.duckdb"
    file.write_bytes(db.read_bytes())
    with closing(duckdb.connect(str(file))) as conn:
        report = Report(manifest["version"])
        stage(conn, report)
        conn.execute("UPDATE ads.ads_executive_dashboard SET delivered_gmv_brl=999 WHERE month_start='2018-01-01'")
        reconcile(conn, report, Settings())
    assert not report.passed
    assert any(c.violations for c in report.checks if c.name == "reconciliation.independent_to_ads.monthly_metrics")


def test_explicit_freshness_sla(tmp_path, source):
    with pytest.raises(PipelineFailure, match="freshness.orders"):
        run(source, tmp_path / "out", replace(Settings(), as_of_date=date(2018, 6, 1)))


def test_configured_payment_mismatch_can_block_publication(tmp_path, source):
    edit(source, "order_payments", lambda rows: rows[1:])
    with pytest.raises(PipelineFailure, match="reconciliation.payment_values"):
        run(source, tmp_path / "out", replace(Settings(), payment_mismatch_severity="error"))


def test_incremental_corrections_deletions_and_idempotency(tmp_path, source):
    out = tmp_path / "out"
    initial = run(source, out)
    old_db = out / initial["database"]
    first_bytes = hashlib.sha256(old_db.read_bytes()).digest()
    assert run(source, out)["outcome"] == "unchanged"
    assert len(list((out / "snapshots").glob("*.duckdb"))) == 1

    def correct_and_delete(rows):
        rows[0][5] = "65"
        return [row for row in rows if row[0] != "o7"]

    edit(source, "order_items", correct_and_delete)
    with closing(duckdb.connect(str(old_db), read_only=True)) as pinned_reader:
        next_run = run(source, out)
        assert pinned_reader.execute("SELECT sum(merchandise_brl) FROM dwd.fact_order WHERE status='delivered'").fetchone() == (280,)
    new_db = out / next_run["database"]
    assert next_run["changed_sources"] == ["order_items"]
    assert next_run["previous_version"] == initial["version"]
    assert one(new_db, "SELECT sum(delivered_gmv_brl) FROM ads.ads_executive_dashboard") == (285,)
    assert one(new_db, "SELECT count(*) FROM dwd.fact_order_item WHERE order_id='o7'") == (0,)
    assert one(new_db, """
        SELECT last_changed_version FROM control.source_watermark WHERE source_name='orders'
    """) == (initial["version"],)
    assert one(new_db, """
        SELECT last_changed_version FROM control.source_watermark WHERE source_name='order_items'
    """) == (next_run["version"],)
    assert hashlib.sha256(old_db.read_bytes()).digest() == first_bytes
    assert run(source, out)["version"] == next_run["version"]
    assert os.stat(new_db).st_mode & 0o222 == 0
    with closing(duckdb.connect(str(new_db), read_only=True)) as conn:
        with pytest.raises(duckdb.Error):
            conn.execute("DELETE FROM dwd.fact_order")


def test_recovery_preserves_last_good_watermarks(tmp_path, source, monkeypatch):
    out = tmp_path / "out"
    initial = run(source, out)
    edit(source, "order_reviews", lambda rows: rows[:-1])

    def cannot_publish(self, working, report, state):
        raise OSError("simulated interruption before publication")

    with monkeypatch.context() as patch:
        patch.setattr(Snapshots, "publish", cannot_publish)
        with pytest.raises(PipelineFailure):
            run(source, out)
    assert json.loads((out / "latest.json").read_text())["version"] == initial["version"]
    recovered = run(source, out)
    assert recovered["changed_sources"] == ["order_reviews"]
    assert one(out / recovered["database"], "SELECT count(*) FROM dwd.fact_review") == (3,)


def test_duplicate_writers_serialize(tmp_path, source):
    out = tmp_path / "out"
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, source, out) for _ in range(2)]
        results = [f.result(timeout=20) for f in futures]
    assert sorted(r["outcome"] for r in results) == ["published", "unchanged"]
    assert results[0]["version"] == results[1]["version"]
