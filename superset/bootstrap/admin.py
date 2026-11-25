"""Create the local BI administrator once, using Flask-AppBuilder."""

import os

from superset.app import create_app
from superset.extensions import appbuilder


with create_app().app_context():
    security = appbuilder.sm
    username = os.environ["SUPERSET_ADMIN_USERNAME"]
    role = security.find_role(security.auth_role_admin)
    user = security.find_user(username=username)
    if user is None:
        user = security.add_user(
            username=username,
            first_name="Retail",
            last_name="Administrator",
            email="retail-admin@localhost.invalid",
            role=role,
            password=os.environ["SUPERSET_ADMIN_PASSWORD"],
        )
    if not user or role not in user.roles:
        raise RuntimeError("The configured local account does not have the Superset administrator role")
