SELECT state, SUM(on_time_orders) AS on_time_orders, SUM(eligible_orders) AS eligible_orders,
       ROUND(SUM(on_time_orders) / NULLIF(SUM(eligible_orders), 0), 4) AS on_time_delivery_rate
FROM dws.dws_delivery_performance
GROUP BY state HAVING SUM(eligible_orders) > 0
ORDER BY on_time_delivery_rate, state LIMIT 10
