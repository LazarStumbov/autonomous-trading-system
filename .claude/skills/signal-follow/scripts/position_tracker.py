"""Track current positions of followed traders and emit trader_signals.json.

confluence_detector.py reads this file (see line 74) to cross-check live setups
against what skilled traders are doing right now.

Offline-safe: if Bybit position API fails, writes an empty signal list.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))


def load_followed() -> list[dict]:
    path = Path(PROJECT_ROOT) / "config" / "trader_accounts.json"
    if not path.exists():
        return []
    try:
        with open(path) as f:
            cfg = json.load(f)
        return cfg.get("traders", cfg if isinstance(cfg, list) else [])
    except Exception:
        return []


def fetch_positions_for_trader(trader_id: str) -> list[dict]:
    """Bybit's public copy-trade position endpoint. Best-effort; returns [] on failure."""
    try:
        import requests  # type: ignore
        r = requests.get(
            "https://api2.bybit.com/fapi/beta/public/copytrade/trader/current/position",
            params={"leaderMark": trader_id},
            timeout=10,
        )
        r.raise_for_status()
        body = r.json().get("result", {}).get("list", []) or []
        return [
            {
                "symbol": p.get("symbol"),
                "side": "long" if p.get("side", "").lower() == "buy" else "short",
                "size": p.get("size"),
                "entry_price": p.get("entryPrice"),
                "leverage": p.get("leverage"),
                "unrealized_pnl": p.get("unrealisedPnl"),
            }
            for p in body
        ]
    except Exception:
        return []


def main():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir = Path(PROJECT_ROOT) / "data" / "signals" / today
    out_dir.mkdir(parents=True, exist_ok=True)

    traders = load_followed()
    signals: list[dict] = []
    for t in traders[:20]:  # cap to avoid rate limits
        tid = t.get("account_id") or t.get("id")
        if not tid:
            continue
        positions = fetch_positions_for_trader(tid)
        for p in positions:
            signals.append({
                "trader_id": tid,
                "alias": t.get("alias"),
                "skill_score": t.get("skill_score", 0),
                "asset": p["symbol"],
                "direction": p["side"],
                "entry_price": p.get("entry_price"),
                "size": p.get("size"),
                "leverage": p.get("leverage"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

    out = out_dir / "trader_signals.json"
    with open(out, "w") as f:
        json.dump({"generated_at": datetime.now(timezone.utc).isoformat(), "signals": signals}, f, indent=2)
    print(f"[position_tracker] {len(signals)} trader signals across {len(traders)} followed accounts → {out}")


if __name__ == "__main__":
    main()
