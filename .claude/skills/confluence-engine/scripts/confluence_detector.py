"""Confluence detector. Groups signals by asset and direction, counts independent signal sources."""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from lib.constants import SignalType
from lib.db import get_connection, init_db


def load_signals_from_files(signals_dir: str = None) -> list[dict]:
    """Load all signals from today's signal files."""
    if signals_dir is None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        signals_dir = os.path.join(PROJECT_ROOT, "data", "signals", today)

    all_signals = []

    # Load from technicals
    technicals_path = os.path.join(signals_dir, "technicals.json")
    if os.path.exists(technicals_path):
        with open(technicals_path) as f:
            data = json.load(f).get("analysis", {})
        for symbol, analysis in data.items():
            for sig in analysis.get("signals", []):
                all_signals.append({
                    "symbol": symbol,
                    "type": _classify_signal_type(sig.get("type", "")),
                    "direction": "long" if sig.get("bias") == "bullish" else "short" if sig.get("bias") == "bearish" else None,
                    "strength": 1.0,
                    "source": "technical_analysis",
                    "timeframe": sig.get("timeframe", ""),
                    "detail": sig,
                })

    # Load from setups (screener output)
    setups_path = os.path.join(signals_dir, "setups.json")
    if os.path.exists(setups_path):
        with open(setups_path) as f:
            setups = json.load(f).get("setups", [])
        for setup in setups:
            all_signals.append({
                "symbol": setup["symbol"],
                "type": SignalType.TECHNICAL_BREAKOUT,
                "direction": setup["direction"],
                "strength": setup.get("confidence", 50) / 100,
                "source": f"screener_{setup['strategy']}",
                "timeframe": setup.get("timeframe", ""),
                "detail": setup,
            })

    # Load from news signals (if exists)
    news_path = os.path.join(signals_dir, "news_signals.json")
    if os.path.exists(news_path):
        with open(news_path) as f:
            news = json.load(f)
        for sig in news if isinstance(news, list) else news.get("signals", []):
            all_signals.append({
                "symbol": sig.get("symbol", ""),
                "type": SignalType.NEWS_CATALYST,
                "direction": sig.get("direction"),
                "strength": sig.get("urgency", 0.5),
                "source": "news_monitor",
                "detail": sig,
            })

    # Load from trader signals (if exists)
    trader_path = os.path.join(signals_dir, "trader_signals.json")
    if os.path.exists(trader_path):
        with open(trader_path) as f:
            traders = json.load(f)
        for sig in traders if isinstance(traders, list) else traders.get("signals", []):
            all_signals.append({
                "symbol": sig.get("symbol", ""),
                "type": SignalType.TRADER_ACCUMULATION,
                "direction": sig.get("direction"),
                "strength": sig.get("skill_score", 0.5),
                "source": "signal_follow",
                "detail": sig,
            })

    return all_signals


def _classify_signal_type(signal_name: str) -> str:
    """Map specific signal names to broad SignalType categories."""
    name = signal_name.lower()
    if any(k in name for k in ["breakout", "ema", "macd", "rsi", "bb"]):
        return SignalType.TECHNICAL_BREAKOUT
    if "volume" in name:
        return SignalType.VOLUME_ANOMALY
    if "sentiment" in name:
        return SignalType.SENTIMENT_SHIFT
    return SignalType.TECHNICAL_BREAKOUT


def detect_confluence(signals: list[dict]) -> list[dict]:
    """Group signals by symbol+direction and detect confluence.

    Returns:
        List of confluence groups, each with symbol, direction, signal count, and signal details.
    """
    # Group by (symbol, direction)
    groups = defaultdict(list)
    for sig in signals:
        if sig["direction"] is None:
            continue
        key = (sig["symbol"], sig["direction"])
        groups[key].append(sig)

    confluences = []
    for (symbol, direction), group_signals in groups.items():
        # Count unique signal types
        unique_types = set()
        for s in group_signals:
            unique_types.add(s["type"])

        confluences.append({
            "symbol": symbol,
            "direction": direction,
            "total_signals": len(group_signals),
            "unique_signal_types": len(unique_types),
            "signal_types": list(unique_types),
            "signals": group_signals,
            "avg_strength": sum(s["strength"] for s in group_signals) / len(group_signals),
        })

    # Sort by unique signal types (more types = stronger confluence)
    confluences.sort(key=lambda c: (c["unique_signal_types"], c["total_signals"]), reverse=True)

    return confluences


def save_confluences(confluences: list[dict], output_dir: str = None) -> str:
    """Save confluence detection results."""
    if output_dir is None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        output_dir = os.path.join(PROJECT_ROOT, "data", "signals", today)

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    filepath = os.path.join(output_dir, "confluences.json")

    # Serialize enums
    serializable = json.loads(json.dumps(confluences, default=str))

    with open(filepath, "w") as f:
        json.dump({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "confluences": serializable,
            "count": len(confluences),
        }, f, indent=2)

    return filepath


def main():
    parser = argparse.ArgumentParser(description="Detect signal confluence")
    parser.add_argument("--signals-dir", help="Directory with signal files")
    parser.add_argument("--no-save", action="store_true")
    args = parser.parse_args()

    signals = load_signals_from_files(args.signals_dir)
    print(f"Loaded {len(signals)} signals")

    confluences = detect_confluence(signals)

    if not args.no_save:
        path = save_confluences(confluences)
        print(f"Saved to: {path}")

    print(f"\n{len(confluences)} confluence groups:")
    for c in confluences:
        print(f"  {c['symbol']} {c['direction'].upper()}: "
              f"{c['unique_signal_types']} types, {c['total_signals']} signals, "
              f"avg strength {c['avg_strength']:.2f}")


if __name__ == "__main__":
    main()
