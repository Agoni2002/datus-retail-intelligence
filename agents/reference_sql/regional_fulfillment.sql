-- Compare by customer state. This table supports regional order and delivery counts.
SELECT month_start, state, delivered_orders, eligible_orders, on_time_orders
FROM dws.dws_delivery_performance
ORDER BY month_start DESC, state
