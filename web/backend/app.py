"""Public API and restricted same-origin Superset gateway."""

import json
import logging
import os
import re
import secrets
import time
from pathlib import Path

import httpx
import jwt
import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from .ai import Analyst

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "deployment/.runtime"
ISSUER_KEY = ROOT / "superset/.runtime/demo-signing-key"
UPSTREAM = "http://127.0.0.1:8088"
APP = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
LOG = logging.getLogger("retail.security")
ANALYST = Analyst(ROOT, RUNTIME)
UUID = r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}"
SAFE_HEADERS = ("content-type", "content-security-policy", "x-frame-options",
                "cache-control", "etag", "last-modified", "referrer-policy")
client = httpx.AsyncClient(timeout=httpx.Timeout(30, connect=3), trust_env=False,
                           limits=httpx.Limits(max_connections=10, max_keepalive_connections=4))


def data():
    try:
        return json.loads((RUNTIME / "public-data.json").read_text())
    except (OSError, ValueError):
        raise HTTPException(503, "Demo data is being prepared") from None


def origin():
    try:
        return (RUNTIME / "origin").read_text().strip()
    except OSError:
        return ""


def guest_key():
    return ISSUER_KEY.read_text().strip()


@APP.middleware("http")
async def public_boundary(request, call_next):
    supplied = request.headers.get("origin")
    if supplied and supplied != origin():
        LOG.info("cross_origin_rejected")
        return JSONResponse({"detail": "Origin not allowed"}, 403)
    if request.method == "OPTIONS":
        return JSONResponse({"detail": "Cross-origin requests are unavailable"}, 403)
    try:
        return await call_next(request)
    except Exception as error:
        LOG.error("public_request_failed type=%s", type(error).__name__)
        return JSONResponse({"detail": "Service temporarily unavailable"}, 503)


async def body(request, limit):
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        raise HTTPException(415, "Expected JSON")
    payload = bytearray()
    async for chunk in request.stream():
        payload.extend(chunk)
        if len(payload) > limit:
            LOG.info("oversized_request_rejected")
            raise HTTPException(413, "Request is too large")
    try:
        value = json.loads(payload)
    except (ValueError, RecursionError):
        raise HTTPException(422, "Invalid JSON") from None
    if not isinstance(value, dict):
        raise HTTPException(422, "Expected a JSON object")
    return value


@APP.get("/api/health")
def health():
    data()
    return {"status": "ok"}


@APP.get("/api/public/{section}")
def public_section(section: str):
    if section not in {"overview", "quality", "snapshot", "dashboards"}:
        raise HTTPException(404, "Unknown section")
    content = data()[section]
    if section == "dashboards":
        return [{"slug": slug, "uuid": value["uuid"], "title": value["title"]} for slug, value in content.items()]
    if section == "snapshot":
        metrics = yaml.safe_load((ROOT / "metrics/definitions.yml").read_text())["metrics"]
        content["metrics"] = {key: {field: metric[field] for field in ("meaning", "formula", "limitations")}
                              for key, metric in metrics.items()}
    return content


@APP.post("/api/superset/guest-token")
async def issue_token(request: Request):
    if request.headers.get("origin") != origin() or not origin():
        raise HTTPException(403, "Same-origin request required")
    payload = await body(request, 512)
    slug = payload.get("dashboard")
    if set(payload) != {"dashboard"} or not isinstance(slug, str):
        raise HTTPException(422, "Select an approved dashboard")
    entry = data()["dashboards"].get(slug)
    if not entry:
        raise HTTPException(404, "Unknown dashboard")
    now = int(time.time())
    token = jwt.encode({"type": "guest", "user": {"username": "retail_demo"},
                        "resources": [{"type": "dashboard", "id": entry["uuid"]}], "rls_rules": [],
                        "aud": "retail-demo", "iat": now, "exp": now + 180},
                       guest_key(), algorithm="HS256")
    return JSONResponse({"token": token}, headers={"Cache-Control": "no-store"})


def token_scope(request, dashboards):
    value = request.headers.get("x-guesttoken", "")
    try:
        claims = jwt.decode(value, guest_key(), audience="retail-demo", algorithms=["HS256"],
                            options={"require": ["exp", "iat", "aud"]})
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Guest token required") from None
    resources = claims.get("resources")
    if claims.get("type") == "guest" and isinstance(resources, list) and len(resources) == 1:
        for entry in dashboards.values():
            if resources[0] == {"type": "dashboard", "id": entry["uuid"]}:
                return entry
    raise HTTPException(403, "Unapproved dashboard")


