SELECT date_trunc('month', purchase_date)::DATE AS month_start,
       CASE WHEN merchandise_brl < 50 THEN '01 · Below 50'
            WHEN merchandise_brl < 100 THEN '02 · 50 to <100'
            WHEN merchandise_brl < 200 THEN '03 · 100 to <200'
            WHEN merchandise_brl < 500 THEN '04 · 200 to <500'
            ELSE '05 · 500 and above' END AS basket_band,
       count(*) AS delivered_orders
FROM dwd.fact_order WHERE status = 'delivered'
GROUP BY 1, 2
