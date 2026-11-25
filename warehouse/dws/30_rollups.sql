CREATE OR REPLACE TABLE dws.dws_sales_daily AS
SELECT purchase_date, count(*) orders, count_if(status = 'delivered') delivered_orders,
       count_if(status = 'canceled') canceled_orders,
       coalesce(sum(merchandise_brl) FILTER (status = 'delivered'), 0) delivered_gmv_brl,
       coalesce(sum(freight_brl) FILTER (status = 'delivered'), 0) freight_revenue_brl,
       sum(latest_review_score) FILTER (status = 'delivered') review_score_sum,
       count(latest_review_score) FILTER (status = 'delivered') reviewed_orders
FROM dwd.fact_order GROUP BY purchase_date;
ALTER TABLE dws.dws_sales_daily ADD PRIMARY KEY(purchase_date);

CREATE OR REPLACE TABLE dws.dws_category_performance AS
SELECT date_trunc('month', o.purchase_date)::DATE month_start, p.category_code, p.category_name,
       count(*) delivered_items, count(DISTINCT o.order_id) delivered_orders, sum(i.price_brl) category_sales_brl
FROM dwd.fact_order_item i JOIN dwd.fact_order o USING (order_id) JOIN dwd.dim_product p USING (product_id)
WHERE o.status = 'delivered' GROUP BY 1, 2, 3;
ALTER TABLE dws.dws_category_performance ADD PRIMARY KEY(month_start, category_code);

CREATE OR REPLACE TABLE dws.dws_seller_performance AS
WITH seller_orders AS (
    SELECT order_id, seller_id, sum(price_brl) merchandise_brl, sum(freight_brl) freight_brl
    FROM dwd.fact_order_item GROUP BY order_id, seller_id
)
SELECT date_trunc('month', o.purchase_date)::DATE month_start, i.seller_id, count(*) seller_orders,
       count_if(o.status = 'delivered') delivered_orders, count_if(o.status = 'canceled') canceled_orders,
       coalesce(sum(i.merchandise_brl) FILTER (o.status = 'delivered'), 0) delivered_gmv_brl,
       coalesce(sum(i.freight_brl) FILTER (o.status = 'delivered'), 0) freight_revenue_brl
FROM seller_orders i JOIN dwd.fact_order o USING (order_id) GROUP BY 1, 2;
ALTER TABLE dws.dws_seller_performance ADD PRIMARY KEY(month_start, seller_id);

CREATE OR REPLACE TABLE dws.dws_delivery_performance AS
SELECT date_trunc('month', o.purchase_date)::DATE month_start, c.state,
       count(*) delivered_orders, count(*) FILTER (o.delivery_eligible) eligible_orders,
       count(*) FILTER (o.is_on_time) on_time_orders, count(*) FILTER (o.is_on_time = false) late_orders,
       coalesce(sum(o.late_days), 0) late_days_sum
FROM dwd.fact_order o JOIN dwd.dim_customer c USING (customer_id)
WHERE o.status = 'delivered' GROUP BY 1, 2;
ALTER TABLE dws.dws_delivery_performance ADD PRIMARY KEY(month_start, state);

CREATE OR REPLACE TABLE dws.dws_customer_retention AS
SELECT date_trunc('month', o.purchase_date)::DATE month_start, c.customer_unique_id,
       count(*) delivered_orders
FROM dwd.fact_order o JOIN dwd.dim_customer c USING (customer_id)
WHERE o.status = 'delivered' GROUP BY 1, 2;
ALTER TABLE dws.dws_customer_retention ADD PRIMARY KEY(month_start, customer_unique_id);
