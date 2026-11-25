SELECT month_start,
       CASE WHEN delivered_orders <= 4 THEN CAST(delivered_orders AS VARCHAR) ELSE '5+' END AS order_count,
       count(*) AS customer_months
FROM dws.dws_customer_retention
GROUP BY 1, 2
