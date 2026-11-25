"""Validated pipeline thresholds shared by deterministic checks and rollups."""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    memory_limit: str = "512MB"
    threads: int = 2
    as_of_date: date | None = None
    max_order_age_days: int = 45
    max_source_lag_days: int = 45
    payment_tolerance_brl: Decimal = Decimal("0.02")
    payment_mismatch_severity: str = "warning"
    late_alert_min_orders: int = 1
    late_alert_rate: float = 0.25
    sales_decline_threshold: float = 0.10

    def __post_init__(self):
        if not re.fullmatch(r"[1-9][0-9]*(MB|GB|MiB|GiB)", self.memory_limit):
            raise ValueError("memory_limit must be a positive size with units")
        for key in ("threads", "late_alert_min_orders", "max_order_age_days", "max_source_lag_days"):
            lower = 1 if key in ("threads", "late_alert_min_orders") else 0
            value = getattr(self, key)
            if type(value) is not int or value < lower:
                raise ValueError(f"{key} must be an integer >= {lower}")
        if self.as_of_date is not None and type(self.as_of_date) is not date:
            raise ValueError("as_of_date must be an ISO calendar date")
        if (not self.payment_tolerance_brl.is_finite() or self.payment_tolerance_brl < 0
                or self.payment_mismatch_severity not in {"warning", "error"}):
            raise ValueError("Invalid payment reconciliation policy")
        for key in ("late_alert_rate", "sales_decline_threshold"):
            value = getattr(self, key)
            if type(value) not in (int, float) or not 0 < value <= 1:
                raise ValueError(f"{key} must be in (0, 1]")

    @classmethod
    def load(cls, path: Path):
        values = yaml.safe_load(path.read_text()) or {}
        if not isinstance(values, dict):
            raise ValueError("Warehouse config must be a mapping")
        if "payment_tolerance_brl" in values:
            values["payment_tolerance_brl"] = Decimal(str(values["payment_tolerance_brl"]))
        return cls(**values)

    def prepare_sql(self, conn):
        conn.execute("""
            CREATE TEMP TABLE run_settings AS
            SELECT ?::BIGINT late_alert_min_orders, ?::DOUBLE late_alert_rate, ?::DOUBLE sales_decline_threshold
        """, [self.late_alert_min_orders, self.late_alert_rate, self.sales_decline_threshold])
