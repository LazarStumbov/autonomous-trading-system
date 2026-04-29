"""Snapshot today's trades into data/signals/<date>/trade_journal.json.

Pulls from the trades table and writes a human-readable JSON blob the daily
report consumes. Adds per-trade reasoning summary if available.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from lib.db import get_connection, get_today_trades


def main():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir = Path(PROJECT_ROOT) / "data" / "signals" / today
    out_dir.mkdir(parents=True, exist_ok=True)

    conn = get_connection()
    try:
        trades = get_today_trades(conn)
    finally:
        conn.close()

    payload = {
        "date": today,
        "count": len(trades),
        "trades": trades,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    out = out_dir / "trade_journal.json"
    with open(out, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    print(f"[trade_journal] wrote {len(trades)} trades to {out}")


if __name__ == "__main__":
    main()
