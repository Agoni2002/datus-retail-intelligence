-- One row per purchase month. Use additive numerators for filter-safe ratios.
WITH reviews AS (
    SELECT date_trunc('month', purchase_date)::DATE AS month_start,
           sum(review_score_sum) AS review_score_sum
    FROM dws.dws_sales_daily GROUP BY 1
), delivery AS (
    SELECT month_start, sum(late_days_sum) AS late_days_sum
    FROM dws.dws_delivery_performance GROUP BY 1
)
SELECT a.*, r.review_score_sum, coalesce(d.late_days_sum, 0) AS late_days_sum
FROM ads.ads_executive_dashboard a
LEFT JOIN reviews r USING (month_start)
LEFT JOIN delivery d USING (month_start)
