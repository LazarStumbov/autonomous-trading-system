"""Check current portfolio exposure against limits."""

import argparse
import json
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from lib.risk_engine import check_portfolio_exposure, load_risk_config
from lib.db import get_connection, init_db, get_open_trades


def get_exposure_report(capital: float = None) -> dict:
    """Get full portfolio exposure report.

    Args:
        capital: Current capital. If None, reads from config.
    """
    config = load_risk_config()
    if capital is None:
        capital = config["capital"]["initial_market_usd"]

    init_db()
    conn = get_connection()
    open_trades = get_open_trades(conn)
    conn.close()

    # Calculate per-position exposure
    positions = []
    total_exposure = 0
    for t in open_trades:
        value = t.get("quantity", 0) * t.get("entry_price", 0) * t.get("leverage", 1)
        total_exposure += value
        positions.append({
            "asset": t["asset"],
            "direction": t["direction"],
            "value_usd": round(value, 2),
            "leverage": t.get("leverage", 1),
            "entry_price": t["entry_price"],
        })

    exposure_pct = (total_exposure / capital * 100) if capital > 0 else 0
    max_allowed = config["market_trading"]["max_portfolio_exposure_pct"]

    return {
        "capital": capital,
        "total_exposure_usd": round(total_exposure, 2),
        "exposure_pct": round(exposure_pct, 2),
        "max_allowed_pct": max_allowed,
        "remaining_capacity_usd": round(capital * max_allowed / 100 - total_exposure, 2),
        "open_positions": len(positions),
        "positions": positions,
        "verdict": "PASS" if exposure_pct <= max_allowed else "FAIL",
    }


def main():
    parser = argparse.ArgumentParser(description="Check portfolio exposure")
    parser.add_argument("--capital", type=float, help="Current capital USD")
    args = parser.parse_args()

    report = get_exposure_report(args.capital)
    print(json.dumps(report, indent=2))

    if report["verdict"] == "FAIL":
        print(f"\nWARNING: Exposure {report['exposure_pct']}% exceeds limit {report['max_allowed_pct']}%")
    else:
        print(f"\nExposure OK: {report['exposure_pct']}% / {report['max_allowed_pct']}% "
              f"(${report['remaining_capacity_usd']:.2f} remaining)")


if __name__ == "__main__":
    main()
