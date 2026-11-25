-- Attribute whole-order eligibility to each participating seller at most once.
WITH seller_orders AS (
    SELECT DISTINCT seller_id, order_id FROM dwd.fact_order_item
)
SELECT date_trunc('month', o.purchase_date)::DATE AS month_start, s.seller_id,
       count(*) FILTER (WHERE o.delivery_eligible) AS eligible_orders,
       count(*) FILTER (WHERE o.is_on_time) AS on_time_orders
FROM seller_orders s JOIN dwd.fact_order o USING (order_id)
WHERE o.status = 'delivered'
GROUP BY 1, 2
HAVING count(*) FILTER (WHERE o.delivery_eligible) > 0
