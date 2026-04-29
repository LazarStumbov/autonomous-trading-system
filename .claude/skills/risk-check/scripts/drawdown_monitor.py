"""Monitor daily and weekly drawdown against circuit breaker limits."""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from lib.risk_engine import check_drawdown, check_circuit_breakers, load_risk_config
from lib.db import get_connection, init_db, get_daily_stats, get_system_state


def get_drawdown_report(capital: float = None) -> dict:
    """Generate comprehensive drawdown report.

    Args:
        capital: Current capital. If None, reads from config.
    """
    config = load_risk_config()
    if capital is None:
        capital = config["capital"]["initial_market_usd"]

    breakers_config = config["market_trading"]["circuit_breakers"]

    # Check drawdown
    drawdown = check_drawdown(capital)

    # Check circuit breakers
    circuit = check_circuit_breakers()

    # Get today's stats
    init_db()
    conn = get_connection()
    daily_stats = get_daily_stats(conn)
    consecutive_losses = int(get_system_state(conn, "consecutive_losses") or "0")
    conn.close()

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "capital": capital,
        "drawdown": {
            "daily_pnl_usd": drawdown["daily_pnl_usd"],
            "weekly_pnl_usd": drawdown["weekly_pnl_usd"],
            "daily_drawdown_pct": drawdown["daily_drawdown_pct"],
            "weekly_drawdown_pct": drawdown["weekly_drawdown_pct"],
            "daily_limit_pct": breakers_config["daily_loss_halt_pct"],
            "weekly_limit_pct": breakers_config["weekly_loss_halt_pct"],
            "daily_remaining_pct": round(breakers_config["daily_loss_halt_pct"] - drawdown["daily_drawdown_pct"], 2),
            "weekly_remaining_pct": round(breakers_config["weekly_loss_halt_pct"] - drawdown["weekly_drawdown_pct"], 2),
        },
        "circuit_breakers": {
            "trading_halted": circuit["halted"],
            "consecutive_losses": consecutive_losses,
            "max_consecutive_losses": breakers_config["halt_after_consecutive_losses"],
            "halt_duration_hours": breakers_config["halt_duration_hours"],
        },
        "today": {
            "total_trades": daily_stats.get("total_trades", 0),
            "winning": daily_stats.get("winning", 0),
            "losing": daily_stats.get("losing", 0),
            "total_pnl": daily_stats.get("total_pnl", 0),
            "best_trade": daily_stats.get("best_trade", 0),
            "worst_trade": daily_stats.get("worst_trade", 0),
        },
        "verdict": drawdown["verdict"],
        "reason": drawdown["reason"],
        "can_trade": drawdown["verdict"] == "PASS" and not circuit["halted"],
    }


def main():
    parser = argparse.ArgumentParser(description="Monitor drawdown and circuit breakers")
    parser.add_argument("--capital", type=float, help="Current capital USD")
    args = parser.parse_args()

    report = get_drawdown_report(args.capital)
    print(json.dumps(report, indent=2, default=str))

    if not report["can_trade"]:
        print(f"\nTRADING HALTED: {report['reason']}")
    else:
        dd = report["drawdown"]
        print(f"\nDrawdown OK — Daily: {dd['daily_drawdown_pct']}%/{dd['daily_limit_pct']}% | "
              f"Weekly: {dd['weekly_drawdown_pct']}%/{dd['weekly_limit_pct']}%")


if __name__ == "__main__":
    main()
