"""Generate actionable trade alerts from scored setups. Only alerts for setups scoring >= 60."""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from lib.constants import HIGH_CONFLUENCE_SCORE, get_effective_min_score
from lib.db import get_connection, init_db, log_signal


def generate_alerts(scored_path: str = None, setups_path: str = None) -> list[dict]:
    """Generate actionable alerts from scored confluences + screener setups.

    Merges confluence scores with setup details (entry/SL/TP) to produce
    complete trade alerts ready for risk-check.

    Returns:
        List of alert dicts sorted by priority.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    signals_dir = os.path.join(PROJECT_ROOT, "data", "signals", today)

    # Load scored confluences
    if scored_path is None:
        scored_path = os.path.join(signals_dir, "scored_setups.json")

    with open(scored_path) as f:
        scored_data = json.load(f)
    scored = scored_data.get("scored_setups", [])

    # Load screener setups for entry/SL/TP details
    setups_map = {}
    if setups_path is None:
        setups_path = os.path.join(signals_dir, "setups.json")
    if os.path.exists(setups_path):
        with open(setups_path) as f:
            setups = json.load(f).get("setups", [])
        for s in setups:
            key = (s["symbol"], s["direction"])
            if key not in setups_map or s["confidence"] > setups_map[key]["confidence"]:
                setups_map[key] = s

    alerts = []
    min_score = get_effective_min_score()

    for setup in scored:
        # In paper mode min_score may be lower than the `actionable` flag set
        # at scoring time — fall back to the score directly.
        if setup["score"] < min_score:
            continue

        symbol = setup["symbol"]
        direction = setup["direction"]
        score = setup["score"]

        # Get entry/SL/TP from screener if available
        key = (symbol, direction)
        screener_setup = setups_map.get(key, {})

        alert = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "direction": direction,
            "confluence_score": score,
            "tier": setup["tier"],
            "entry_price": screener_setup.get("entry_price"),
            "stop_loss": screener_setup.get("stop_loss"),
            "take_profit": screener_setup.get("take_profit"),
            "suggested_leverage": _suggest_leverage(score, screener_setup),
            "strategy": screener_setup.get("strategy", "confluence"),
            "rr_ratio": screener_setup.get("rr_ratio"),
            "signal_summary": {
                "unique_types": setup["unique_signal_types"],
                "total_signals": setup["total_signals"],
                "breakdown": setup["breakdown"],
            },
            "conditions_met": screener_setup.get("conditions_met", []),
            "priority": "HIGH" if score >= HIGH_CONFLUENCE_SCORE else "STANDARD",
            "action": "SEND_TO_RISK_CHECK",
        }

        alerts.append(alert)

    # Sort by score
    alerts.sort(key=lambda a: a["confluence_score"], reverse=True)

    # Log signals to DB
    _log_alerts_to_db(alerts)

    return alerts


def _suggest_leverage(score: float, setup: dict) -> int:
    """Suggest leverage based on confluence score."""
    if score >= HIGH_CONFLUENCE_SCORE:
        return min(setup.get("leverage", 5), 10)
    elif score >= 70:
        return min(setup.get("leverage", 3), 5)
    else:
        return 3


def _log_alerts_to_db(alerts: list[dict]):
    """Log each alert as a signal in the database."""
    try:
        init_db()
        conn = get_connection()
        for alert in alerts:
            log_signal(
                conn,
                signal_type="confluence_alert",
                asset=alert["symbol"],
                direction=alert["direction"],
                strength=alert["confluence_score"],
                source="confluence_engine",
                details_json=json.dumps({
                    "score": alert["confluence_score"],
                    "tier": alert["tier"],
                    "entry": alert.get("entry_price"),
                    "sl": alert.get("stop_loss"),
                    "tp": alert.get("take_profit"),
                }, default=str),
            )
        conn.close()
    except Exception as e:
        print(f"Warning: DB logging failed: {e}")


def save_alerts(alerts: list[dict], output_dir: str = None) -> str:
    """Save alerts to file."""
    if output_dir is None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        output_dir = os.path.join(PROJECT_ROOT, "data", "signals", today)

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    filepath = os.path.join(output_dir, "alerts.json")

    with open(filepath, "w") as f:
        json.dump({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "alerts": alerts,
            "count": len(alerts),
        }, f, indent=2, default=str)

    return filepath


def main():
    parser = argparse.ArgumentParser(description="Generate trade alerts from scored setups")
    parser.add_argument("--scored", help="Path to scored_setups.json")
    parser.add_argument("--setups", help="Path to setups.json")
    parser.add_argument("--no-save", action="store_true")
    args = parser.parse_args()

    alerts = generate_alerts(args.scored, args.setups)

    if not args.no_save:
        path = save_alerts(alerts)
        print(f"Saved to: {path}")

    print(f"\n{len(alerts)} actionable alerts:")
    for a in alerts:
        print(f"  [{a['priority']}] {a['symbol']} {a['direction'].upper()} "
              f"score={a['confluence_score']:.0f} "
              f"entry={a.get('entry_price', '?')} sl={a.get('stop_loss', '?')} tp={a.get('take_profit', '?')} "
              f"lev={a['suggested_leverage']}x")
        print(f"         -> {a['action']}")


if __name__ == "__main__":
    main()
