"""Read-only context-gathering helpers for the multi-agent brain.

Each function returns a compact dict/list of facts that gets serialized into
the user-message of an agent call. The agents themselves never execute these
tools live (no `tool_use` blocks) — the orchestrator pre-computes whatever the
agent needs and stuffs it into the prompt. This keeps the brain strictly
read-only: deterministic Python is the only path to orders, risk params,
or DB writes beyond `agent_actions`.

Stage 2 ships the helpers required for `brain_pm_sanity_check` and
`brain_daily_synthesis`. Future agents (technical analyst, sentiment) will
add more helpers here as needed.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone

PROJECT_ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from lib.db import get_connection  # noqa: E402


# ── Trade / signal context ───────────────────────────────────────────────────


def get_open_positions() -> list[dict]:
    """All currently-open trades across both pillars, sorted by pillar+asset."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT id, pillar, asset, direction, entry_price, quantity, leverage,
                      stop_loss, take_profit, strategy, confluence_score, opened_at
                 FROM trades
                WHERE status = 'open'
                ORDER BY pillar, asset"""
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_recent_trades(days: int = 7, strategy: str | None = None) -> list[dict]:
    """Last N days of closed trades. Strategy filter optional."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    conn = get_connection()
    try:
        q = """SELECT id, pillar, asset, direction, entry_price, exit_price,
                       pnl_usd, pnl_pct, strategy, confluence_score, opened_at, closed_at
                 FROM trades
                WHERE status = 'closed' AND COALESCE(closed_at, timestamp) >= ?"""
        params: list = [cutoff]
        if strategy:
            q += " AND strategy = ?"
            params.append(strategy)
        q += " ORDER BY closed_at DESC LIMIT 50"
        rows = conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_risk_state() -> dict:
    """Most recent portfolio_risk_snapshots row + key system_state values."""
    conn = get_connection()
    try:
        snap = conn.execute(
            "SELECT * FROM portfolio_risk_snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone()
        sys_state = conn.execute("SELECT key, value FROM system_state").fetchall()
        return {
            "latest_snapshot": dict(snap) if snap else None,
            "system_state": {r["key"]: r["value"] for r in sys_state},
        }
    finally:
        conn.close()


# ── Polymarket context ──────────────────────────────────────────────────────


def get_pm_history(market_question_substr: str | None = None, days: int = 30) -> dict:
    """Stats on recent PM bets, optionally filtered by question substring.

    Used by the Polymarket Specialist to compute base rates for similar
    markets: 'we have 12 prior bets on similar markets, 4 winners, avg
    edge 6%' — context the LLM uses to sanity-check the proposed bet.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    conn = get_connection()
    try:
        q = """SELECT t.id, t.asset, t.direction, t.pnl_usd, t.entry_price,
                       pb.market_question, pb.estimated_probability, pb.edge_pct,
                       pb.discovery_method, t.status, t.confluence_score
                 FROM polymarket_bets pb
                 JOIN trades t ON t.id = pb.trade_id
                WHERE COALESCE(t.closed_at, t.timestamp) >= ?"""
        params: list = [cutoff]
        if market_question_substr:
            q += " AND LOWER(pb.market_question) LIKE ?"
            params.append(f"%{market_question_substr.lower()}%")
        q += " ORDER BY t.timestamp DESC LIMIT 30"
        rows = conn.execute(q, params).fetchall()
        bets = [dict(r) for r in rows]
        closed = [b for b in bets if b["status"] == "closed"]
        wins = sum(1 for b in closed if (b["pnl_usd"] or 0) > 0)
        return {
            "count": len(bets),
            "closed_count": len(closed),
            "win_count": wins,
            "win_rate": (wins / len(closed)) if closed else None,
            "sample": bets[:10],
        }
    finally:
        conn.close()


def get_tracked_wallets_summary() -> dict:
    """Snapshot of currently-tracked PM wallets from config."""
    path = os.path.join(PROJECT_ROOT, "config", "polymarket_accounts.json")
    if not os.path.exists(path):
        return {"tracked_count": 0, "wallets": []}
    try:
        with open(path) as f:
            cfg = json.load(f)
        tracked = cfg.get("tracked_accounts") or []
        return {
            "tracked_count": len(tracked),
            "wallets": [
                {k: w.get(k) for k in ("address", "alias", "skill_score", "win_rate", "total_positions")}
                for w in tracked[:25]
            ],
        }
    except Exception as e:
        return {"tracked_count": 0, "wallets": [], "error": str(e)}


# ── Memory + signals ────────────────────────────────────────────────────────


def get_agent_memory(category: str | None = None, limit: int = 20) -> list[dict]:
    """Pull recent semantic-memory entries (lessons + rules). Newest first."""
    conn = get_connection()
    try:
        q = "SELECT * FROM agent_memory_semantic WHERE superseded_by IS NULL"
        params: list = []
        if category:
            q += " AND category = ?"
            params.append(category)
        q += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_recent_signals(date_str: str | None = None) -> dict:
    """Bundle today's signal files into a compact dict for the synthesizer.

    Reads data/signals/<date>/*.json and returns counts + a small sample per
    source so the synthesizer has a coherent picture without ballooning the
    prompt.
    """
    if not date_str:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    base = os.path.join(PROJECT_ROOT, "data", "signals", date_str)
    out: dict = {"date": date_str, "sources": {}}
    if not os.path.isdir(base):
        return out
    for fname in sorted(os.listdir(base)):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(base, fname)
        try:
            with open(path) as f:
                data = json.load(f)
        except Exception:
            continue
        sample = None
        count = None
        if isinstance(data, list):
            count = len(data)
            sample = data[:3]
        elif isinstance(data, dict):
            # Common keys we recognize
            for k in ("signals", "alerts", "items", "candidates", "setups", "events"):
                if isinstance(data.get(k), list):
                    count = len(data[k])
                    sample = data[k][:3]
                    break
            if count is None:
                count = 1
                sample = {k: v for k, v in list(data.items())[:5]}
        out["sources"][fname] = {"count": count, "sample": sample}
    return out


# ── Cost dashboard ──────────────────────────────────────────────────────────


def get_today_agent_cost() -> dict:
    """Sum agent_actions cost for today + breakdown by job."""
    conn = get_connection()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        total = conn.execute(
            "SELECT COALESCE(SUM(usd_cost), 0) FROM agent_actions WHERE timestamp LIKE ?",
            (f"{today}%",),
        ).fetchone()[0]
        by_job = conn.execute(
            """SELECT job, COUNT(*) AS calls, COALESCE(SUM(usd_cost),0) AS cost
                 FROM agent_actions
                WHERE timestamp LIKE ?
                GROUP BY job
                ORDER BY cost DESC""",
            (f"{today}%",),
        ).fetchall()
        return {
            "date": today,
            "total_usd": float(total or 0),
            "by_job": [dict(r) for r in by_job],
        }
    finally:
        conn.close()
