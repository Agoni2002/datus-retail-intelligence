# Data dictionary

[Ingestion contract](../ingestion/contract.py) lists every original CSV column, expected logical type, candidate key, required field, and ordered event evidence. The schema inspector emits per-column ODS and expected types, row counts, null ratios, invalid-cast counts, duplicate candidate keys, and candidate FK orphan counts.

| ODS table | Candidate key | Candidate relationships and fields |
| --- | --- | --- |
| `orders` | `order_id` | `customer_id → customers`; order status, purchase/approval, carrier, actual delivery, and estimated delivery timestamps. |
| `order_items` | `order_id, order_item_id` | Order, product and seller IDs; shipping deadline; exact item price and freight in BRL. |
| `customers` | `customer_id` | Order-scoped ID, cross-order `customer_unique_id`, state, city and ZIP prefix. A ZIP prefix can match multiple geolocation records. |
| `products` | `product_id` | Source category may match the optional translation table; product metadata and dimensions. The source uses the original `*_lenght` column spellings. |
| `sellers` | `seller_id` | State, city, and five-character ZIP prefix with optional geolocation samples. |
| `order_payments` | `order_id, payment_sequential` | Order ID, tender type and installment count. `payment_value` is the tender entry total. |
| `order_reviews` | `order_id, review_id` | Order ID, score, nullable title and comment, creation and answer timestamps. |
| `geolocation` | ZIP, latitude, longitude, city, state | Candidate observation tuple for deduplication. ZIP alone is many-to-one when mapped to the canonical DWD geography. |
| `product_category_name_translation` | `product_category_name` | Label lookup from the source category to an English category name. |

DWD type conversions normalize one- to five-digit ZIP prefixes to five-character strings, amounts as fixed-point decimals, and dates as timezone-naive local source timestamps. Identifiers remain strings. Business time for sales is the order purchase date. See [dimension and fact grains](dimensional_model.md) and the [published KPI dictionary](metric_dictionary.md).
