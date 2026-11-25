SELECT date_trunc('month', o.purchase_date)::DATE AS month_start, c.state,
       count(DISTINCT c.customer_unique_id) AS state_customer_months
FROM dwd.fact_order o JOIN dwd.dim_customer c USING (customer_id)
WHERE o.status = 'delivered'
GROUP BY 1, 2
