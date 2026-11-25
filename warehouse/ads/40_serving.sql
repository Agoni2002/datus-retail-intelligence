CREATE OR REPLACE TABLE ads.ads_executive_dashboard AS
WITH sales AS (
    SELECT date_trunc('month', purchase_date)::DATE month_start, sum(orders) orders,
           sum(delivered_orders) delivered_orders, sum(canceled_orders) canceled_orders,
           sum(delivered_gmv_brl) delivered_gmv_brl, sum(freight_revenue_brl) freight_revenue_brl,
           sum(review_score_sum) review_score_sum, sum(reviewed_orders) reviewed_orders
    FROM dws.dws_sales_daily GROUP BY 1
),
delivery AS (
    SELECT month_start, sum(eligible_orders) eligible_orders, sum(on_time_orders) on_time_orders,
           sum(late_orders) late_orders, sum(late_days_sum) late_days_sum
    FROM dws.dws_delivery_performance GROUP BY 1
),
retention AS (
    SELECT month_start, count(*) delivered_customers, count_if(delivered_orders >= 2) repeat_customers
    FROM dws.dws_customer_retention GROUP BY 1
)
SELECT s.month_start, s.orders, s.delivered_orders, s.canceled_orders, s.delivered_gmv_brl,
       s.delivered_gmv_brl / nullif(s.delivered_orders, 0) average_order_value_brl,
       s.canceled_orders / nullif(s.orders, 0) cancellation_rate,
       coalesce(d.eligible_orders, 0) delivery_eligible_orders, coalesce(d.on_time_orders, 0) on_time_orders,
       coalesce(d.late_orders, 0) late_orders, d.on_time_orders / nullif(d.eligible_orders, 0) on_time_delivery_rate,
       d.late_days_sum / nullif(d.late_orders, 0) average_late_delivery_days, s.freight_revenue_brl,
       s.reviewed_orders, s.review_score_sum / nullif(s.reviewed_orders, 0) average_review_score,
       coalesce(r.delivered_customers, 0) delivered_customers, coalesce(r.repeat_customers, 0) repeat_customers,
       r.repeat_customers / nullif(r.delivered_customers, 0) repeat_purchase_rate
FROM sales s LEFT JOIN delivery d USING (month_start) LEFT JOIN retention r USING (month_start);
ALTER TABLE ads.ads_executive_dashboard ADD PRIMARY KEY(month_start);

CREATE OR REPLACE TABLE ads.ads_seller_scorecard AS
SELECT s.*, s.canceled_orders / nullif(s.seller_orders, 0) cancellation_rate, d.state seller_state
FROM dws.dws_seller_performance s JOIN dwd.dim_seller d USING (seller_id);
ALTER TABLE ads.ads_seller_scorecard ADD PRIMARY KEY(month_start, seller_id);

CREATE OR REPLACE TABLE ads.ads_delivery_alerts AS
SELECT d.*, d.on_time_orders / nullif(d.eligible_orders, 0) on_time_delivery_rate,
       d.late_orders / nullif(d.eligible_orders, 0) late_delivery_rate,
       d.late_days_sum / nullif(d.late_orders, 0) average_late_delivery_days
FROM dws.dws_delivery_performance d CROSS JOIN run_settings s
WHERE d.eligible_orders >= s.late_alert_min_orders
  AND d.late_orders / nullif(d.eligible_orders, 0) >= s.late_alert_rate;
ALTER TABLE ads.ads_delivery_alerts ADD PRIMARY KEY(month_start, state);

CREATE OR REPLACE TABLE ads.ads_sales_anomaly AS
SELECT cur.month_start, cur.delivered_gmv_brl, prev.delivered_gmv_brl prior_month_gmv_brl,
       cur.delivered_gmv_brl - prev.delivered_gmv_brl gmv_change_brl,
       (cur.delivered_gmv_brl - prev.delivered_gmv_brl) / nullif(prev.delivered_gmv_brl, 0) gmv_change_rate,
       (cur.delivered_gmv_brl - prev.delivered_gmv_brl) / nullif(prev.delivered_gmv_brl, 0)
           <= -s.sales_decline_threshold is_decline
FROM ads.ads_executive_dashboard cur
LEFT JOIN ads.ads_executive_dashboard prev ON prev.month_start = (cur.month_start - INTERVAL 1 MONTH)::DATE
CROSS JOIN run_settings s;
ALTER TABLE ads.ads_sales_anomaly ADD PRIMARY KEY(month_start);

CREATE OR REPLACE TABLE ads.ads_sales_category_movement AS
WITH candidates AS (
    SELECT m.month_start, c.category_code
    FROM ads.ads_sales_anomaly m JOIN dws.dws_category_performance c
      ON c.month_start IN (m.month_start, (m.month_start - INTERVAL 1 MONTH)::DATE)
    WHERE m.prior_month_gmv_brl IS NOT NULL
    GROUP BY 1, 2
)
SELECT k.month_start, k.category_code, coalesce(cur.category_name, prev.category_name) category_name,
       coalesce(cur.category_sales_brl, 0) current_gmv_brl, coalesce(prev.category_sales_brl, 0) prior_gmv_brl,
       coalesce(cur.category_sales_brl, 0) - coalesce(prev.category_sales_brl, 0) contribution_brl
FROM candidates k LEFT JOIN dws.dws_category_performance cur
  ON cur.month_start = k.month_start AND cur.category_code = k.category_code
LEFT JOIN dws.dws_category_performance prev
  ON prev.month_start = (k.month_start - INTERVAL 1 MONTH)::DATE AND prev.category_code = k.category_code;
ALTER TABLE ads.ads_sales_category_movement ADD PRIMARY KEY(month_start, category_code);
