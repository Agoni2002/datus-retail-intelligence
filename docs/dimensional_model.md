# Dimensional model

## ODS and staging

The nine ODS tables are one row per source CSV record. ODS stores columns in contract order and preserves source values as VARCHAR, including leading zeroes and duplicate rows. DuckDB interprets CSV empty fields as NULL. Grain, candidate keys and relationships are listed in the [data dictionary](data_dictionary.md). ODS has no enforced keys or foreign keys so the quality gate can observe source violations.

## DWD

| Table | Grain and primary key | Foreign keys | Meaning and constraints |
| --- | --- | --- | --- |
| `fact_order` | One order, `order_id` | `customer_id → dim_customer`, `purchase_date → dim_date` | Order status and dates, separately aggregated merchandise, freight, payment and latest review. Required status and purchase time. Nonnegative item totals. |
| `fact_order_item` | One item position, `(order_id, order_item_id)` | Order, product, seller | Exact decimal BRL price and freight with positive item sequence and nonnegative money. |
| `fact_payment` | One tender entry, `(order_id, payment_sequence)` | Order | Tender type, installments and nonnegative amount. Payment sequence is positive. |
| `fact_review` | One review key within an order, `(order_id, review_id)` | Order | Score 1–5 and source text/timestamps. Review IDs are treated as order-scoped. |
| `dim_customer` | One order-scoped customer record, `customer_id` | ZIP prefix → geography | `customer_unique_id` is the cross-order repeat identity. Customer location uses source state and city. |
| `dim_product` | One product, `product_id` | None | Category code, label, and nullable physical properties. Category translation is resolved during load. |
| `dim_seller` | One seller, `seller_id` | ZIP prefix → geography | Source seller location. |
| `dim_date` | One calendar day, `date_key` | None | Continuous date spine between observed minimum and maximum supported source timestamps. |
| `dim_geography` | One ZIP prefix, `zip_prefix` | None | Most frequent valid normalized locality, with median coordinates from its points. When location samples are absent, customer and seller locality provides a fallback without coordinates. |

Item, payment, and latest-review summaries are prepared separately before the order join. For a multi-seller order, seller performance first groups items to the seller/order pair. Never sum the order monetary total alongside an item, payment, or review row without re-establishing the target grain.

## DWS and ADS

DWS and ADS are materialized from the same validated transaction, with primary keys at each documented grain. They use logical upstream relationships through SQL.

| Table | Grain and primary key | Meaning and constraints |
| --- | --- | --- |
| `dws_sales_daily` | Purchase date | Additive order, freight, merchandise and review inputs. |
| `dws_category_performance` | Purchase month + category code | Delivered category merchandise and overlapping order counts across categories. |
| `dws_seller_performance` | Purchase month + seller ID | Deduplicated seller participation and seller-owned item amounts. |
| `dws_delivery_performance` | Purchase month + customer state | Delivered and eligible counts, on-time and late counts, and sum of late days. |
| `dws_customer_retention` | Purchase month + cross-order customer ID | Delivered order counts for month-level repeats. Contains identifiers and is excluded from the guarded query interface. |
| `ads_executive_dashboard` | Purchase month | Published counts, additive amounts, and rates. Ratios with no eligible denominator are NULL. |
| `ads_seller_scorecard` | Purchase month + seller ID | Seller volume and cancellation rate with seller state. |
| `ads_delivery_alerts` | Purchase month + customer state | Regions at or above the configured late-delivery rate and eligible-order minimum. |
| `ads_sales_anomaly` | Purchase month | Absolute and percentage change versus the prior calendar month, with the configured decline flag. Missing or zero prior totals make the rate unknown. |
| `ads_sales_category_movement` | Purchase month + category code | Additive current-minus-prior category movements. Categories missing from one side contribute zero there. |
