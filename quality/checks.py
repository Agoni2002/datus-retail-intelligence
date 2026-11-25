"""Source validation, typed staging, deterministic deduplication and quality checks."""

from ingestion.contract import REAL, RELATIONSHIPS, SOURCES, TEXT, TS, identifier, text_value, typed_value


def count(conn, query, params=None):
    return conn.execute(query, params or []).fetchone()[0]


def stage(conn, report):
    for name, source in SOURCES.items():
        schema = conn.execute(f"DESCRIBE ods.{name}").fetchall()
        expected = [(column, "VARCHAR") for column in source.columns]
        report.add(f"{name}.ods_schema", [(r[0], r[1]) for r in schema] != expected)
        report.require_pass()
        typed = ", ".join(f"{typed_value(col, kind)} AS {identifier(col)}" for col, kind in source.columns.items())
        conn.execute(f"CREATE TEMP TABLE typed_{name} AS SELECT {typed} FROM ods.{name}")
        requirements = dict.fromkeys(source.key + source.required)
        for col, kind in source.columns.items():
            quoted = identifier(col)
            if kind != TEXT:
                expression = typed_value(col, kind)
                bad = f"{text_value(col)} IS NOT NULL AND ({expression}) IS NULL"
                if kind == REAL:
                    bad = f"({bad}) OR NOT isfinite({expression})"
                report.add(f"{name}.{col}.type", count(conn, f"SELECT count(*) FROM ods.{name} WHERE {bad}"))
            if col in requirements:
                report.add(f"{name}.{col}.required",
                           count(conn, f"SELECT count(*) FROM typed_{name} WHERE {quoted} IS NULL"))
            if kind == TS:
                check(conn, report, f"{name}.{col}.supported_year", f"typed_{name}",
                      f"NOT isfinite({quoted}) OR year({quoted}) NOT BETWEEN 1900 AND 2100")
        key = ", ".join(map(identifier, source.key))
        ordered = dict.fromkeys((*source.newest, *source.columns))
        sorting = ", ".join(f"{identifier(c)} {'DESC' if c in source.newest else 'ASC'} NULLS LAST"
                            for c in ordered)
        conn.execute(f"""
            CREATE TEMP TABLE stg_{name} AS
            SELECT * FROM typed_{name} QUALIFY row_number() OVER (PARTITION BY {key} ORDER BY {sorting}) = 1
        """)
        raw_rows = count(conn, f"SELECT count(*) FROM typed_{name}")
        staged_rows = count(conn, f"SELECT count(*) FROM stg_{name}")
        variants = count(conn, f"SELECT count(*) FROM (SELECT DISTINCT * FROM typed_{name})")
        report.add(f"{name}.duplicate_key_rows", raw_rows - staged_rows, "warning",
                   f"Identical rows removed: {raw_rows - variants}; conflicting variants removed: {variants - staged_rows}")
        report.add(f"{name}.staged_unique", count(conn, f"""
            SELECT count(*) FROM (SELECT {key} FROM stg_{name} GROUP BY {key} HAVING count(*) > 1)
        """))
        conn.execute(f"DROP TABLE typed_{name}")


def check(conn, report, name, table, predicate, severity="error", detail=""):
    report.add(name, count(conn, f"SELECT count(*) FROM {table} WHERE {predicate}"), severity, detail)


def validate_sources(conn, report, settings):
    for child, field, parent, key in RELATIONSHIPS:
        report.add(f"{child}.{field}.foreign_key", count(conn, f"""
            SELECT count(*) FROM stg_{child} c ANTI JOIN stg_{parent} p ON c.{field} = p.{key}
        """))
    check(conn, report, "orders.valid_status", "stg_orders",
          """order_status NOT IN ('created', 'approved', 'invoiced', 'processing', 'shipped',
                                  'delivered', 'unavailable', 'canceled')""")
    check(conn, report, "orders.timeline", "stg_orders", """
        order_approved_at < order_purchase_timestamp OR order_delivered_carrier_date < order_purchase_timestamp
        OR order_delivered_customer_date < order_purchase_timestamp
        OR order_delivered_customer_date < order_delivered_carrier_date
        OR order_estimated_delivery_date::DATE < order_purchase_timestamp::DATE
    """, "warning", "Orders with inconsistent delivery chronology are ineligible for the delivery KPI.")
    check(conn, report, "orders.delivered_timestamps", "stg_orders", """
        order_status = 'delivered' AND (order_delivered_customer_date IS NULL OR order_estimated_delivery_date IS NULL)
    """, "warning")
    report.add("orders.delivered_without_items", count(conn, """
        SELECT count(*) FROM stg_orders o ANTI JOIN stg_order_items i USING (order_id)
        WHERE o.order_status = 'delivered'
    """), "warning")
    check(conn, report, "items.monetary_values", "stg_order_items", "price < 0 OR freight_value < 0")
    check(conn, report, "items.positive_sequence", "stg_order_items", "order_item_id <= 0")
    check(conn, report, "payments.valid_amount_and_sequence", "stg_order_payments",
          "payment_value < 0 OR payment_sequential <= 0 OR payment_installments < 0")
    check(conn, report, "reviews.valid_score", "stg_order_reviews", "review_score NOT BETWEEN 1 AND 5")
    check(conn, report, "reviews.timeline", "stg_order_reviews",
          "review_answer_timestamp < review_creation_date", "warning")
    for table, label in (("stg_customers", "customer"), ("stg_sellers", "seller")):
        check(conn, report, f"{label}.location_format", table,
              f"NOT regexp_full_match({label}_zip_code_prefix, '[0-9]{{5}}') "
              f"OR NOT regexp_full_match({label}_state, '[A-Za-z]{{2}}')")
    check(conn, report, "geolocation.coordinates", "stg_geolocation",
          """NOT regexp_full_match(geolocation_zip_code_prefix, '[0-9]{5}')
             OR geolocation_lat NOT BETWEEN -90 AND 90 OR geolocation_lng NOT BETWEEN -180 AND 180""",
          "warning", "Invalid coordinate samples are excluded from geography rollups.")
    latest_order = count(conn, "SELECT max(order_purchase_timestamp)::DATE FROM stg_orders")
    report.add("freshness.orders_not_empty", latest_order is None)
    if latest_order is None:
        return
    reference_date = settings.as_of_date or latest_order
    report.reference_date = reference_date.isoformat()
    order_age = (reference_date - latest_order).days
    report.add("freshness.orders", not 0 <= order_age <= settings.max_order_age_days,
               detail=f"Latest purchase age: {order_age} days")
    for table, time_column in (("order_items", "shipping_limit_date"), ("order_reviews", "review_creation_date")):
        latest = count(conn, f"SELECT max({time_column})::DATE FROM stg_{table}")
        lag = (reference_date - latest).days if latest else None
        report.add(f"freshness.{table}", lag is None or lag > settings.max_source_lag_days, "warning",
                   f"Latest extract event lag: {lag} days")
