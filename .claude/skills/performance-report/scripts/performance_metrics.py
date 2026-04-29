"""Compute Sharpe, Sortino, win-rate, max-DD, per-strategy breakdown.

Writes results to data/reports/metrics_<period>_<date>.json.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from lib.db import get_connection


def compute(pnls: list[float]) -> dict:
    if not pnls:
        return {"n": 0, "mean": 0, "std": 0, "sharpe": 0, "sortino": 0, "max_dd_pct": 0, "win_rate": 0}
    n = len(pnls)
    wins = sum(1 for p in pnls if p > 0)
    mean = sum(pnls) / n
    var = sum((p - mean) ** 2 for p in pnls) / n
    std = math.sqrt(var) if var > 0 else 1e-9
    downside = [p for p in pnls if p < 0]
    dvar = sum((p - 0) ** 2 for p in downside) / len(downside) if downside else 0.0
    dstd = math.sqrt(dvar) if dvar > 0 else 1e-9
    annual = math.sqrt(252)
    # Equity-curve max DD from cumulative pnl
    equity = [0.0]
    for p in pnls:
        equity.append(equity[-1] + p)
    peak = equity[0]
    max_dd = 0.0
    for e in equity:
        if e > peak:
            peak = e
        if peak > 0:
            dd = (peak - e) / peak
            if dd > max_dd:
                max_dd = dd
    return {
        "n": n,
        "win_rate": wins / n,
        "mean": mean,
        "std": std,
        "sharpe": (mean / std) * annual if std > 0 else 0,
        "sortino": (mean / dstd) * annual if dstd > 0 else 0,
        "max_dd_pct": max_dd * 100,
        "total_pnl": sum(pnls),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--period", choices=["daily", "weekly"], default="daily")
    args = parser.parse_args()

    today = datetime.now(timezone.utc)
    days = 1 if args.period == "daily" else 7
    cutoff = (today - timedelta(days=days)).isoformat()

    conn = get_connection()
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM trades WHERE status='closed' AND closed_at >= ?", (cutoff,)
        ).fetchall()]
    finally:
        conn.close()

    overall = compute([r.get("pnl_usd") or 0.0 for r in rows])

    # Per-strategy breakdown
    by_strat: dict[str, list[float]] = {}
    for r in rows:
        sid = r.get("strategy") or "unknown"
        by_strat.setdefault(sid, []).append(r.get("pnl_usd") or 0.0)
    strategies = {sid: compute(v) for sid, v in by_strat.items()}

    out_dir = Path(PROJECT_ROOT) / "data" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"metrics_{args.period}_{today.strftime('%Y-%m-%d')}.json"
    payload = {
        "period": args.period,
        "generated_at": today.isoformat(),
        "window_days": days,
        "overall": overall,
        "by_strategy": strategies,
    }
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"[metrics] wrote {out_path} | trades={overall['n']} sharpe={overall['sharpe']:.2f} pnl=${overall['total_pnl']:.2f}")


if __name__ == "__main__":
    main()
