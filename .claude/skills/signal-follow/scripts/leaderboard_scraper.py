"""Pull the Bybit copy-trade leaderboard and cache trader stats.

Writes data/signals/<date>/leaderboard.json with top N traders + their 30d metrics.
Graceful fallback: if the endpoint fails, keeps the previous snapshot.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))

try:
    import requests  # type: ignore
except ImportError:
    requests = None


BYBIT_LEADERBOARD_URL = "https://api2.bybit.com/fapi/beta/public/copytrade/trader/leader-board"


def fetch_leaderboard(limit: int = 50) -> list[dict]:
    if requests is None:
        return []
    try:
        r = requests.get(BYBIT_LEADERBOARD_URL, params={"page": 1, "pageSize": limit, "sortType": "ROI"}, timeout=15)
        r.raise_for_status()
        body = r.json().get("result", {}).get("list", [])
        return [
            {
                "account_id": x.get("leaderMark") or x.get("uid"),
                "alias": x.get("nickName"),
                "roi_30d_pct": x.get("pnlRate30d") or x.get("roi"),
                "pnl_30d_usd": x.get("pnl30d"),
                "win_rate": x.get("winRate"),
                "followers": x.get("followers"),
                "total_trades": x.get("totalTrades"),
            }
            for x in body
        ]
    except Exception as e:
        print(f"[leaderboard] fetch failed: {e}")
        return []


def main():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir = Path(PROJECT_ROOT) / "data" / "signals" / today
    out_dir.mkdir(parents=True, exist_ok=True)

    traders = fetch_leaderboard(50)
    out = out_dir / "leaderboard.json"
    if not traders and out.exists():
        print("[leaderboard] keeping previous snapshot")
        return
    with open(out, "w") as f:
        json.dump({"generated_at": datetime.now(timezone.utc).isoformat(), "traders": traders}, f, indent=2)
    print(f"[leaderboard] wrote {len(traders)} traders to {out}")


if __name__ == "__main__":
    main()
