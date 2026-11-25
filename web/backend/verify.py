"""Verify the public gateway and the local quota ledger without provider calls."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import time

import httpx
import jwt

from . import app


def verify_gateway(origin):
    with httpx.Client(base_url=origin, timeout=20, trust_env=False) as http:
        for path in ("/", "/analytics", "/analyst", "/quality", "/data", "/api/health"):
            assert http.get(path).status_code == 200, path
        for path in ("/login/", "/sqllab/", "/superset/welcome/", "/api/v1/database/", "/api/v1/security/login",
                     "/docs", "/redoc", "/openapi.json", "/bi-proxy/api/v1/dashboard/1",
                     "/data/raw/olist_orders_dataset.csv", "/data/processed/olist/latest.json", "/api/ai/internal"):
            assert http.get(path).status_code == 404, path
        assert http.get("/api/public/overview", headers={"Origin": "https://unapproved.invalid"}).status_code == 403
        assert http.options("/api/ai/chat", headers={"Origin": "https://unapproved.invalid"}).status_code == 403
        assert http.post("/api/ai/chat", json={"question": "q" * 28_001}).status_code == 413
        assert http.post("/api/ai/chat", json={"sql": "SELECT 1"}).status_code == 422
        if not http.get("/api/ai/status").json()["enabled"]:
            assert http.post("/api/ai/chat", json={"question": "What was GMV?"}).status_code == 503
        dashboards = http.get("/api/public/dashboards").json()
        assert len(dashboards) == 6
        accepted = http.post("/api/superset/guest-token", headers={"Origin": origin},
                             json={"dashboard": dashboards[0]["slug"]})
        assert accepted.status_code == 200
        assert http.post("/api/superset/guest-token", headers={"Origin": origin},
                         json={"dashboard": "unapproved"}).status_code == 404
        token = accepted.json()["token"]
        claims = jwt.decode(token, app.guest_key(), audience="retail-demo", algorithms=["HS256"])
        assert claims["exp"] - claims["iat"] == 180
        assert claims["resources"] == [{"type": "dashboard", "id": dashboards[0]["uuid"]}]
        scopes = app.data()["dashboards"]
        board = scopes[dashboards[0]["slug"]]
        other = scopes[dashboards[1]["slug"]]
        guest = {"X-GuestToken": token}
        assert http.get(f"/api/v1/dashboard/{board['id']}", headers=guest).status_code == 200
        assert http.get(f"/api/v1/dashboard/{other['id']}", headers=guest).status_code == 403
        assert http.put(f"/api/v1/dashboard/{board['id']}", headers=guest, json={}).status_code in (403, 405)
        assert http.get("/api/v1/database/", headers=guest).status_code == 404
        roles = http.get("/api/v1/me/roles/", headers=guest).json()["result"]["roles"]
        assert tuple(roles) == ("RetailDemoRole",)
        assert all(p[0] in {"can_read", "can_time_range", "can_get", "can_log"} for p in roles["RetailDemoRole"])
        expired = jwt.encode(claims | {"iat": int(time()) - 200, "exp": int(time()) - 1},
                             app.guest_key(), algorithm="HS256")
        assert http.get(f"/api/v1/dashboard/{board['id']}",
                        headers={"X-GuestToken": expired}).status_code == 401
        print("HTTPS pages, API restrictions, guest role, scope and expiration passed")


def verify_limits():
    from decimal import Decimal
    from fastapi import HTTPException

    with TemporaryDirectory(dir=app.RUNTIME) as folder:
        analyst = app.Analyst(app.ROOT, Path(folder))
        analyst.input_price = Decimal("1")
        analyst.output_price = Decimal("1")
        analyst.reservation = analyst.cost(40_000, 1_000)
        analyst.daily_limit = 10 * analyst.reservation
        for _ in range(analyst.limits.minute):
            analyst.reserve("192.0.2.1", "test-visitor")
        try:
            analyst.reserve("192.0.2.1", "other-visitor")
        except HTTPException as error:
            assert error.status_code == 429
        else:
            raise AssertionError("IP quota was not enforced")
        analyst.daily_limit = analyst.limits.minute * analyst.reservation
        try:
            analyst.reserve("192.0.2.2", "second-visitor")
        except HTTPException as error:
            assert error.status_code == 429
        else:
            raise AssertionError("Daily cost ceiling was not enforced")
        with analyst.connect() as conn:
            assert conn.execute("SELECT COUNT(*), SUM(cost) FROM requests").fetchone() == (
                analyst.limits.minute, analyst.daily_limit,
            )
    print("Persistent IP quota and daily monetary ceiling passed with isolated test inputs")


if __name__ == "__main__":
    verify_gateway(app.origin())
    verify_limits()
