# Business requirements

The warehouse supports e-commerce operations analysis from the Brazilian Olist extract. It uses the original recorded prices, freight charges, statuses and fulfillment timestamps. It does not estimate inventory, product cost, margin, profit, or causes of cancellation.

| Question | Warehouse answer |
| --- | --- |
| What is monthly GMV? | Delivered item merchandise value by order purchase month and BRL. |
| Which categories contribute most? | Delivered item totals by source product category with English labels where available. |
| Which sellers have the highest cancellation rates? | Canceled seller/order pairs divided by observed seller/order pairs, with the denominator visible. |
| Which regions have the worst delivery performance? | Eligible delivery rate and late days by customer state, supported by delivered and eligible counts. |
| What is repeat purchase? | Within-month repeat share among delivered customers, using the cross-order customer ID. |
| Why did sales decrease and where? | Compare consecutive purchase months and show additive category movements. These locate the change and support follow-up investigation. The source does not establish causality. |

Treat a missing outcome as unknown. `unavailable` remains its own status. Same-calendar-date delivery is on time. The source records historical snapshots of orders with no event stream or status history. For recent data supplied in future, flag incomplete purchase months before using them in alerts or rankings. The deterministic warehouse definitions and fixture cases are the acceptance baseline ahead of model-based analysis.
