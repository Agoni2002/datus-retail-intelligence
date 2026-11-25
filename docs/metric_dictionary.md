# Metric dictionary

[Machine-readable metric definitions](../metrics/definitions.yml) are the canonical business contract. Each of the eleven definitions lists the formula, input count or amount, denominator where applicable, time dimension, eligible statuses, NULL behavior, source tables, published SQL field, and limitations. [Warehouse SQL](../warehouse) implements the calculations and [independent reconciliation SQL](../metrics/calculations.sql) recomputes fixture-verifiable results before publishing.

| Metric | Published calculation |
| --- | --- |
| Delivered GMV | Delivered item price sum excluding freight, BRL |
| Delivered order count | Distinct delivered orders |
| Average order value | Delivered GMV ÷ delivered orders |
| Cancellation rate | Canceled orders ÷ all orders |
| On-time delivery rate | On-time delivered orders ÷ delivered orders with eligible dates |
| Average late delivery days | Sum of late calendar days ÷ eligible late orders |
| Freight revenue | Recorded delivered-item freight charges, BRL |
| Average review score | Latest score per reviewed delivered order, averaged |
| Repeat purchase rate | Customers with at least 2 delivered orders in the purchase month ÷ delivered customers in the same month |
| Category sales | Delivered item price sum by source product category |
| Seller performance | Seller/order participation, cancellation, and seller-attributed delivered item and freight values |

Rate rollups should use summed numerators and denominators at the requested grain. Within-month repeat customer counts cannot be summed to compute cross-month unique retention. Average late days uses late orders as its denominator. The sales anomaly and category movement tables provide adjacent-month comparisons and are sensitive to incomplete reporting periods.
