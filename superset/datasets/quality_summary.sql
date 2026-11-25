-- The bootstrap adds versioned quality-report numbers as markdown panels.
-- The coverage chart uses complete purchase counts from the published snapshot.
SELECT month_start, orders, delivered_orders, reviewed_orders
FROM ads.ads_executive_dashboard
