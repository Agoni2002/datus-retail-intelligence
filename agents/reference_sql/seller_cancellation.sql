SELECT seller_id, SUM(canceled_orders) AS canceled_orders, SUM(seller_orders) AS seller_orders,
       ROUND(SUM(canceled_orders) / NULLIF(SUM(seller_orders), 0), 4) AS cancellation_rate
FROM ads.ads_seller_scorecard
GROUP BY seller_id ORDER BY cancellation_rate DESC, seller_id LIMIT 10
