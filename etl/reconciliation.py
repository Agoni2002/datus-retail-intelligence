"""Cross-layer gates in addition to the row-level source checks."""

from etl.config import ROOT
from quality.checks import count

DIRECT = {
    "orders": "fact_order", "order_items": "fact_order_item", "order_payments": "fact_payment",
    "order_reviews": "fact_review", "customers": "dim_customer", "products": "dim_product", "sellers": "dim_seller",
}


def reconcile(conn, report, settings):
    for name, table in DIRECT.items():
        removed = next(check.violations for check in report.checks if check.name == f"{name}.duplicate_key_rows")
        raw_count = count(conn, f"SELECT count(*) FROM ods.{name}")
        fact_count = count(conn, f"SELECT count(*) FROM dwd.{table}")
        report.add(f"reconciliation.ods_to_dwd.{name}", abs(raw_count - removed - fact_count),
                   detail=f"Raw {raw_count}; duplicates removed {removed}; loaded {fact_count}")
    report.add("reconciliation.ods_to_dwd.geography", count(conn, """
        WITH zip_prefixes AS (
            SELECT geolocation_zip_code_prefix AS zip_prefix FROM stg_geolocation
            WHERE regexp_full_match(geolocation_zip_code_prefix, '[0-9]{5}')
              AND geolocation_lat BETWEEN -90 AND 90 AND geolocation_lng BETWEEN -180 AND 180
            UNION SELECT customer_zip_code_prefix FROM stg_customers
            UNION SELECT seller_zip_code_prefix FROM stg_sellers
        )
        SELECT count(*) FROM zip_prefixes s FULL JOIN dwd.dim_geography d USING (zip_prefix)
        WHERE s.zip_prefix IS NULL OR d.zip_prefix IS NULL
    """))
    report.add("reconciliation.ods_to_dwd.category_translation", count(conn, """
        SELECT count(*) FROM stg_products p
        LEFT JOIN stg_product_category_name_translation t USING (product_category_name)
        JOIN dwd.dim_product d USING (product_id)
        WHERE d.category_name IS DISTINCT FROM coalesce(t.product_category_name_english,
                                                         p.product_category_name, '(unknown)')
    """))
    report.add("reconciliation.payment_values", count(conn, """
        SELECT count(*) FROM dwd.fact_order
        WHERE status = 'delivered' AND (payment_brl IS NULL OR abs(payment_brl - merchandise_brl - freight_brl) > ?)
    """, [settings.payment_tolerance_brl]), settings.payment_mismatch_severity,
        "Delivered orders with missing or out-of-tolerance payments versus merchandise plus freight.")
    for name, violations in conn.execute((ROOT / "metrics/calculations.sql").read_text()).fetchall():
        report.add(f"reconciliation.{name}", violations)
