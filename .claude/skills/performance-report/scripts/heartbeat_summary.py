"""Daily Haiku-tier Telegram heartbeat.

Single short message every morning summarizing overnight state. Uses
Haiku 4.5 (light tier in lib.llm_brain) — costs ~$0.001 per call,
~$0.30/month total.

Reads:
  - portfolio_risk_snapshots (latest row)
  - trades (last 24h: opened, closed, P&L)
  - system_state heartbeats + paper_balance
  - agent_actions cost MTD (so user sees brain spend)

Output: 5–8 line Telegram message. Pure status update — no decisions,
no narrative. Haiku is plenty for this; it just needs to format the
numbers tersely.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone, timedelta

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from lib.db import get_connection, get_system_state  # noqa: E402


def _gather() -> dict:
    """Build the compact context dict for the LLM. All read-only."""
    now = datetime.now(timezone.utc)
    cutoff_24h = (now - timedelta(hours=24)).isoformat()
    conn = get_connection()
    try:
        # Recent trades
        opens = conn.execute(
            "SELECT id, asset, direction, broker, opened_at "
            "FROM trades WHERE status='open' AND opened_at >= ? "
            "ORDER BY opened_at DESC LIMIT 20",
            (cutoff_24h,),
        ).fetchall()
        closes = conn.execute(
            "SELECT id, asset, pnl_usd, pnl_pct, closed_at "
            "FROM trades WHERE status='closed' AND COALESCE(closed_at, timestamp) >= ? "
            "ORDER BY closed_at DESC LIMIT 20",
            (cutoff_24h,),
        ).fetchall()
        # Outstanding book
        all_open = conn.execute(
            "SELECT pillar, COUNT(*) AS n FROM trades WHERE status='open' GROUP BY pillar"
        ).fetchall()
        # Latest risk snapshot
        risk = conn.execute(
            "SELECT * FROM portfolio_risk_snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone()
        # Heartbeats
        hb = {}
        for r in conn.execute(
            "SELECT key, value FROM system_state WHERE key LIKE 'last_cron_at%'"
        ):
            hb[r["key"]] = r["value"]
        # MTD API cost
        month_prefix = now.strftime("%Y-%m")
        api = conn.execute(
            "SELECT COALESCE(SUM(usd_cost),0) AS total, COUNT(*) AS n "
            "FROM api_costs WHERE timestamp LIKE ?",
            (f"{month_prefix}%",),
        ).fetchone()
        # Paper balance
        paper_balance = get_system_state(conn, "paper_balance_usd") or "?"
        # Trading halt + loss streak
        halted = get_system_state(conn, "trading_halted") or "false"
        losses = get_system_state(conn, "consecutive_losses") or "0"
        return {
            "as_of_utc": now.isoformat(),
            "opens_24h": [dict(r) for r in opens],
            "closes_24h": [dict(r) for r in closes],
            "open_book_by_pillar": {r["pillar"]: r["n"] for r in all_open},
            "latest_risk": dict(risk) if risk else None,
            "heartbeats": hb,
            "api_spend_mtd_usd": float(api["total"] or 0),
            "api_calls_mtd": int(api["n"] or 0),
            "paper_balance_usd": paper_balance,
            "trading_halted": halted,
            "consecutive_losses": losses,
        }
    finally:
        conn.close()


_PROMPT = """You are a curt, factual operations bot. The user is the trader and just woke up. Give them a 6–8 line plaintext Telegram status update on the system. Hard rules:
- No emojis except a single 🟢 / 🟡 / 🔴 at the very start (green if system_ok, yellow if any cron stale or 1 loss streak, red if halted / VaR>30% / loss-streak >= 3).
- One number per line. No prose padding.
- Bullets with '• ' prefix.
- Show: open positions count + gross, 24h opened/closed counts with net P&L $, latest VaR %, paper balance, MTD API spend $, cron freshness (use the largest age across jobs).
- Final line: any anomaly ('all clear' if nothing to flag).
Return ONLY the message text — no JSON, no markdown headers."""


def main() -> int:
    ctx = _gather()
    try:
        from lib import llm_brain
    except ImportError as e:
        print(f"[heartbeat] llm_brain not available: {e}")
        return 1

    import json
    user_block = json.dumps(ctx, default=str)[:8000]
    resp = llm_brain.call(
        job="heartbeat_summary",
        tier="light",
        system=_PROMPT,
        user=user_block,
        max_tokens=300,
        parse_json=False,
    )
    if not resp.ok or not resp.text.strip():
        # Stub fallback: terse summary built deterministically.
        opens = len(ctx.get("opens_24h", []))
        closes_list = ctx.get("closes_24h", [])
        closes = len(closes_list)
        net_pnl = sum((c.get("pnl_usd") or 0) for c in closes_list)
        risk = ctx.get("latest_risk") or {}
        var_pct = risk.get("var_95_pct")
        bal = ctx.get("paper_balance_usd")
        api_usd = ctx.get("api_spend_mtd_usd", 0)
        msg = (
            f"🟡 heartbeat (LLM stub)\n"
            f"• open: {ctx.get('open_book_by_pillar', {})}\n"
            f"• 24h: {opens} opened, {closes} closed, net ${net_pnl:+.2f}\n"
            f"• VaR 1d 95%: {var_pct}%\n"
            f"• paper balance: ${bal}\n"
            f"• MTD API: ${api_usd:.2f}\n"
        )
    else:
        msg = resp.text.strip()

    print(msg)
    try:
        from lib.notifier import send_telegram
        send_telegram(msg)
    except Exception as e:
        print(f"[heartbeat] telegram send failed (non-fatal): {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
