"""Check effective demo permissions and reject four warehouse write operations."""

import sys
from contextlib import redirect_stdout

from sqlalchemy.exc import DBAPIError

from common import read_runtime


def main():
    from flask import g
    from superset.app import create_app
    from superset.extensions import appbuilder, db

    with redirect_stdout(sys.stderr):
        app = create_app()
    provision = read_runtime("provision.json")
    with app.test_request_context():
        from superset.models.core import Database
        from superset.models.dashboard import Dashboard

        security = appbuilder.sm
        user = security.find_user(username="retail_demo")
        assert user and [role.name for role in user.roles] == ["RetailDemoRole"]
        g.user = user
        allowed = {item["id"] for item in provision["dashboards"].values()}
        assert {d.id for d in db.session.query(Dashboard) if security.can_access_dashboard(d)} == allowed
        permissions = {(p.permission.name, p.view_menu.name) for p in user.roles[0].permissions}
        assert all(action in {"can_read", "can_get", "can_time_range", "can_log"} for action, _ in permissions)
        assert all("SQLLab" not in view and view != "Database" for _, view in permissions)
        source = db.session.get(Database, provision["database_id"])
        for verb, statement in {
            "CREATE": "CREATE TABLE ads.public_demo_write_probe (i INTEGER)",
            "INSERT": "INSERT INTO ads.ads_executive_dashboard SELECT * FROM ads.ads_executive_dashboard WHERE FALSE",
            "UPDATE": "UPDATE ads.ads_executive_dashboard SET orders = orders WHERE FALSE",
            "DELETE": "DELETE FROM ads.ads_executive_dashboard WHERE FALSE",
        }.items():
            with source.get_sqla_engine() as engine, engine.connect() as conn, conn.begin() as transaction:
                try:
                    conn.exec_driver_sql(statement)
                except DBAPIError as error:
                    assert "read-only" in str(error).lower() or "read only" in str(error).lower()
                    print(f"{verb} rejected by read-only DuckDB")
                else:
                    transaction.rollback()
                    raise RuntimeError(f"Warehouse accepted {verb}")
        print(f"retail_demo has RetailDemoRole, {len(permissions)} grants and {len(allowed)} dashboards")


if __name__ == "__main__":
    main()
