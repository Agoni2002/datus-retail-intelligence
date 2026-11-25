SELECT date_trunc('month', purchase_date)::DATE AS month_start,
       CAST(latest_review_score AS VARCHAR) AS score,
       count(*) AS reviewed_orders
FROM dwd.fact_order
WHERE status = 'delivered' AND latest_review_score IS NOT NULL
GROUP BY 1, 2
