"""Live-trading readiness gate.

Prints a PASS/FAIL checklist. Must fully pass before flipping PAPER_MODE=false.
Run manually:   python3 lib/live_readiness.py
Telegram:       /readiness  (wired in modal/trading_webhook.py)

Checks:
  1. ≥ 30 closed paper trades total
  2. Paper win rate ≥ 45% over the last 30 closed trades
  3. No trading_halted event in the last 7 days
  4. OKX live API keys present in env
  5. ≥ 5 partial_closes rows with tier 1-3 (TP tiers exercised)
  6. ≥ 3 strategies in mode='backtest_validated'
  7. PM resolver executed at least once in the last 24 h
     (proxied by: at least one polymarket trade has a non-null resolved_at)
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

PROJECT_ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from lib.db import get_connection, get_system_state


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _check_closed_trades(conn) -> tuple[bool, str]:
    row = conn.execute("SELECT COUNT(*) FROM trades WHERE status='closed' AND pillar='market'").fetchone()
    n = int(row[0] or 0)
    ok = n >= 30
    return ok, f"closed market trades: {n}/30 {'✓' if ok else '✗'}"


def _check_win_rate(conn) -> tuple[bool, str]:
    rows = conn.execute(
        """SELECT pnl_usd FROM trades
           WHERE status='closed' AND pillar='market'
           ORDER BY closed_at DESC LIMIT 30"""
    ).fetchall()
    if not rows:
        return False, "win rate (last 30): no closed trades ✗"
    wins = sum(1 for r in rows if (r[0] or 0) > 0)
    wr = wins / len(rows)
    ok = wr >= 0.45
    return ok, f"win rate (last {len(rows)}): {wr:.0%} {'✓' if ok else '✗ (need ≥45%)'}"


def _check_no_halt(conn) -> tuple[bool, str]:
    cutoff = (_utcnow() - timedelta(days=7)).isoformat()
    row = conn.execute(
        """SELECT COUNT(*) FROM system_state
           WHERE key='trading_halted' AND value='true' AND updated_at >= ?""",
        (cutoff,),
    ).fetchone()
    n = int(row[0] or 0)
    ok = n == 0
    return ok, f"no halt events (7d): {'✓' if ok else f'{n} halt event(s) found ✗'}"


def _check_okx_keys() -> tuple[bool, str]:
    """Check OKX credentials are present, gated by BROKER_MODE.

    For BROKER_MODE=live we need real OKX_API_KEY/OKX_SECRET_KEY/OKX_PASSPHRASE
    AND OKX_DEMO must NOT be true. For BROKER_MODE=demo we still need keys
    (OKX demo trading requires a separate key pair generated in the demo
    portal), but OKX_DEMO must be true. Fixes the earlier typo where the
    env var was `OKX_SECRET` instead of `OKX_SECRET_KEY` — the okx_adapter
    reads `OKX_SECRET_KEY`, so the live-readiness check was looking in the
    wrong place.
    """
    key = os.environ.get("OKX_API_KEY", "")
    # okx_adapter reads OKX_SECRET_KEY; accept either name for backwards compat
    secret = os.environ.get("OKX_SECRET_KEY", "") or os.environ.get("OKX_SECRET", "")
    passphrase = os.environ.get("OKX_PASSPHRASE", "")
    okx_demo = os.environ.get("OKX_DEMO", "").lower().strip()
    if not (key and secret and passphrase):
        try:
            from dotenv import dotenv_values
            env = dotenv_values(os.path.join(PROJECT_ROOT, ".env"))
            key = key or env.get("OKX_API_KEY", "")
            secret = secret or env.get("OKX_SECRET_KEY", "") or env.get("OKX_SECRET", "")
            passphrase = passphrase or env.get("OKX_PASSPHRASE", "")
            okx_demo = okx_demo or (env.get("OKX_DEMO", "") or "").lower().strip()
        except Exception:
            pass
    keys_present = bool(key and secret and passphrase)
    broker_mode_val = (os.environ.get("BROKER_MODE", "") or "").lower().strip()
    if broker_mode_val == "live":
        if not keys_present:
            return False, "OKX live keys: ✗ (OKX_API_KEY / OKX_SECRET_KEY / OKX_PASSPHRASE missing)"
        if okx_demo == "true":
            return False, "OKX live keys: ✗ (OKX_DEMO=true with BROKER_MODE=live — refusing)"
        return True, "OKX live keys: ✓"
    # demo or synthetic — keys are nice-to-have for demo, irrelevant for synthetic
    return keys_present, f"OKX keys: {'✓' if keys_present else '(missing — only needed for live or demo)'}"


def _check_partial_tp_hits(conn) -> tuple[bool, str]:
    row = conn.execute(
        "SELECT COUNT(*) FROM partial_closes WHERE tier BETWEEN 1 AND 3"
    ).fetchone()
    n = int(row[0] or 0)
    ok = n >= 5
    return ok, f"TP-tier hits (partial_closes tier 1-3): {n}/5 {'✓' if ok else '✗'}"


def _check_validated_strategies(conn) -> tuple[bool, str]:
    row = conn.execute(
        "SELECT COUNT(*) FROM strategy_registry WHERE mode='backtest_validated'"
    ).fetchone()
    n = int(row[0] or 0)
    ok = n >= 3
    return ok, f"backtest_validated strategies: {n}/3 {'✓' if ok else '✗'}"


def _check_resolver_ran(conn) -> tuple[bool, str]:
    row = conn.execute(
        "SELECT COUNT(*) FROM polymarket_bets WHERE resolved_at IS NOT NULL"
    ).fetchone()
    n = int(row[0] or 0)
    ok = n >= 1
    return ok, f"PM resolver ran (≥1 resolved bet): {'✓' if ok else '✗ (no resolved bets yet)'}"


def is_ready_for_live() -> tuple[bool, list[str]]:
    """Run all checks. Returns (all_passed, list_of_check_strings)."""
    conn = get_connection()
    try:
        checks = [
            _check_closed_trades(conn),
            _check_win_rate(conn),
            _check_no_halt(conn),
            _check_okx_keys(),
            _check_partial_tp_hits(conn),
            _check_validated_strategies(conn),
            _check_resolver_ran(conn),
        ]
    finally:
        conn.close()

    all_passed = all(ok for ok, _ in checks)
    lines = [msg for _, msg in checks]
    return all_passed, lines


def format_report() -> str:
    passed, lines = is_ready_for_live()
    status = "PASS — ready for live trading" if passed else "FAIL — not ready yet"
    header = f"Live Readiness: {status}"
    body = "\n".join(f"  {line}" for line in lines)
    return f"{header}\n{body}"


if __name__ == "__main__":
    report = format_report()
    print(report)
    passed, _ = is_ready_for_live()
    sys.exit(0 if passed else 1)
