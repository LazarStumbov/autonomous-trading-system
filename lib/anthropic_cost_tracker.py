"""Centralised cost tracking + monthly kill switch for Anthropic API calls.

Wraps every API call with `track_call(...)` so MTD spend lands in the
`api_costs` table. When MTD exceeds `ANTHROPIC_MONTHLY_USD_CAP` (default $50)
non-Opus-daily calls return a stub. The daily brief is allow-listed because
the bot still needs to make decisions — just with thinner context.

Pricing reference (per million tokens, USD, as of Apr 2026):

    | Model                  | Input | Cached | Output |
    |------------------------|------:|-------:|-------:|
    | claude-haiku-3-5       | 0.80  |  0.08  | 4.00   |
    | claude-sonnet-4-5      | 3.00  |  0.30  | 15.00  |
    | claude-sonnet-4-7      | 3.00  |  0.30  | 15.00  |
    | claude-opus-4-7        | 15.00 |  1.50  | 75.00  |

Cached input gets a ~90% discount under prompt caching (5-min TTL ephemeral).
Batch API gets a 50% discount on both input and output. We pass the
`is_batch` flag through and apply the discount when accruing spend.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

_PROJECT_ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from lib.db import get_connection  # noqa: E402


PRICING_PER_MTOK = {
    # (input_usd, cached_input_usd, output_usd)
    "claude-haiku-3-5":   (0.80, 0.08,  4.00),
    "claude-sonnet-4-5":  (3.00, 0.30, 15.00),
    "claude-sonnet-4-7":  (3.00, 0.30, 15.00),
    "claude-opus-4-7":    (15.00, 1.50, 75.00),
}

# Jobs allow-listed once monthly cap is hit. The bot keeps making decisions
# but with thinner context.
ALLOWLIST_AFTER_CAP = {"opus_daily_brief"}

DEFAULT_MONTHLY_CAP_USD = float(os.environ.get("ANTHROPIC_MONTHLY_USD_CAP", "50"))


SCHEMA = """
CREATE TABLE IF NOT EXISTS api_costs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    job TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    cached_input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    is_batch INTEGER NOT NULL DEFAULT 0,
    usd_cost REAL NOT NULL DEFAULT 0,
    notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_api_costs_job   ON api_costs(job);
CREATE INDEX IF NOT EXISTS idx_api_costs_month ON api_costs(timestamp);
"""


@dataclass
class CostRecord:
    job: str
    model: str
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    is_batch: bool = False
    notes: str = ""

    def usd_cost(self) -> float:
        in_p, cache_p, out_p = PRICING_PER_MTOK.get(self.model, (15.0, 1.5, 75.0))
        if self.is_batch:
            in_p, cache_p, out_p = in_p / 2, cache_p / 2, out_p / 2
        return (
            (self.input_tokens / 1_000_000) * in_p
            + (self.cached_input_tokens / 1_000_000) * cache_p
            + (self.output_tokens / 1_000_000) * out_p
        )


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def track_call(
    job: str,
    model: str,
    *,
    input_tokens: int = 0,
    cached_input_tokens: int = 0,
    output_tokens: int = 0,
    is_batch: bool = False,
    notes: str = "",
) -> float:
    """Record an Anthropic API call and return the USD cost accrued.

    Use this AFTER the API call returns — never before — so we don't double-
    count rejections / network failures.
    """
    rec = CostRecord(
        job=job,
        model=model,
        input_tokens=int(input_tokens or 0),
        cached_input_tokens=int(cached_input_tokens or 0),
        output_tokens=int(output_tokens or 0),
        is_batch=bool(is_batch),
        notes=notes,
    )
    cost = rec.usd_cost()
    conn = get_connection()
    try:
        _ensure_schema(conn)
        conn.execute(
            """INSERT INTO api_costs (job, model, input_tokens, cached_input_tokens,
                output_tokens, is_batch, usd_cost, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (rec.job, rec.model, rec.input_tokens, rec.cached_input_tokens,
             rec.output_tokens, 1 if rec.is_batch else 0, cost, rec.notes),
        )
        conn.commit()
    finally:
        conn.close()
    return cost


def mtd_spend(now: Optional[datetime] = None) -> float:
    """Sum of usd_cost rows in the current calendar month (UTC)."""
    now = now or datetime.now(timezone.utc)
    month_prefix = now.strftime("%Y-%m")
    conn = get_connection()
    try:
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT COALESCE(SUM(usd_cost), 0) FROM api_costs WHERE timestamp LIKE ?",
            (f"{month_prefix}%",),
        ).fetchone()
        return float(row[0] or 0)
    finally:
        conn.close()


def cap_reached(monthly_cap_usd: Optional[float] = None) -> bool:
    cap = monthly_cap_usd if monthly_cap_usd is not None else DEFAULT_MONTHLY_CAP_USD
    return mtd_spend() >= cap


def should_allow(job: str, monthly_cap_usd: Optional[float] = None) -> tuple[bool, str]:
    """Gate function called BEFORE any API call.

    Returns (allowed, reason). When False, the caller should skip the call
    and emit a thin-context fallback.
    """
    if not cap_reached(monthly_cap_usd):
        return True, "ok"
    if job in ALLOWLIST_AFTER_CAP:
        return True, "cap_reached_but_allowlisted"
    return False, f"monthly_cap_reached_${DEFAULT_MONTHLY_CAP_USD:.0f}"


def cost_summary(now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    month_prefix = now.strftime("%Y-%m")
    conn = get_connection()
    try:
        _ensure_schema(conn)
        rows = conn.execute(
            """SELECT model, COUNT(*), SUM(input_tokens), SUM(cached_input_tokens),
                      SUM(output_tokens), SUM(usd_cost)
               FROM api_costs WHERE timestamp LIKE ?
               GROUP BY model""",
            (f"{month_prefix}%",),
        ).fetchall()
        by_model = [
            {
                "model": r[0],
                "calls": r[1],
                "input_tokens": r[2] or 0,
                "cached_input_tokens": r[3] or 0,
                "output_tokens": r[4] or 0,
                "usd_cost": r[5] or 0,
            }
            for r in rows
        ]
        total = sum(m["usd_cost"] for m in by_model)
        return {
            "month": month_prefix,
            "mtd_usd": total,
            "monthly_cap_usd": DEFAULT_MONTHLY_CAP_USD,
            "cap_reached": total >= DEFAULT_MONTHLY_CAP_USD,
            "by_model": by_model,
        }
    finally:
        conn.close()


if __name__ == "__main__":
    print(json.dumps(cost_summary(), indent=2))
