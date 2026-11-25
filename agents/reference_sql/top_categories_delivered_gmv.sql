SELECT category_name, SUM(category_sales_brl) AS delivered_gmv_brl
FROM dws.dws_category_performance
GROUP BY category_name ORDER BY delivered_gmv_brl DESC, category_name LIMIT 10
