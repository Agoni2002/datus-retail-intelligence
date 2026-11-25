"""Shared connection settings and Superset REST client."""

import hashlib
import json
import os
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import prison
import requests
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

BASE = Path(__file__).resolve().parents[1]
SERVER = "http://127.0.0.1:8088"
DATABASE_NAME = "Olist · validated read-only snapshot"
CONNECT_ARGS = {
    "read_only": True,
    "config": {"enable_external_access": "false", "threads": "1", "memory_limit": "256MB"},
}
EXTRA = json.dumps({"engine_params": {"connect_args": CONNECT_ARGS}, "metadata_params": {}})


def read_runtime(filename):
    return json.loads((BASE / "runtime" / filename).read_text())


def digest(path):
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def warehouse(receipt):
    path = Path(receipt["container_path"])
    if not os.statvfs(path).f_flag & os.ST_RDONLY:
        raise RuntimeError("The warehouse bind mount must be read-only")
    if digest(path) != receipt["sha256"]:
        raise RuntimeError("The mounted snapshot SHA-256 differs from the host receipt")
    url = "duckdb:///" + str(path)
    return url, create_engine(url, connect_args=CONNECT_ARGS, poolclass=NullPool)


def asset_uuid(*parts):
    return str(uuid5(NAMESPACE_URL, "local-retail-superset/" + "/".join(parts)))


class API:
    def __init__(self):
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers["Referer"] = SERVER + "/"
        login = self.call("POST", "/security/login", {
            "username": os.environ["SUPERSET_ADMIN_USERNAME"],
            "password": os.environ["SUPERSET_ADMIN_PASSWORD"],
            "provider": "db",
            "refresh": False,
        })
        self.session.headers["Authorization"] = f"Bearer {login['access_token']}"
        self.session.headers["X-CSRFToken"] = self.call("GET", "/security/csrf_token/")["result"]

    def call(self, method, path, body=None, query=None):
        response = self.session.request(method, SERVER + "/api/v1" + path, json=body,
                                        params={"q": prison.dumps(query)} if query else None, timeout=55)
        if not response.ok:
            # Login response details and authorization headers are never emitted.
            if path == "/security/login":
                raise RuntimeError(f"Superset administrator login failed ({response.status_code})")
            try:
                detail = response.json().get("message") or response.json().get("errors", "")
            except ValueError:
                detail = ""
            raise RuntimeError(f"{method} {path} failed ({response.status_code}): {detail}")
        return response.json() if response.content else {}

    def list(self, kind):
        page = 0
        while True:
            result = self.call("GET", f"/{kind}/", query={"page": page, "page_size": 100})
            rows = result["result"]
            yield from rows
            if (page + 1) * 100 >= result["count"] or not rows:
                return
            page += 1

    def get(self, kind, item_id):
        return self.call("GET", f"/{kind}/{item_id}")["result"]

    def save(self, kind, body, item_id=None):
        if item_id is None:
            return self.call("POST", f"/{kind}/", body)["id"]
        self.call("PUT", f"/{kind}/{item_id}", body)
        return item_id
