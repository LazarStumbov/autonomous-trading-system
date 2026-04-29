"""Score sentiment (-1..+1) per news item. Keyword heuristic by default; LLM optional.

Upgrades news.json with "sentiment" field. Works offline without API keys.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))

BULLISH = {"surge", "rally", "gain", "beat", "record", "approval", "breakout", "adopt", "bullish", "upgrade", "partnership", "buy", "accumulate", "launch"}
BEARISH = {"crash", "plunge", "fall", "drop", "miss", "reject", "hack", "exploit", "bearish", "downgrade", "lawsuit", "sell", "liquidation", "fear", "fud", "halt"}


def score_item(text: str) -> float:
    t = (text or "").lower()
    bull = sum(1 for w in BULLISH if w in t)
    bear = sum(1 for w in BEARISH if w in t)
    if bull == 0 and bear == 0:
        return 0.0
    return (bull - bear) / (bull + bear)


def main():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = Path(PROJECT_ROOT) / "data" / "signals" / today / "news.json"
    if not path.exists():
        print(f"[sentiment] no news.json at {path}")
        return
    with open(path) as f:
        payload = json.load(f)
    for item in payload.get("items", []):
        item["sentiment"] = score_item(f"{item.get('title','')} {item.get('summary','')}")
    payload["avg_sentiment"] = (
        sum(i.get("sentiment", 0) for i in payload.get("items", [])) / max(1, len(payload.get("items", [])))
    )
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"[sentiment] scored {payload.get('count',0)} items, avg={payload['avg_sentiment']:+.2f}")


if __name__ == "__main__":
    main()
