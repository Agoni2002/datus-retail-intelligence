"""Create snapshot-governance panels from the accepted receipt and aggregates."""

from datetime import datetime, timezone


def governance(conn, receipt):
    def rows(sql):
        return conn.exec_driver_sql(sql).all()

    quality = receipt["quality"]
    checks = {check["name"]: check for check in quality["checks"]}
    warnings = [c for c in checks.values() if c["severity"] == "warning" and not c["passed"]]
    blockers = [c for c in checks.values() if c["severity"] == "error" and not c["passed"]]
    def violations(name):
        return checks[name]["violations"]

    source_rows = rows("SELECT SUM(source_rows) FROM control.source_watermark")[0][0]
    relations = rows("""
        SELECT table_schema, table_name FROM information_schema.tables
        WHERE table_schema IN ('ods', 'dwd', 'dws', 'ads') AND table_type='BASE TABLE'
        ORDER BY 1, 2
    """)
    totals = {key: [0, 0] for key in ("ods", "dwd", "dws", "ads")}
    for schema, table in relations:
        totals[schema][0] += 1
        totals[schema][1] += rows(f'SELECT COUNT(*) FROM "{schema}"."{table}"')[0][0]

    # This runs only during provisioning. The optional raw lookup checks are
    # required because DWD already applies fallback labels to these rows.
    customer_zip, seller_zip = rows("""
        WITH zip AS (
            SELECT DISTINCT CASE WHEN regexp_full_match(trim(geolocation_zip_code_prefix), '[0-9]{1,5}')
                 THEN lpad(trim(geolocation_zip_code_prefix), 5, '0')
                 ELSE trim(geolocation_zip_code_prefix) END AS prefix
            FROM ods.geolocation
        )
        SELECT (SELECT COUNT(*) FROM dwd.dim_customer c ANTI JOIN zip z ON c.zip_prefix=z.prefix),
               (SELECT COUNT(*) FROM dwd.dim_seller s ANTI JOIN zip z ON s.zip_prefix=z.prefix)
    """)[0]
    category_gaps = rows("""
        SELECT COUNT(*) FROM dwd.dim_product p ANTI JOIN ods.product_category_name_translation t
        ON p.category_code=trim(t.product_category_name)
        WHERE p.category_code <> '(unknown)'
    """)[0][0]
    anomalies = dict(rows("""
        SELECT status, COUNT(*) FROM dwd.fact_order
        WHERE approved_at < purchased_at OR carrier_at < purchased_at OR delivered_at < purchased_at
           OR delivered_at < carrier_at OR estimated_delivery_at::DATE < purchased_at::DATE
        GROUP BY status ORDER BY status
    """))
    excluded, missing_delivery, missing_pay, amount_diff, start, end = rows("""
        SELECT COUNT(*) FILTER (WHERE status='delivered' AND NOT delivery_eligible),
               COUNT(*) FILTER (WHERE status='delivered' AND delivered_at IS NULL),
               COUNT(*) FILTER (WHERE status='delivered' AND payment_brl IS NULL),
               COUNT(*) FILTER (
                   WHERE status='delivered' AND abs(payment_brl-merchandise_brl-freight_brl)>0.02),
               MIN(purchase_date), MAX(purchase_date)
        FROM dwd.fact_order
    """)[0]
    review_end = rows("SELECT MAX(created_at)::DATE FROM dwd.fact_review")[0][0]
    tail = list(reversed(rows("""
        SELECT month_start, orders, delivered_orders FROM ads.ads_executive_dashboard
        ORDER BY month_start DESC LIMIT 2
    """)))
    tail_months = " and ".join(month.strftime("%B %Y") for month, *_ in tail)
    time = datetime.fromtimestamp(receipt["publication_manifest_timestamp"], timezone.utc)
    tail_delivered = sum(row[2] for row in tail)
    coverage = (f"Purchases span {start} to {end}. {tail_months} contain "
                f"{sum(row[1] for row in tail):,} orders and {tail_delivered:,} delivered orders.")
    if not tail_delivered:
        coverage += " Treat these edge months as sparse extract coverage."
    layer_text = "\n".join(f"| {name.upper()} | {n} | {count:,} |" for name, (n, count) in totals.items())
    summary = f"""### Published snapshot

**{source_rows:,} source rows** · **{len(checks)} checks** · **{len(blockers)} blockers** · **{len(warnings)} warnings**

Version `{receipt['version']}`. Published {time:%Y-%m-%d %H:%M:%S UTC} (publication manifest timestamp).

| Layer | Tables | Rows |
| --- | ---: | ---: |
{layer_text}"""
    limitations = f"""### Data limitations

- Geography checks found {violations('geolocation.duplicate_key_rows'):,} exact duplicate geolocation records. {customer_zip:,} customers and {seller_zip:,} sellers have no geographic match. {category_gaps:,} products have no category translation.
- Delivery checks found {violations('orders.timeline'):,} timestamp anomalies ({', '.join(f'{n:,} {status}' for status, n in anomalies.items())}). {missing_delivery:,} delivered orders lack an actual delivery timestamp. {excluded:,} delivered orders are excluded from the on-time denominator.
- Payment reconciliation flagged {violations('reconciliation.payment_values'):,} delivered orders, including {missing_pay:,} missing payment and {amount_diff:,} differences over BRL 0.02.
- Latest review date was {review_end}, {(end-review_end).days} days before the last purchase."""
    return coverage, (summary, limitations)
