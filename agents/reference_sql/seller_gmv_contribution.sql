-- Filter to the two comparison months. Compare by seller and fill absent periods with zero.
SELECT month_start, seller_id, delivered_gmv_brl
FROM ads.ads_seller_scorecard
ORDER BY month_start DESC, seller_id
