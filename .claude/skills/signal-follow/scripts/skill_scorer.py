"""Score followed traders on their signal-generation skill.

For each trader that has recent position data, cross-reference their signals
to downstream trade outcomes in our own trades table. Weight score by win-rate,
30d ROI, Sharpe-like consistency, and followers. Writes scores back into
config/trader_accounts.json.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from lib.db import get_connection


def skill_score(trader: dict, our_wins: int, our_losses: int) -> float:
    roi = float(trader.get("roi_30d_pct") or 0)
    wr = float(trader.get("win_rate") or 0)
    followers = float(trader.get("followers") or 0)
    trades = float(trader.get("total_trades") or 0)
    # Score: weighted combination, bounded to 0..100
    score = (
        min(roi, 300) * 0.25           # cap extreme ROIs
        + wr * 100 * 0.30
        + min(followers, 5000) / 50   # up to 100
        + min(trades, 500) / 5        # up to 100
    )
    # Downstream confirmation from our own trades
    n = our_wins + our_losses
    if n > 0:
        realized_wr = our_wins / n
        score += (realized_wr - 0.5) * 40  # +/-20 swing
    return max(0, min(100, score))


def main():
    cfg_path = Path(PROJECT_ROOT) / "config" / "trader_accounts.json"
    if not cfg_path.exists():
        print(f"[skill_scorer] no trader_accounts.json; skipping")
        return
    with open(cfg_path) as f:
        cfg = json.load(f)
    traders = cfg.get("traders", cfg if isinstance(cfg, list) else [])

    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    conn = get_connection()
    try:
        # Join with account_performance for downstream signal outcome
        perf_rows = {r["account_id"]: dict(r) for r in conn.execute(
            "SELECT * FROM account_performance WHERE check_timestamp >= ?", (cutoff,)
        ).fetchall()}
    finally:
        conn.close()

    for t in traders:
        tid = t.get("account_id") or t.get("id") or ""
        perf = perf_rows.get(tid, {})
        wins = perf.get("signals_profitable", 0) or 0
        losses = (perf.get("signals_generated", 0) or 0) - wins
        t["skill_score"] = round(skill_score(t, wins, losses), 1)

    # Sort descending
    traders.sort(key=lambda x: -x.get("skill_score", 0))
    cfg["traders"] = traders
    cfg["last_scored_at"] = datetime.now(timezone.utc).isoformat()
    with open(cfg_path, "w") as f:
        json.dump(cfg, f, indent=2)
    print(f"[skill_scorer] rescored {len(traders)} traders; top: {[t.get('alias') for t in traders[:5]]}")


if __name__ == "__main__":
    main()
