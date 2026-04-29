"""Generate daily report PDF + a short text summary for Telegram."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from lib.db import get_connection, get_daily_stats, get_open_trades


def main():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn = get_connection()
    try:
        stats = get_daily_stats(conn, today)
        open_trades = get_open_trades(conn)
    finally:
        conn.close()

    reports_dir = Path(PROJECT_ROOT) / "data" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = reports_dir / f"metrics_daily_{today}.json"
    metrics = {}
    if metrics_path.exists():
        with open(metrics_path) as f:
            metrics = json.load(f)

    total = stats.get("total_trades", 0) or 0
    wins = stats.get("winning", 0) or 0
    losses = stats.get("losing", 0) or 0
    pnl = stats.get("total_pnl", 0.0) or 0.0
    wr = (wins / total * 100) if total else 0
    sharpe = (metrics.get("overall") or {}).get("sharpe", 0)

    summary_lines = [
        f"Trades: {total} ({wins}W / {losses}L)  WR: {wr:.0f}%",
        f"Realized P&L: ${pnl:.2f}  Sharpe: {sharpe:.2f}",
        f"Open positions: {len(open_trades)}",
    ]
    by_strat = (metrics.get("by_strategy") or {})
    if by_strat:
        summary_lines.append("")
        summary_lines.append("By strategy:")
        for sid, m in sorted(by_strat.items(), key=lambda kv: -kv[1].get("total_pnl", 0)):
            summary_lines.append(f"  {sid}: n={m['n']} pnl=${m['total_pnl']:.2f} wr={m['win_rate']*100:.0f}%")
    summary = "\n".join(summary_lines)

    with open(reports_dir / "latest_daily_summary.txt", "w") as f:
        f.write(summary)

    # Optional PDF (falls back to text if reportlab missing)
    try:
        from lib.pdf_generator import generate_daily_pdf  # type: ignore
        pdf_path = reports_dir / f"daily_{today}.pdf"
        generate_daily_pdf(str(pdf_path), today, stats, open_trades, metrics)
        print(f"[daily-report] {pdf_path}")
    except Exception as e:
        print(f"[daily-report] PDF skipped ({e}); text summary only")

    print(summary)


if __name__ == "__main__":
    main()
