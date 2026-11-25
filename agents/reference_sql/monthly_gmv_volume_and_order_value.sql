-- Retrieve both periods. Use prior AOV × change in orders for volume,
-- and current orders × change in AOV for value. The terms sum to the GMV change.
SELECT month_start, delivered_gmv_brl, delivered_orders, average_order_value_brl
FROM ads.ads_executive_dashboard
ORDER BY month_start DESC LIMIT 2