def check_chart(payload, scope):
    form = payload.get("form_data")
    source = payload.get("datasource")
    if not isinstance(form, dict) or not isinstance(source, dict) or source.get("type") != "table":
        raise HTTPException(403, "Chart scope required")
    if form.get("dashboardId") != scope["id"] or payload.get("result_format", "json") != "json":
        raise HTTPException(403, "Chart scope required")
    native = form.get("type") == "NATIVE_FILTER"
    if native:
        target = scope["filters"].get(str(form.get("native_filter_id")), {})
        dataset = target.get("datasetId")
        column = target.get("column", {}).get("name")
    else:
        chart = scope["charts"].get(str(form.get("slice_id")), {})
        dataset = chart.get("dataset")
        axes = chart.get("axes", [])
    if dataset is None or source.get("id") != dataset:
        raise HTTPException(403, "Chart dataset is outside dashboard scope")
    adhoc = form.get("adhoc_filters") or []
    if not isinstance(adhoc, list) or any(
        not isinstance(f, dict) or f.get("expressionType") != "SIMPLE" for f in adhoc
    ):
        raise HTTPException(403, "Custom SQL filters are unavailable")
    queries = payload.get("queries")
    if not isinstance(queries, list) or not 1 <= len(queries) <= 3:
        raise HTTPException(422, "Invalid chart queries")
    for query in queries:
        if not isinstance(query, dict):
            raise HTTPException(422, "Invalid chart query")
        extras = query.get("extras") or {}
        if not isinstance(extras, dict) or any(extras.get(k) for k in ("where", "having")):
            raise HTTPException(403, "Custom SQL filters are unavailable")
        if native and (query.get("columns") != [column] or query.get("metrics") or query.get("orderby")):
            # Native filter option queries may sort by their one approved column.
            if query.get("columns") != [column] or query.get("metrics") or any(
                item not in ([column, True], [column, False]) for item in query.get("orderby", [])
            ):
                raise HTTPException(403, "Unapproved filter query")
        columns, metrics = query.get("columns") or [], query.get("metrics") or []
        if not isinstance(columns, list) or not isinstance(metrics, list) or any(not isinstance(m, str) for m in metrics):
            raise HTTPException(403, "Custom chart expressions are unavailable")
        for index, item in enumerate(columns):
            if isinstance(item, str):
                continue
            if native or not isinstance(item, dict):
                raise HTTPException(403, "Custom chart expressions are unavailable")
            field = item.get("sqlExpression")
            if (field not in axes or item.get("label") != field or item.get("columnType") != "BASE_AXIS"
                    or item.get("isColumnReference") is not True or item.get("expressionType") != "SQL"
                    or item.get("timeGrain") != "P1M"):
                raise HTTPException(403, "Custom chart expressions are unavailable")
            if field != "month_start":
                columns[index] = field
        filter_columns = {"month_start"} | {
            target["column"]["name"] for target in scope["filters"].values()
        }
        filters = query.get("filters") or []
        if not isinstance(filters, list) or len(filters) > 8 or any(
            not isinstance(f, dict) or not isinstance(f.get("col"), str)
            or f["col"] not in filter_columns or f.get("op") not in {"IN", "NOT IN", "TEMPORAL_RANGE"}
            or (isinstance(f.get("val"), list) and (
                len(f["val"]) > 100 or any(not isinstance(value, str) for value in f["val"])
            ))
            or (not isinstance(f.get("val"), list) and not isinstance(f.get("val"), str))
            for f in filters
        ):
            raise HTTPException(403, "Chart filter is outside dashboard scope")
        if native and query.get("post_processing"):
            raise HTTPException(403, "Unapproved filter query")
        row_limit = query.get("row_limit")
        if not isinstance(row_limit, int) or not 0 < row_limit <= 2500:
            raise HTTPException(422, "Invalid chart row limit")


