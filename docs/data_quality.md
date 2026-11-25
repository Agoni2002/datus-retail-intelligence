# Data quality and reconciliation

Use `python -m ingestion.schema_inspector <csv-directory>` for a shape and relationship profile. Build results include a machine-readable JSON report with check-level status, severity, and violating row counts. Raw data values and review text are excluded from the pipeline report. Error-level violations prevent promotion.

| Family | Gates and reported conditions |
| --- | --- |
| Structure and types | Strict CSV header set and parsing, ODS shape checks, exact integral and cents precision, timestamp range and finite numeric values. |
| Completeness and freshness | Required identifiers and values, nonempty orders, nullable source fields, delivered order date/missing item warnings, configurable historical event lag. |
| Uniqueness | Stable typed business keys. Warn on duplicates, distinguishing identical from conflicting typed variants. Enforce declared DWD keys and reconciled row counts. |
| Relationships | Required customer, order, product and seller links are checked before load. Additional FKs and value constraints are enforced in DWD. |
| Business rules | Valid statuses, positive sequences, nonnegative payment/price/freight, reviews 1–5, customer and seller location formats, date consistency and geolocation plausibility. |
| Reconciliation | ODS rows minus dedup removals to DWD, delivered payments versus merchandise plus freight, DWD daily sales to DWS, DWS to ADS rollups, and independent SQL against published KPIs and dimensional totals. |

Duplicate keys with date evidence keep the strongest latest event tuple listed in the contract. Ties use the full typed row in ascending order, with NULL last. Without reliable event evidence a tie-break is deterministic. It cannot establish which version is authoritative. All raw rows remain in ODS for review.

Delivery chronology violations are warnings and exclude the affected order from delivery performance. Missing review scores on an actual review row are type/required errors. A delivered order without a review row does not enter the mean score. Payment mismatches on delivered orders warn by default because tender and item values are observations, including missing payments. Set `payment_mismatch_severity: error` for a stricter feed. Geolocation outliers are reported and excluded from canonical coordinate selection.

Setting `as_of_date` enables a reproducible freshness SLA relative to that date. For the historical fixture and supplied extract, the default derives the reference date from the latest purchase. That checks relative component lag without marking years-old data as current. A complete original Olist extract has not been run against this project. Review its first quality report before changing tolerances or deciding how to remediate source exceptions.
