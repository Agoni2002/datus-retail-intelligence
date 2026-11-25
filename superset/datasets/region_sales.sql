-- Order facts already contain item totals aggregated to order grain.
SELECT date_trunc('month', o.purchase_date)::DATE AS month_start, c.state,
       sum(o.merchandise_brl) AS delivered_gmv_brl, count(*) AS delivered_orders
FROM dwd.fact_order o JOIN dwd.dim_customer c USING (customer_id)
WHERE o.status = 'delivered'
GROUP BY 1, 2