@APP.api_route("/bi-proxy/{path:path}", methods=["GET", "POST"])
async def superset_proxy(request: Request, path: str):
    dashboards = data()["dashboards"]
    headers = {"Cookie": ""}
    content = None
    if re.fullmatch(rf"embedded/{UUID}/?", path) and request.method == "GET":
        if not any(path.split("/")[1] == entry["uuid"] for entry in dashboards.values()):
            raise HTTPException(404, "Unknown dashboard")
        ref = request.headers.get("referer", "")
        if not origin() or not ref.startswith(origin() + "/"):
            raise HTTPException(403, "Embedding origin is not approved")
        headers["Referer"] = ref
    elif path.rstrip("/") == "superset/log" and request.method == "POST":
        # Suppress the iframe's optional telemetry at the public boundary.
        return Response(status_code=204)
    elif path == "api/v1/security/csrf_token/" and request.method == "GET":
        # The Superset embedded client may request this endpoint before the SDK handshake.
        pass
    elif path.startswith(("api/v1/", "superset/")):
        permitted = (r"api/v1/dashboard/\d+/?(?:charts|datasets)?/?",
                     r"api/v1/chart/data/?", r"api/v1/dataset/\d+/?",
                     r"api/v1/time_range/?", r"api/v1/me/roles/?")
        if not any(re.fullmatch(pattern, path) for pattern in permitted):
            raise HTTPException(404, "Unknown embedded route")
        scope = token_scope(request, dashboards)
        headers["X-GuestToken"] = request.headers["x-guesttoken"]
        match = re.match(r"api/v1/(dashboard|dataset)/(\d+)", path)
        if match:
            allowed = {scope["id"]} if match[1] == "dashboard" else {chart["dataset"] for chart in scope["charts"].values()}
            if request.method != "GET" or int(match[2]) not in allowed:
                raise HTTPException(403, "Resource outside dashboard scope")
        elif path.rstrip("/") == "api/v1/chart/data":
            if request.method != "POST":
                raise HTTPException(405, "Method unavailable")
            payload = await body(request, 96_000)
            check_chart(payload, scope)
            content = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        elif request.method != "GET":
            raise HTTPException(405, "Method unavailable")
    else:
        raise HTTPException(404, "Unknown embedded route")
    try:
        async with client.stream(request.method, f"{UPSTREAM}/{path}", headers=headers,
                                 params=request.query_params.multi_items(), content=content) as upstream:
            if upstream.is_redirect or upstream.status_code >= 400:
                LOG.info("embedded_upstream_rejected status=%s", upstream.status_code)
                return JSONResponse({"detail": "Embedded resource unavailable"},
                                    status_code=upstream.status_code if upstream.status_code >= 400 else 403)
            safe = {key: upstream.headers[key] for key in SAFE_HEADERS if key in upstream.headers}
            payload = bytearray()
            async for chunk in upstream.aiter_bytes():
                payload.extend(chunk)
                if len(payload) > 4_000_000:
                    raise HTTPException(502, "Embedded response exceeds the demo limit")
    except httpx.RequestError:
        raise HTTPException(502, "Analytics service unavailable") from None
    if path.rstrip("/") == "api/v1/chart/data":
        document = json.loads(payload)
        for result in document.get("result", []):
            if result.get("error") or result.get("stacktrace"):
                return JSONResponse({"detail": "Embedded chart query failed"}, status_code=422)
            result.pop("query", None)
        payload = json.dumps(document).encode()
    safe["cache-control"] = "no-store"
    return Response(bytes(payload), upstream.status_code, headers=safe)


@APP.get("/api/ai/status")
def ai_status():
    return ANALYST.status()


@APP.post("/api/ai/chat")
async def chat(request: Request):
    payload = await body(request, 28_000)
    question = payload.get("question")
    if set(payload) != {"question"} or not isinstance(question, str) or not 1 <= len(question.strip()) <= 4_000:
        raise HTTPException(422, "Enter a question of up to 4,000 characters")
    if not ANALYST.enabled:
        raise HTTPException(503, "Live AI inference is not configured")
    if request.headers.get("origin") != origin() or not origin():
        raise HTTPException(403, "Same-origin request required")
    ip = request.headers.get("x-retail-client", "")
    session = request.cookies.get("retail_visitor", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{32}", session):
        session = secrets.token_urlsafe(24)
    answer = await ANALYST.answer(ip, session, question.strip(), data()["snapshot"]["version"])
    response = JSONResponse(answer, headers={"Cache-Control": "no-store"})
    response.set_cookie("retail_visitor", session, max_age=86_400, secure=True, httponly=True, samesite="strict")
    return response
