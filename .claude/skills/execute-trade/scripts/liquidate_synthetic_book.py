"""One-shot: close every open trade that was opened in synthetic mode.

When we flip BROKER_MODE from synthetic→demo, the 11 currently-open positions
become orphaned: they exist in our DB with `broker='paper'` but have no
counterpart on OKX demo. position_monitor would keep marking them against the
public price forever. This script closes them at the current public mark and
credits/debits paper_balance_usd accordingly, so we start the demo era with
a clean book.

Idempotent: only acts on trades with status='open' and broker LIKE 'paper%'.
Re-runs do nothing.

Usage:
  python3 .claude/skills/execute-trade/scripts/liquidate_synthetic_book.py --dry-run
  python3 .claude/skills/execute-trade/scripts/liquidate_synthetic_book.py
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from lib.db import get_connection, close_trade  # noqa: E402
from lib.paper_engine import get_public_price, credit_paper_balance  # noqa: E402


def _compute_pnl(trade: dict, exit_price: float) -> tuple[float, float]:
    """Return (pnl_usd, pnl_pct) for a paper trade close.

    Paper trades on the market pillar: pnl = (exit - entry) * qty * sign.
    Polymarket trades: pnl = (exit - entry) * qty * sign (binary contract).
    """
    entry = float(trade["entry_price"] or 0)
    qty = float(trade["quantity"] or 0)
    sign = 1 if trade["direction"] in ("long", "yes") else -1
    pnl_usd = (exit_price - entry) * qty * sign
    pnl_pct = ((exit_price - entry) / entry * 100 * sign) if entry > 0 else 0
    return round(pnl_usd, 4), round(pnl_pct, 4)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="Report what would close; make no changes")
    p.add_argument("--pillar", choices=["market", "polymarket", "all"], default="all",
                   help="Restrict to a single pillar (default: all)")
    args = p.parse_args()

    conn = get_connection()
    q = "SELECT * FROM trades WHERE status='open' AND COALESCE(broker,'') LIKE 'paper%'"
    params: list = []
    if args.pillar != "all":
        q += " AND pillar=?"
        params.append(args.pillar)
    rows = conn.execute(q, params).fetchall()
    trades = [dict(r) for r in rows]

    if not trades:
        print("[liquidate] no open synthetic positions — nothing to do")
        conn.close()
        return 0

    print(f"[liquidate] {len(trades)} open synthetic trades to close (dry_run={args.dry_run}, pillar={args.pillar})")
    total_pnl = 0.0
    skipped: list[dict] = []
    closed: list[dict] = []

    for t in trades:
        asset = t["asset"]
        # Polymarket "asset" is the question text, not a tradable symbol —
        # we can't fetch a public price. Close PM bets at entry price (0 P&L).
        if t["pillar"] == "polymarket":
            exit_price = float(t["entry_price"] or 0)
            note = "polymarket: closed at entry (no public mark available)"
        else:
            price = get_public_price(asset)
            if price is None or price <= 0:
                skipped.append({"id": t["id"], "asset": asset, "reason": "no public price"})
                print(f"  SKIP #{t['id']:3d} {asset:30s}  no public price")
                continue
            exit_price = float(price)
            note = "synthetic close at current public mark"

        pnl_usd, pnl_pct = _compute_pnl(t, exit_price)
        total_pnl += pnl_usd
        closed.append({
            "trade_id": t["id"], "asset": asset, "entry": t["entry_price"],
            "exit": exit_price, "pnl_usd": pnl_usd, "pnl_pct": pnl_pct,
        })
        print(f"  CLOSE #{t['id']:3d} {asset[:30]:30s}  entry={t['entry_price']:.4f}  "
              f"exit={exit_price:.4f}  pnl=${pnl_usd:+.2f} ({pnl_pct:+.2f}%)  [{note}]")

        if not args.dry_run:
            close_trade(conn, t["id"], exit_price, pnl_usd, pnl_pct, fees=0)
            if t["pillar"] == "market":
                # paper_balance accounting only for market pillar (PM bets
                # are a separate bankroll in the design).
                credit_paper_balance(pnl_usd, reason=f"liquidate_synthetic_book:#{t['id']}")

    print(f"\n[liquidate] closed={len(closed)} skipped={len(skipped)} total_pnl=${total_pnl:+.2f}")
    if args.dry_run:
        print("[liquidate] DRY-RUN: no changes committed. Re-run without --dry-run to apply.")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
