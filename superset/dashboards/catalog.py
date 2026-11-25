"""Version-controlled Superset dashboard, dataset and metric definitions."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Metric:
    label: str
    sql: str
    format: str = ",d"
    description: str = ""


def total(field, label, fmt=",d", description=""):
    return Metric(label, f"SUM({field})", fmt, description)


def rate(numerator, denominator, label, fmt=".2%", description=""):
    return Metric(label, f"SUM({numerator}) / NULLIF(SUM({denominator}), 0)", fmt, description)


METRICS = {
    "gmv": total("delivered_gmv_brl", "Delivered GMV (BRL)", ",.2f",
                 "Delivered merchandise value only. Excludes freight."),
    "delivered": total("delivered_orders", "Delivered Orders"),
    "aov": rate("delivered_gmv_brl", "delivered_orders", "Average Order Value (BRL)", ",.2f"),
    "orders": total("orders", "All Orders"),
    "cancel_rate": rate("canceled_orders", "orders", "Cancellation Rate", ".4%",
                        "Canceled orders divided by all observed orders."),
    "on_time_exec": rate("on_time_orders", "delivery_eligible_orders", "On-time Delivery Rate", ".4%"),
    "on_time": rate("on_time_orders", "eligible_orders", "On-time Delivery Rate", ".2%",
                    "On-time deliveries divided by deliveries with eligible timestamps."),
    "late_avg": rate("late_days_sum", "late_orders", "Average Late Delivery Days", ",.2f",
                     "Positive late calendar days divided by late delivered orders."),
    "freight": total("freight_revenue_brl", "Freight Charges (BRL)", ",.2f",
                     "Delivered freight charges, separate from merchandise GMV."),
    "review": rate("review_score_sum", "reviewed_orders", "Average Review Score", ".4f",
                   "Latest available score per reviewed, delivered order."),
    "reviewed": total("reviewed_orders", "Reviewed Delivered Orders"),
    "repeat": rate("repeat_customers", "delivered_customers", "Monthly Same-Month Repeat Customer Share", ".4%",
                   "Customer-months with at least two delivered orders divided by eligible customer-months."),
    "category_gmv": total("category_sales_brl", "Category GMV (BRL)", ",.2f"),
    "category_orders": total("delivered_orders", "Delivered Category Orders", ",d",
                             "Distinct within each category. An order may appear in multiple categories."),
    "category_items": total("delivered_items", "Delivered Item Lines"),
    "seller_orders": total("seller_orders", "Seller Order Participations"),
    "seller_cancel": rate("canceled_orders", "seller_orders", "Seller Participation Cancellation Rate", ".2%",
                          "Canceled seller-order pairs divided by all seller-order pairs. Orders can span sellers."),
    "eligible": total("eligible_orders", "Eligible Delivered Orders"),
    "late": total("late_orders", "Late Delivered Orders"),
    "excluded": total("excluded_orders", "Excluded Delivered Orders"),
    "delivery_avg": Metric("Average Delivery Time (Days)",
                           "SUM(delivery_minutes_sum) / NULLIF(SUM(eligible_orders), 0) / 1440.0", ",.2f",
                           "Elapsed purchase-to-delivery time for orders passing the warehouse delivery gate."),
    "alert": Metric("Flagged State-Months", "COUNT(*)"),
    "customer_months": total("customer_months", "Delivered Customer-Months"),
    "state_customers": total("state_customer_months", "State Customer-Months", ",d",
                             "Distinct customers within each state-month. Totals can overlap across states."),
}

# Virtual datasets are selected by name from datasets/*.sql. Physical datasets
# retain their native schema, source columns and published grain.
DATASETS = {
    "executive": (None, "Month-level ADS counts and amounts plus DWS additive review and delay numerators.",
                  "gmv delivered aov orders cancel_rate on_time_exec late_avg freight review reviewed repeat"),
    "category": ("dws.dws_category_performance", "Delivered items and orders per purchase month and product category.",
                 "category_gmv category_orders category_items"),
    "seller": ("ads.ads_seller_scorecard", "Seller-order participation and delivered item amounts by purchase month.",
               "gmv delivered seller_orders seller_cancel freight"),
    "region_sales": (None, "Delivered order amounts by purchase month and customer state.",
                     "gmv delivered"),
    "fulfillment": (None, "Delivery DWS plus elapsed minutes from the eligible order facts.",
                    "delivered eligible late excluded on_time late_avg delivery_avg"),
    "seller_delivery": (None, "Eligible deliveries per seller-order pair. One order can include multiple sellers.",
                        "eligible on_time"),
    "alerts": ("ads.ads_delivery_alerts", "Existing warehouse alert flags by purchase month and state.",
               "alert late"),
    "basket_distribution": (None, "Delivered merchandise orders grouped by BRL basket bands.",
                            "delivered"),
    "customer_frequency": (None, "Non-identifying customer-month frequency distribution from DWS.",
                           "customer_months"),
    "review_distribution": (None, "Latest qualifying review per delivered order, grouped by score.",
                             "reviewed"),
    "customer_geography": (None, "Delivered customer counts within each purchase month and customer state.",
                           "state_customers"),
    "quality_summary": (None, "Purchase-month coverage in the published ADS.",
                        "orders delivered reviewed"),
}

LINE = "echarts_timeseries_line"
BAR = "echarts_timeseries_bar"
BIG = "big_number_total"
TABLE = "table"


@dataclass(frozen=True)
class Chart:
    key: str
    title: str
    dataset: str
    viz: str
    metrics: tuple[str, ...]
    axis: str = ""
    series: str = ""
    limit: int = 500
    sort: str = "axis"
    description: str = ""


def viz(key, title, dataset, kind, metrics, axis="", *, series="", limit=500, sort="axis", description=""):
    return Chart(key, title, dataset, kind, tuple(metrics.split()), axis, series, limit, sort, description)


def card(metric, dataset="executive"):
    # A scalar aggregation returns one row. Leave headroom so Superset does
    # not show a row-limit warning on a complete KPI result.
    return viz(metric, METRICS[metric].label, dataset, BIG, metric, limit=2)


CHART_ROWS = {
    "retail-executive": (
        tuple(card(m) for m in ("gmv", "delivered", "aov")),
        tuple(card(m) for m in ("cancel_rate", "on_time_exec", "review")),
        (viz("gmv_trend", "Monthly Delivered GMV · BRL", "executive", LINE, "gmv", "month_start"),
         viz("orders_trend", "Monthly Delivered Orders", "executive", LINE, "delivered", "month_start")),
        (viz("aov_trend", "Monthly Average Order Value · BRL", "executive", LINE, "aov", "month_start"),
         viz("top_categories", "Top 10 Product Categories · BRL", "category", BAR, "category_gmv",
             "category_name", limit=10, sort="desc")),
        (viz("regional_gmv", "Delivered GMV by Customer State · BRL", "region_sales", BAR, "gmv", "state", sort="desc"),
         viz("regional_overview", "State Delivery Performance", "fulfillment", TABLE,
             "delivered eligible late excluded on_time", "state", sort="desc")),
    ),
    "retail-category": (
        (viz("gmv_rank", "Category GMV Ranking · BRL", "category", BAR, "category_gmv", "category_name", limit=15, sort="desc"),
         viz("orders_rank", "Category Order Volume", "category", BAR, "category_orders", "category_name", limit=15, sort="desc")),
        (viz("category_trend", "Monthly Category Sales · BRL", "category", LINE, "category_gmv", "month_start", series="category_name", limit=2500,
             description="Select one or more categories to compare their monthly trends."),),
        (viz("contribution", "Category Contribution to Selected GMV", "category", "pie", "category_gmv",
             "category_name", limit=100, sort="desc", description="Share of selected category GMV. Hover to see amounts and percentages."),
         viz("bottom", "Lowest Delivered Category GMV · BRL", "category", BAR, "category_gmv", "category_name", limit=10, sort="asc")),
        (viz("category_scorecard", "Category Performance Detail", "category", TABLE,
             "category_gmv category_orders category_items", "category_name", sort="desc"),),
    ),
    "retail-seller": (
        (viz("gmv", "Top Sellers by Delivered GMV · BRL", "seller", BAR, "gmv", "seller_id", limit=10, sort="desc"),
         viz("volume", "Top Sellers by Order Participation", "seller", BAR, "seller_orders", "seller_id", limit=10, sort="desc")),
        (viz("cancel", "Seller Participation Cancellation Rate", "seller", TABLE, "seller_cancel seller_orders",
             "seller_id", limit=20, sort="desc", description="Ranked by cancellation rate. Check participation volume when comparing rates."),
         viz("freight", "Top Sellers by Delivered Freight · BRL", "seller", BAR, "freight", "seller_id", limit=10, sort="desc")),
        (viz("delivery", "Seller Delivery Participation", "seller_delivery", TABLE, "eligible on_time",
             "seller_id", limit=20, sort="desc", description="Eligibility follows the order. Multiple sellers can participate in a delivery."),
         viz("seller_scorecard", "Seller Scorecard", "seller", TABLE, "gmv seller_orders delivered seller_cancel freight",
             "seller_id", limit=100, sort="desc")),
    ),
    "retail-fulfillment": (
        (card("on_time", "fulfillment"), card("delivery_avg", "fulfillment"), card("late_avg", "fulfillment")),
        (viz("eligibility", "Monthly Delivery Denominators", "fulfillment", LINE,
             "delivered eligible late excluded", "month_start"),
         viz("time_trend", "Monthly Purchase-to-Delivery Time", "fulfillment", LINE, "delivery_avg", "month_start")),
        (viz("regional_delivery", "Regional Delivery Performance", "fulfillment", TABLE,
             "delivered eligible late excluded on_time late_avg", "state", sort="desc"),
         viz("alert_distribution", "Delivery Alert Distribution", "alerts", BAR, "alert", "state", sort="desc",
             description="Number of state-months flagged by the warehouse alert rule.")),
    ),
    "retail-customer": (
        (viz("basket", "Delivered Basket Distribution · BRL", "basket_distribution", BAR, "delivered", "basket_band"),
         viz("frequency", "Order Frequency per Customer-Month", "customer_frequency", BAR, "customer_months", "order_count")),
        (viz("repeat", "Monthly Same-Month Repeat Customer Share", "executive", LINE, "repeat", "month_start"),
         viz("review_trend", "Monthly Average Latest Review Score", "executive", LINE, "review", "month_start")),
        (viz("review_dist", "Latest Review Score Distribution", "review_distribution", BAR, "reviewed", "score"),
         viz("customers_state", "Delivered Customer-Months by State", "customer_geography", BAR,
             "state_customers", "state", sort="desc")),
    ),
    "retail-quality": (
        (viz("coverage", "Purchase, Delivery and Review Coverage", "quality_summary", LINE,
             "orders delivered reviewed", "month_start"),),
    ),
}

TITLES = {
    "retail-executive": "E-Commerce Executive Overview",
    "retail-category": "Product & Category Analytics",
    "retail-seller": "Seller Performance Analytics",
    "retail-fulfillment": "Delivery & Fulfillment Analytics",
    "retail-customer": "Customer & Review Analytics",
    "retail-quality": "Data Quality & Governance",
}

NOTES = {
    "retail-executive": "All headline KPIs use the purchase-month range. Category and state filters apply only to compatible panels. GMV excludes freight.",
    "retail-category": "Category orders overlap across categories. Contribution percentages use the selected category GMV denominator. Select categories to focus the monthly trend.",
    "retail-seller": "Orders enter each participating seller's denominator once. Multi-seller orders can appear under multiple sellers. Delivery rates attribute whole-order outcomes to seller-order participation.",
    "retail-fulfillment": "Eligible deliveries pass the warehouse date and chronology gate. Delivered orders with missing or invalid timestamps are tracked as exclusions. Late days use only eligible late orders.",
    "retail-customer": "Latest review per delivered order. Frequency and repeat share use customer-months. Regional counts are distinct within state-months and can overlap across states.",
    "retail-quality": "Checks and publication facts are captured from the validated snapshot. The coverage chart queries that snapshot live.",
}

FILTERS = {
    "retail-executive": (
        ("Product category", "category", "category_name", {"category"}),
        ("Customer state", "region_sales", "state", {"region_sales", "fulfillment"}),
    ),
    "retail-category": (("Product category", "category", "category_name", {"category"}),),
    "retail-seller": (("Seller ID", "seller", "seller_id", {"seller", "seller_delivery"}),),
    "retail-fulfillment": (("Customer state", "fulfillment", "state", {"fulfillment", "alerts"}),),
    "retail-customer": (("Customer state", "customer_geography", "state", {"customer_geography"}),),
}
