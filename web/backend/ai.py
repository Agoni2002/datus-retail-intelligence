"""Enforce persistent preview quotas and isolate live analyst processes."""

import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import signal
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException

LOG = logging.getLogger("retail.security")
INPUT_ALLOWANCE = 40_000
OUTPUT_ALLOWANCE = 1_000


@dataclass(frozen=True)
class Limits:
    minute: int = int(os.getenv("AI_IP_PER_MINUTE", "5"))
    day: int = int(os.getenv("AI_IP_PER_DAY", "20"))
    global_day: int = int(os.getenv("AI_GLOBAL_PER_DAY", "50"))
    seconds: int = min(60, int(os.getenv("AI_TIMEOUT_SECONDS", "60")))


class Analyst:
    def __init__(self, root, runtime):
        self.root = root
        self.runtime = runtime
        self.database = runtime / "ai-quota.sqlite"
        self.lock = asyncio.Lock()
        self.limits = Limits()
        self.python = os.getenv("DATUS_PYTHON", "/home/userz/Projects/Datus-agent/.venv/bin/python")
        self.model = os.getenv("RETAIL_MODEL", "gpt-4.1-mini")
        key = os.getenv("OPENAI_API_KEY", "")
        try:
            budget, price_in, price_out = (
                Decimal(os.getenv(name, "")) for name in ("AI_DAILY_USD", "AI_INPUT_USD_PER_MTOK",
                                                          "AI_OUTPUT_USD_PER_MTOK")
            )
            if not all(value.is_finite() and value > 0 for value in (budget, price_in, price_out)):
                raise ValueError
            self.daily_limit = int(budget * 1_000_000)
            self.input_price, self.output_price = price_in, price_out
            self.reservation = self.cost(INPUT_ALLOWANCE, OUTPUT_ALLOWANCE)
            self.enabled = (os.getenv("AI_ENABLED", "false").lower() == "true" and bool(key)
                            and 0 < self.reservation <= self.daily_limit and os.path.isfile(self.python)
                            and min(self.limits.minute, self.limits.day, self.limits.global_day, self.limits.seconds) > 0
                            and not any(os.getenv(name) for name in ("OPENAI_BASE_URL", "OPENAI_API_BASE", "LITELLM_API_BASE")))
        except (InvalidOperation, ValueError):
            self.enabled = False

    def cost(self, tokens_in, tokens_out):
        return int((self.input_price * tokens_in + self.output_price * tokens_out).to_integral_value(rounding="ROUND_CEILING"))

    def status(self):
        return {"enabled": self.enabled, "message": ("Live guarded analysis is available" if self.enabled
                else "Live AI inference is not configured. Business analytics and data quality remain available."),
                "limits": {"ipPerMinute": self.limits.minute, "ipPerDay": self.limits.day,
                           "globalPerDay": self.limits.global_day, "maxOutputTokens": OUTPUT_ALLOWANCE,
                           "timeoutSeconds": self.limits.seconds, "concurrent": 1}}

    def connect(self):
        connection = sqlite3.connect(self.database)
        connection.execute("""CREATE TABLE IF NOT EXISTS requests
            (id INTEGER PRIMARY KEY, day TEXT NOT NULL, ts INTEGER NOT NULL, ip TEXT NOT NULL,
            visitor TEXT NOT NULL, cost INTEGER NOT NULL, input_tokens INTEGER, output_tokens INTEGER)""")
        return connection

    def reserve(self, ip, visitor):
        now = int(time.time())
        today = datetime.now(timezone.utc).date().isoformat()
        key = (self.root / "superset/.runtime/demo-signing-key").read_bytes()
        address = ipaddress.ip_address(ip).compressed
        peer = hmac.new(key, address.encode(), hashlib.sha256).hexdigest()
        user = hmac.new(key, visitor.encode(), hashlib.sha256).hexdigest()
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            minute, daily = conn.execute("""SELECT COUNT(*) FILTER (WHERE ts > ?),
                COUNT(*) FILTER (WHERE day = ?) FROM requests WHERE ip = ?""",
                (now - 60, today, peer)).fetchone()
            visitor_daily = conn.execute("SELECT COUNT(*) FROM requests WHERE day=? AND visitor=?",
                                         (today, user)).fetchone()[0]
            count, cost = conn.execute("SELECT COUNT(*), COALESCE(SUM(cost),0) FROM requests WHERE day=?",
                                       (today,)).fetchone()
            if (minute >= self.limits.minute or daily >= self.limits.day or visitor_daily >= self.limits.day
                    or count >= self.limits.global_day or cost + self.reservation > self.daily_limit):
                LOG.info("ai_quota_rejected")
                raise HTTPException(429, "Live analysis quota is exhausted")
            cursor = conn.execute("INSERT INTO requests(day,ts,ip,visitor,cost) VALUES (?,?,?,?,?)",
                                  (today, now, peer, user, self.reservation))
            return cursor.lastrowid

    async def answer(self, ip, visitor, question, snapshot):
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            raise HTTPException(403, "Trusted client address is unavailable") from None
        if self.lock.locked():
            raise HTTPException(429, "An analysis is already in progress")
        async with self.lock:
            row = self.reserve(ip, visitor)
            env = {key: value for key, value in os.environ.items()
                   if key in {"HOME", "PATH", "OPENAI_API_KEY", "SSL_CERT_FILE", "SSL_CERT_DIR"}}
            env.update(RETAIL_MODEL=self.model, OPENAI_AGENTS_DISABLE_TRACING="1", PYTHONDONTWRITEBYTECODE="1")
            process = await asyncio.create_subprocess_exec(
                self.python, "-B", "-m", "web.backend.live_worker", cwd=self.root,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, start_new_session=True, env=env,
            )
            try:
                payload = json.dumps({"question": question, "snapshot": snapshot}).encode()
                output, _ = await asyncio.wait_for(process.communicate(payload), self.limits.seconds)
            except (TimeoutError, asyncio.CancelledError):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await process.wait()
                raise HTTPException(504, "Analysis exceeded the demo timeout") from None
            if process.returncode != 0 or len(output) > 64_000:
                LOG.info("ai_guarded_inference_failed")
                raise HTTPException(502, "Guarded analysis did not complete")
            report = json.loads(output)
            usage = report["usage"]
            if usage["complete"]:
                estimated = self.cost(usage["input"], usage["output"])
                with self.connect() as conn:
                    conn.execute("UPDATE requests SET cost=?, input_tokens=?, output_tokens=? WHERE id=?",
                                 (max(estimated, 0), usage["input"], usage["output"], row))
            if not report["answer"]:
                raise HTTPException(502, "Analysis returned no verified evidence")
            return report["answer"]
