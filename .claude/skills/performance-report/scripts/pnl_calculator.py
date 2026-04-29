"""Compute realized + unrealized P&L and persist into the daily_pnl table."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from lib.db import get_connection, get_open_trades, get_daily_stats, set_system_state


def main():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn = get_connection()
    try:
        stats = get_daily_stats(conn, today)
        open_trades = get_open_trades(conn, pillar="market")
        unrealized = sum((t.get("pnl_usd") or 0) for t in open_trades)
        realized = stats.get("total_pnl", 0.0) or 0.0
        winning = stats.get("winning", 0) or 0
        losing = stats.get("losing", 0) or 0

        # Upsert today's row
        conn.execute(
            """INSERT INTO daily_pnl (date, realized_pnl, unrealized_pnl, total_trades, winning_trades, losing_trades)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(date) DO UPDATE SET
                 realized_pnl=excluded.realized_pnl,
                 unrealized_pnl=excluded.unrealized_pnl,
                 total_trades=excluded.total_trades,
                 winning_trades=excluded.winning_trades,
                 losing_trades=excluded.losing_trades""",
            (today, realized, unrealized, (winning + losing), winning, losing),
        )
        conn.commit()
        set_system_state(conn, "daily_pnl_usd", f"{realized:.2f}")
        print(f"[pnl] {today} realized=${realized:.2f} unrealized=${unrealized:.2f} trades={winning + losing}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
