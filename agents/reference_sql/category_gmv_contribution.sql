-- Filter to the investigation month as needed. Contributions are current less prior.
SELECT month_start, category_name, contribution_brl
FROM ads.ads_sales_category_movement
ORDER BY month_start DESC, contribution_brl, category_code
