"""Settings for the localhost retail BI deployment."""

import os
from urllib.parse import quote

SECRET_KEY = os.environ["SUPERSET_SECRET_KEY"]
SQLALCHEMY_DATABASE_URI = (
    f"postgresql+psycopg2://superset:{quote(os.environ['POSTGRES_PASSWORD'], safe='')}@metadata:5432/superset"
)
SQLALCHEMY_ENGINE_OPTIONS = {"pool_size": 4, "max_overflow": 2, "pool_pre_ping": True}
SUPERSET_WEBSERVER_TIMEOUT = 45
SQLLAB_TIMEOUT = 45
SQL_MAX_ROW = 10000
ROW_LIMIT = 5000
ENABLE_PROXY_FIX = False
WTF_CSRF_ENABLED = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
FEATURE_FLAGS = {
    "GLOBAL_ASYNC_QUERIES": False,
    "ALERT_REPORTS": False,
    "ENABLE_TEMPLATE_PROCESSING": False,
    "DASHBOARD_NATIVE_FILTERS": True,
}
