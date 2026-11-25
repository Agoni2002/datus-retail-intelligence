---
name: retail-metrics
description: Answer Olist fulfillment and sales questions using the published retail KPIs and protected SQL interface.
---

Use `metrics/definitions.yml` for denominator, status, null, date, and currency rules. Query the serving tables through the approved retail SQL entry point when it is exposed as a tool. Keep each statement to one approved table. Report the result period and number of eligible orders when discussing delivery rates. If an explicit numerator or denominator is needed, use the published supporting counts. Avoid treating category contributions as causal explanations or imputing inventory, costs, or profit.

In local developer sessions, the guarded CLI is `python -m retail_agents.safe_query --output <publication directory> '<single SELECT>'`, launched with the companion Python environment from the project root. If the guarded interface is unavailable, report that the query could not be run.
