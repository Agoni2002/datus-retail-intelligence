-- Independent KPI calculation at normalized source grains. Only compare
-- additive numerators/denominators before comparing the published ratios.
WITH item_by_order AS (
    SELECT order_id, sum(price) gmv, sum(freight_value) freight FROM stg_order_items GROUP BY 1
),
review_by_order AS (
    SELECT order_id, first(review_score ORDER BY review_answer_timestamp DESC NULLS LAST,
                         review_creation_date DESC NULLS LAST, review_id DESC) score
    FROM stg_order_reviews GROUP BY 1
),
source_orders AS (
    SELECT date_trunc('month', o.order_purchase_timestamp)::DATE month_start, o.order_id, c.customer_unique_id,
           c.customer_state, o.order_status = 'delivered' delivered, o.order_status = 'canceled' canceled,
           CASE WHEN o.order_status = 'delivered'
                 AND o.order_delivered_customer_date >= o.order_purchase_timestamp
                 AND o.order_estimated_delivery_date::DATE >= o.order_purchase_timestamp::DATE
                 AND coalesce(o.order_delivered_carrier_date >= o.order_purchase_timestamp
                              AND o.order_delivered_customer_date >= o.order_delivered_carrier_date, true)
                 AND coalesce(o.order_approved_at >= o.order_purchase_timestamp, true)
                THEN date_diff('day', o.order_estimated_delivery_date::DATE,
                                      o.order_delivered_customer_date::DATE) END delivery_delta,
           coalesce(i.gmv, 0) gmv, coalesce(i.freight, 0) freight, r.score
    FROM stg_orders o JOIN stg_customers c USING (customer_id)
    LEFT JOIN item_by_order i USING (order_id) LEFT JOIN review_by_order r USING (order_id)
),
source_metrics AS (
    SELECT month_start, count(*) orders, count(*) FILTER (delivered) delivered_orders,
           count(*) FILTER (canceled) canceled_orders, coalesce(sum(gmv) FILTER (delivered), 0) delivered_gmv_brl,
           coalesce(sum(freight) FILTER (delivered), 0) freight_revenue_brl,
           count(*) FILTER (delivery_delta <= 0) on_time_orders, count(delivery_delta) delivery_eligible_orders,
           count(*) FILTER (delivery_delta > 0) late_orders,
           avg(delivery_delta) FILTER (delivery_delta > 0) average_late_delivery_days,
           count(score) FILTER (delivered) reviewed_orders, avg(score) FILTER (delivered) average_review_score
    FROM source_orders GROUP BY 1
),
source_by_customer AS (
    SELECT month_start, customer_unique_id, count(*) orders FROM source_orders WHERE delivered GROUP BY 1, 2
),
source_repeat AS (
    SELECT month_start, count(*) delivered_customers, count(*) FILTER (orders > 1) repeat_customers
    FROM source_by_customer GROUP BY 1
),
reference AS (
    SELECT m.*, delivered_gmv_brl / nullif(delivered_orders, 0) average_order_value_brl,
           canceled_orders / nullif(orders, 0) cancellation_rate,
           on_time_orders / nullif(delivery_eligible_orders, 0) on_time_delivery_rate,
           coalesce(delivered_customers, 0) delivered_customers, coalesce(repeat_customers, 0) repeat_customers,
           repeat_customers / nullif(delivered_customers, 0) repeat_purchase_rate
    FROM source_metrics m LEFT JOIN source_repeat r USING (month_start)
),
published AS (
    SELECT month_start, orders, delivered_orders, canceled_orders, delivered_gmv_brl,
           freight_revenue_brl, on_time_orders, delivery_eligible_orders, late_orders,
           average_late_delivery_days, reviewed_orders, average_review_score, average_order_value_brl,
           cancellation_rate, on_time_delivery_rate, delivered_customers, repeat_customers, repeat_purchase_rate
    FROM ads.ads_executive_dashboard
),
daily_dwd AS (
    SELECT purchase_date, count(*) orders, sum(CASE WHEN status = 'delivered' THEN merchandise_brl ELSE 0 END) gmv,
           count(*) FILTER (status = 'delivered') delivered, count(*) FILTER (status = 'canceled') canceled,
           sum(CASE WHEN status = 'delivered' THEN freight_brl ELSE 0 END) freight
    FROM dwd.fact_order GROUP BY 1
),
daily_dws AS (
    SELECT purchase_date, orders, delivered_gmv_brl gmv, delivered_orders delivered, canceled_orders canceled,
           freight_revenue_brl freight FROM dws.dws_sales_daily
),
seller_ads AS (
    SELECT month_start, seller_id, seller_orders, delivered_orders, canceled_orders, delivered_gmv_brl,
           freight_revenue_brl,
           cancellation_rate
    FROM ads.ads_seller_scorecard
),
seller_dws AS (
    SELECT month_start, seller_id, seller_orders, delivered_orders, canceled_orders, delivered_gmv_brl,
           freight_revenue_brl, canceled_orders / nullif(seller_orders, 0) cancellation_rate
    FROM dws.dws_seller_performance
),
by_group AS (
    SELECT month_start, sum(category_sales_brl) total FROM dws.dws_category_performance GROUP BY 1
),
by_seller AS (
    SELECT month_start, sum(delivered_gmv_brl) total FROM dws.dws_seller_performance GROUP BY 1
),
category_source AS (
    SELECT o.month_start, coalesce(p.product_category_name, '(unknown)') category_code,
           count(*) delivered_items, count(DISTINCT o.order_id) delivered_orders, sum(i.price) category_sales_brl
    FROM stg_order_items i JOIN source_orders o USING (order_id) JOIN stg_products p USING (product_id)
    WHERE o.delivered GROUP BY 1, 2
),
category_dws AS (
    SELECT month_start, category_code, delivered_items, delivered_orders, category_sales_brl
    FROM dws.dws_category_performance
),
seller_source AS (
    SELECT o.month_start, i.seller_id, count(DISTINCT o.order_id) seller_orders,
           count(DISTINCT o.order_id) FILTER (o.delivered) delivered_orders,
           count(DISTINCT o.order_id) FILTER (o.canceled) canceled_orders,
           sum(CASE WHEN o.delivered THEN i.price ELSE 0 END) delivered_gmv_brl,
           sum(CASE WHEN o.delivered THEN i.freight_value ELSE 0 END) freight_revenue_brl
    FROM stg_order_items i JOIN source_orders o USING (order_id) GROUP BY 1, 2
),
seller_dws_inputs AS (
    SELECT month_start, seller_id, seller_orders, delivered_orders, canceled_orders,
           delivered_gmv_brl, freight_revenue_brl
    FROM dws.dws_seller_performance
),
delivery_source AS (
    SELECT month_start, upper(customer_state) state, count(*) delivered_orders,
           count(delivery_delta) eligible_orders, count(*) FILTER (delivery_delta <= 0) on_time_orders,
           count(*) FILTER (delivery_delta > 0) late_orders,
           coalesce(sum(delivery_delta) FILTER (delivery_delta > 0), 0) late_days_sum
    FROM source_orders WHERE delivered GROUP BY 1, 2
),
movement AS (
    SELECT month_start, sum(contribution_brl) total FROM ads.ads_sales_category_movement GROUP BY 1
)
SELECT 'dwd_to_dws.daily_sales' AS check_name, count(*) AS violations FROM (
    (SELECT * FROM daily_dwd EXCEPT ALL SELECT * FROM daily_dws)
    UNION ALL (SELECT * FROM daily_dws EXCEPT ALL SELECT * FROM daily_dwd)
)
UNION ALL
SELECT 'dws_to_ads.seller_scorecard', count(*) FROM (
    (SELECT * FROM seller_dws EXCEPT ALL SELECT * FROM seller_ads)
    UNION ALL (SELECT * FROM seller_ads EXCEPT ALL SELECT * FROM seller_dws)
)
UNION ALL
SELECT 'independent_to_ads.monthly_metrics', count(*) FROM (
    (SELECT * FROM reference EXCEPT ALL SELECT * FROM published)
    UNION ALL (SELECT * FROM published EXCEPT ALL SELECT * FROM reference)
)
UNION ALL
SELECT 'independent_to_dws.delivery_by_state', count(*) FROM (
    (SELECT * FROM delivery_source EXCEPT ALL SELECT * FROM dws.dws_delivery_performance)
    UNION ALL (SELECT * FROM dws.dws_delivery_performance EXCEPT ALL SELECT * FROM delivery_source)
)
UNION ALL
SELECT 'independent_to_dws.retention', count(*) FROM (
    (SELECT * FROM source_by_customer EXCEPT ALL SELECT * FROM dws.dws_customer_retention)
    UNION ALL (SELECT * FROM dws.dws_customer_retention EXCEPT ALL SELECT * FROM source_by_customer)
)
UNION ALL
SELECT 'independent_to_dws.category', count(*) FROM (
    (SELECT * FROM category_source EXCEPT ALL SELECT * FROM category_dws)
    UNION ALL (SELECT * FROM category_dws EXCEPT ALL SELECT * FROM category_source)
)
UNION ALL
SELECT 'independent_to_dws.seller', count(*) FROM (
    (SELECT * FROM seller_source EXCEPT ALL SELECT * FROM seller_dws_inputs)
    UNION ALL (SELECT * FROM seller_dws_inputs EXCEPT ALL SELECT * FROM seller_source)
)
UNION ALL
SELECT 'dws_to_ads.category_and_seller_gmv', count(*) FROM ads.ads_executive_dashboard a
FULL JOIN by_group c USING (month_start) FULL JOIN by_seller s USING (month_start)
WHERE a.month_start IS NULL OR coalesce(c.total, 0) <> a.delivered_gmv_brl OR coalesce(s.total, 0) <> a.delivered_gmv_brl
UNION ALL
SELECT 'ads.category_movement', count(*) FROM ads.ads_sales_anomaly a FULL JOIN movement m USING (month_start)
WHERE (a.gmv_change_brl IS NOT NULL AND coalesce(m.total, 0) <> a.gmv_change_brl)
   OR (a.gmv_change_brl IS NULL AND m.month_start IS NOT NULL);
