"""Register the approved embedded dashboards and export public aggregates."""

import json
import os
import secrets
import sys
from contextlib import redirect_stdout
from datetime import datetime, timezone

from common import BASE, read_runtime, warehouse
from governance import governance

ROLE = "RetailDemoRole"
APPROVED = ("retail-executive", "retail-category", "retail-seller",
            "retail-fulfillment", "retail-customer", "retail-quality")
READ = (("can_read", "Dashboard"), ("can_read", "Chart"), ("can_read", "Dataset"),
        ("can_read", "EmbeddedDashboard"), ("can_time_range", "Api"),
        ("can_get", "Datasource"), ("can_log", "Superset"))


def configure_embeddings(origin, provision):
    from superset.app import create_app
    from superset.extensions import appbuilder, db

    with redirect_stdout(sys.stderr):
        app = create_app()
    with app.app_context():
        from superset.models.dashboard import Dashboard
        from superset.models.embedded_dashboard import EmbeddedDashboard

        security = appbuilder.sm
        role = security.find_role(ROLE) or security.add_role(ROLE)
        permissions = [security.find_permission_view_menu(action, view) for action, view in READ]
        if any(permission is None for permission in permissions):
            raise RuntimeError("Expected Superset 6.0 permission is missing")
        role.permissions = permissions
        identity = security.find_user(username="retail_demo")
        if identity is None:
            identity = security.add_user("retail_demo", "Retail", "Viewer",
                                         "retail-demo@localhost.invalid", role,
                                         password=secrets.token_urlsafe(48))
        if not identity:
            raise RuntimeError("Could not create the demo identity")
        identity.roles = [role]
        dashboards = {}
        for slug in APPROVED:
            expected = provision["dashboards"][slug]
            dashboard = db.session.get(Dashboard, expected["id"])
            if not dashboard or dashboard.slug != slug or not dashboard.published:
                raise RuntimeError(f"Missing approved dashboard {slug}")
            if {c.id for c in dashboard.slices} != {c["id"] for c in expected["charts"].values()}:
                raise RuntimeError(f"Unexpected charts in {slug}")
            if role not in dashboard.roles:
                dashboard.roles.append(role)
            entry = dashboard.embedded[0] if dashboard.embedded else EmbeddedDashboard(dashboard=dashboard)
            entry.allow_domain_list = origin
            db.session.add(entry)
            db.session.flush()
            filters = json.loads(dashboard.json_metadata)["native_filter_configuration"]
            dashboards[slug] = {
                "id": dashboard.id, "uuid": str(entry.uuid), "title": dashboard.dashboard_title,
                "charts": {str(chart.id): {
                    "dataset": chart.datasource_id,
                    "axes": [column for query in json.loads(chart.query_context)["queries"]
                             for column in query["columns"] if isinstance(column, str)],
                } for chart in dashboard.slices},
                "filters": {item["id"]: target for item in filters for target in item["targets"]
                            if target and "datasetId" in target},
            }
        db.session.commit()
        return dashboards


def summary(receipt):
    _, engine = warehouse(receipt)
    with engine.connect() as conn:
        coverage, panels = governance(conn, receipt, chinese=True)
        metrics = conn.exec_driver_sql("""
            SELECT SUM(delivered_gmv_brl)::DOUBLE, SUM(delivered_orders)::INTEGER,
                   SUM(delivered_gmv_brl) / NULLIF(SUM(delivered_orders),0),
                   SUM(canceled_orders) / NULLIF(SUM(orders),0),
                   SUM(on_time_orders) / NULLIF(SUM(delivery_eligible_orders),0),
                   (SELECT SUM(review_score_sum) FROM dws.dws_sales_daily)
                       / NULLIF(SUM(reviewed_orders),0)
            FROM ads.ads_executive_dashboard
        """).one()
        keys = ("gmv", "orders", "aov", "cancellation", "onTime", "review")
        monthly = conn.exec_driver_sql("""
            SELECT month_start::VARCHAR, delivered_gmv_brl::DOUBLE, delivered_orders
            FROM ads.ads_executive_dashboard ORDER BY month_start
        """).all()
        sources = conn.exec_driver_sql("SELECT source_name, source_rows FROM control.source_watermark ORDER BY 1").all()
        scope = conn.exec_driver_sql("SELECT MIN(purchase_date)::VARCHAR, MAX(purchase_date)::VARCHAR FROM dwd.fact_order").one()
    engine.dispose()
    quality = receipt["quality"]["checks"]
    return {
        "governancePanels": list(panels),
        "overview": {"metrics": {key: float(value) for key, value in zip(keys, metrics)},
                     "monthly": [list(row) for row in monthly], "coverage": list(scope), "coverageNote": coverage,
                     "version": receipt["version"],
                     "warningCount": sum(c["severity"] == "warning" and not c["passed"] for c in quality)},
        "quality": {"checks": len(quality), "blockers": sum(c["severity"] == "error" and not c["passed"] for c in quality),
                    "warnings": sum(c["severity"] == "warning" and not c["passed"] for c in quality),
                    "findings": [s.removeprefix("- ") for s in panels[1].splitlines() if s.startswith("- ")],
                    "coverage": coverage},
        "snapshot": {"version": receipt["version"], "sha256": receipt["sha256"],
                     "published": datetime.fromtimestamp(receipt["publication_manifest_timestamp"], timezone.utc).isoformat(),
                     "size": receipt["size_bytes"], "sources": [list(row) for row in sources],
                     "layers": [line.strip("|").split("|") for line in panels[0].splitlines()
                                if line.startswith(("| ODS ", "| DWD ", "| DWS ", "| ADS "))],
                     "coverage": list(scope)},
    }


if __name__ == "__main__":
    receipt = read_runtime("snapshot.json")
    provision = read_runtime("provision.json")
    if (provision["version"], provision["sha256"]) != (receipt["version"], receipt["sha256"]):
        raise RuntimeError("Superset provisioning receipt differs from snapshot")
    data = summary(receipt)
    data["dashboards"] = configure_embeddings(sys.argv[1], provision)
    print(json.dumps(data))
