WITH elapsed AS (
    SELECT date_trunc('month', o.purchase_date)::DATE AS month_start, c.state,
           sum(date_diff('minute', o.purchased_at, o.delivered_at)) AS delivery_minutes_sum
    FROM dwd.fact_order o JOIN dwd.dim_customer c USING (customer_id)
    WHERE o.delivery_eligible
    GROUP BY 1, 2
)
SELECT d.*, e.delivery_minutes_sum,
       d.delivered_orders - d.eligible_orders AS excluded_orders
FROM dws.dws_delivery_performance d LEFT JOIN elapsed e USING (month_start, state)
