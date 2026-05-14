"""One-shot backfill: tag existing polymarket_bets rows with discovery_method.

Pre-Stage-1 the system labeled every PM bet "polymarket-smart-money" even when
no wallet evidence existed. This script:
  1. Reads every polymarket_bets row whose discovery_method IS NULL.
  2. Inspects the joined trades.reasoning JSON for any wallet/citation evidence.
  3. Writes discovery_method = heuristic_paper for evidence-free bets, and
     re-routes trades.strategy = 'polymarket-heuristic' so post-mortems are honest.
  4. Wallet-evidence rows keep polymarket-smart-money and get tagged wallet_single
     (we can't infer cluster vs single from current reasoning JSON cleanly).

Idempotent: rows that already have discovery_method are untouched.

Usage:
  python3 .claude/skills/polymarket-bet/scripts/backfill_discovery_method.py
  python3 .claude/skills/polymarket-bet/scripts/backfill_discovery_method.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import pm_api  # noqa: E402

ROOT = pm_api.project_root()
sys.path.insert(0, str(ROOT))

from lib import db as dblib  # noqa: E402


def _infer_from_reasoning(reasoning: str | None) -> tuple[str, str]:
    """Return (discovery_method, strategy_for_trade) inferred from trades.reasoning JSON.

    Pre-existing rows store reasoning as JSON {key_factors, citations, fails}.
    Any non-empty citations or wallet mention in key_factors → wallet_single.
    Everything else → heuristic_paper (and strategy is re-routed).
    """
    if not reasoning:
        return "heuristic_paper", "polymarket-heuristic"
    try:
        data = json.loads(reasoning)
    except (json.JSONDecodeError, TypeError):
        return "heuristic_paper", "polymarket-heuristic"
    citations = data.get("citations") or []
    factors = data.get("key_factors") or []
    if citations:
        return "news_driven_researched", "polymarket-smart-money"
    blob = " ".join(str(f) for f in factors).lower()
    if any(k in blob for k in ("wallet", "smart-money", "cluster", "sharp")):
        return "wallet_single", "polymarket-smart-money"
    return "heuristic_paper", "polymarket-heuristic"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--smart-infer",
        action="store_true",
        help="Use reasoning-JSON heuristics. Default is --all-heuristic: every "
             "NULL row → heuristic_paper / polymarket-heuristic strategy. "
             "Default reflects that tracked_accounts was empty during these "
             "bets' lifetime, so any 'wallet' mention was system prose, "
             "not real evidence.",
    )
    args = parser.parse_args()

    conn = dblib.get_connection()
    rows = conn.execute(
        """SELECT pb.id          AS pb_id,
                  pb.trade_id    AS trade_id,
                  pb.market_id   AS market_id,
                  t.reasoning    AS reasoning,
                  t.strategy     AS strategy
             FROM polymarket_bets pb
             JOIN trades t ON t.id = pb.trade_id
            WHERE pb.discovery_method IS NULL
            ORDER BY pb.id"""
    ).fetchall()

    if not rows:
        print("[backfill] no NULL discovery_method rows — done")
        conn.close()
        return 0

    print(f"[backfill] {len(rows)} rows to tag (dry_run={args.dry_run}, smart_infer={args.smart_infer})")
    counts = {"heuristic_paper": 0, "wallet_single": 0, "news_driven_researched": 0}
    for r in rows:
        if args.smart_infer:
            method, strategy = _infer_from_reasoning(r["reasoning"])
        else:
            method, strategy = "heuristic_paper", "polymarket-heuristic"
        counts[method] = counts.get(method, 0) + 1
        print(f"  bet#{r['pb_id']} trade#{r['trade_id']} → {method} / strategy={strategy}")
        if not args.dry_run:
            conn.execute(
                "UPDATE polymarket_bets SET discovery_method=? WHERE id=?",
                (method, r["pb_id"]),
            )
            # Only re-route strategy when the inference downgrades a row.
            # Don't overwrite if the user has manually annotated it.
            if r["strategy"] in (None, "polymarket-smart-money") and strategy != r["strategy"]:
                conn.execute(
                    "UPDATE trades SET strategy=? WHERE id=?",
                    (strategy, r["trade_id"]),
                )
    if not args.dry_run:
        conn.commit()
    conn.close()

    print(f"[backfill] tag counts: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
