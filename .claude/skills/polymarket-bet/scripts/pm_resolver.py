"""Resolve open Polymarket paper bets against the Gamma API.

For each open trade in pillar='polymarket':
  1. Look up the market via polymarket_bets.market_id → gamma /markets/{id}
  2. If resolved=true (closed=true, resolution in outcomePrices):
     - Determine win/loss from direction + winning outcome
     - Compute P&L: win → stake * (1/entry_price - 1), loss → -stake
     - Call close_trade(), credit_paper_balance(), register_trade_close(),
       refresh_strategy_performance()
     - Send Telegram alert
  3. Write a summary to stdout.

Runs once per daily_report cycle. Safe to re-run — close_trade is idempotent
because the trade status flips to 'closed' on first resolution and the WHERE
clause requires status='open'.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import pm_api

ROOT = pm_api.project_root()
sys.path.insert(0, str(ROOT))

from lib.db import get_connection, close_trade
from lib.paper_engine import credit_paper_balance
from lib.category_cooldown import register_trade_close
from lib.strategy_tuner import refresh_strategy_performance
from lib import notifier


def _get_open_polymarket_trades(conn) -> list[dict]:
    """Return open trades joined to polymarket_bets for market_id."""
    rows = conn.execute(
        """
        SELECT t.id        AS trade_id,
               t.asset     AS market_question,
               t.direction,
               t.entry_price,
               t.quantity,
               t.strategy,
               t.confluence_score,
               pb.market_id,
               pb.market_category
        FROM   trades t
        JOIN   polymarket_bets pb ON pb.trade_id = t.id
        WHERE  t.status = 'open'
          AND  t.pillar = 'polymarket'
        ORDER  BY t.id
        """
    ).fetchall()
    return [dict(r) for r in rows]


def _resolve_outcome(market: dict, direction: str) -> tuple[bool | None, str]:
    """Return (won, reason) by inspecting Gamma market fields.

    Gamma marks a resolved binary market with:
      - closed=true
      - resolution (str): 'Yes' | 'No'  (or sometimes '1' / '0')
      - outcomePrices (list of str floats) — [yes_price, no_price] where the
        winner settles at '1.0' and loser at '0.0'.

    Returns (None, reason) if the market is still open or the resolution
    format is unrecognised.
    """
    if not market.get("closed"):
        return None, "market still open"

    resolution = (market.get("resolution") or "").strip().lower()
    if resolution in ("yes", "1", "1.0"):
        resolved_yes = True
    elif resolution in ("no", "0", "0.0"):
        resolved_yes = False
    else:
        # Fallback: read outcomePrices (YES index=0, NO index=1)
        prices = market.get("outcomePrices") or []
        try:
            if len(prices) >= 2:
                yes_price = float(prices[0])
                resolved_yes = yes_price > 0.5
            else:
                return None, f"unrecognised resolution format: {market.get('resolution')!r} outcomePrices={prices}"
        except (TypeError, ValueError):
            return None, f"outcomePrices parse error: {prices}"

    if direction == "yes":
        won = resolved_yes
    elif direction == "no":
        won = not resolved_yes
    else:
        return None, f"unknown direction {direction!r}"

    outcome_str = "YES" if resolved_yes else "NO"
    return won, f"market resolved {outcome_str}, bet was {direction.upper()}"


def resolve_open_bets() -> dict:
    """Main entry point. Returns summary stats."""
    conn = get_connection()
    try:
        bets = _get_open_polymarket_trades(conn)
    finally:
        conn.close()

    if not bets:
        print("[pm_resolver] no open PM trades — nothing to resolve")
        return {"checked": 0, "resolved": 0, "skipped": 0}

    resolved = 0
    skipped = 0

    for bet in bets:
        trade_id = bet["trade_id"]
        market_id = bet.get("market_id")
        if not market_id:
            print(f"[pm_resolver] trade {trade_id}: missing market_id — skip")
            skipped += 1
            continue

        market = pm_api.get_market_by_id(str(market_id))
        if not market:
            print(f"[pm_resolver] trade {trade_id}: could not fetch market {market_id} — skip")
            skipped += 1
            continue

        won, reason = _resolve_outcome(market, bet["direction"])
        if won is None:
            print(f"[pm_resolver] trade {trade_id} ({bet['market_question'][:60]}): {reason}")
            skipped += 1
            continue

        # P&L calculation:
        #   stake_usd  = quantity (number of shares bought at entry_price)
        #   win:  profit = stake_usd * (1/entry_price - 1)
        #   loss: profit = -stake_usd
        entry_price = float(bet["entry_price"])
        stake_usd = float(bet["quantity"])
        if won:
            pnl_usd = stake_usd * ((1.0 / entry_price) - 1.0)
            exit_price = 1.0
        else:
            pnl_usd = -stake_usd
            exit_price = 0.0

        pnl_pct = (pnl_usd / stake_usd) * 100 if stake_usd > 0 else 0.0

        conn = get_connection()
        try:
            close_trade(conn, trade_id, exit_price=exit_price, pnl_usd=round(pnl_usd, 4),
                        pnl_pct=round(pnl_pct, 2))
            # Update polymarket_bets resolution field
            conn.execute(
                "UPDATE polymarket_bets SET resolution=?, resolved_at=? WHERE trade_id=?",
                ("YES" if exit_price == 1.0 else "NO",
                 datetime.now(timezone.utc).isoformat(),
                 trade_id),
            )
            conn.commit()
        finally:
            conn.close()

        # Credit paper balance
        credit_paper_balance(
            pnl_usd,
            reason=f"PM resolved {'WIN' if won else 'LOSS'} trade={trade_id} {bet['market_question'][:50]}"
        )

        # Category cooldown
        conn = get_connection()
        try:
            register_trade_close(conn, category="POLYMARKET_BINARY", won=won)
        finally:
            conn.close()

        # Strategy performance
        strategy = bet.get("strategy") or "polymarket-smart-money"
        conn = get_connection()
        try:
            refresh_strategy_performance(conn, strategy)
        finally:
            conn.close()

        # Telegram notification
        emoji = "✅" if won else "❌"
        notifier.send_telegram(
            f"{emoji} <b>PM Resolved</b>\n"
            f"Market: {bet['market_question'][:80]}\n"
            f"Bet: {bet['direction'].upper()} @ {entry_price:.3f}\n"
            f"Outcome: {'WIN' if won else 'LOSS'}\n"
            f"P&L: ${pnl_usd:+.2f} ({pnl_pct:+.1f}%)\n"
            f"Stake: ${stake_usd:.2f}"
        )

        print(
            f"[pm_resolver] trade {trade_id}: {'WIN' if won else 'LOSS'} "
            f"pnl=${pnl_usd:+.2f} — {reason}"
        )
        resolved += 1

    summary = {"checked": len(bets), "resolved": resolved, "skipped": skipped}
    print(f"[pm_resolver] done — {summary}")
    return summary


if __name__ == "__main__":
    resolve_open_bets()
