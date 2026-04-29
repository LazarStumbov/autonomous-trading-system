"""Compute urgency score (0-10) per news item and emit news_signals.json.

Urgency heuristic:
  +3 if in geopolitical/regulatory/economic categories
  +2 if strong sentiment (|s| > 0.6)
  +2 if freshness < 30 min
  +1 per crypto symbol mentioned (BTC/ETH/etc.)
  +1 if contains "breaking", "just in", "alert"

Writes news_signals.json — this is what confluence_detector.py reads (see its line 60).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))

HIGH_PRIORITY_CATS = {"geopolitical", "regulatory", "economic"}
URGENCY_KEYWORDS = {"breaking", "just in", "alert", "urgent", "emergency"}
CRYPTO_SYMBOLS = {"BTC", "ETH", "SOL", "XRP", "BNB", "ADA", "AVAX", "DOGE"}


def urgency_for(item: dict) -> int:
    score = 0
    cats = set(item.get("categories", []))
    if cats & HIGH_PRIORITY_CATS:
        score += 3
    if abs(item.get("sentiment", 0.0)) > 0.6:
        score += 2
    # freshness
    pub = item.get("published_at")
    if pub:
        try:
            pub_dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
            mins = (datetime.now(timezone.utc) - pub_dt).total_seconds() / 60
            if mins < 30:
                score += 2
            elif mins < 120:
                score += 1
        except Exception:
            pass
    # symbol mentions
    text = f"{item.get('title','')} {item.get('summary','')}".upper()
    score += min(2, sum(1 for s in CRYPTO_SYMBOLS if s in text))
    # shouty keywords
    lower = text.lower()
    if any(k in lower for k in URGENCY_KEYWORDS):
        score += 1
    return min(10, score)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--emit-setups", action="store_true")
    args = parser.parse_args()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d = Path(PROJECT_ROOT) / "data" / "signals" / today
    news_path = d / "news.json"
    if not news_path.exists():
        print(f"[urgency] no news.json")
        return

    with open(news_path) as f:
        news = json.load(f)

    signals: list[dict] = []
    max_urgency = 0
    for item in news.get("items", []):
        u = urgency_for(item)
        max_urgency = max(max_urgency, u)
        if u >= 6:
            # emit one signal per asset mention
            text = f"{item.get('title','')} {item.get('summary','')}".upper()
            for sym in CRYPTO_SYMBOLS:
                if sym in text:
                    direction = "long" if item.get("sentiment", 0) > 0 else "short"
                    signals.append({
                        "asset": sym,
                        "direction": direction,
                        "urgency": u,
                        "sentiment": item.get("sentiment", 0),
                        "title": item.get("title"),
                        "url": item.get("url"),
                        "categories": item.get("categories", []),
                        "source": "news_urgency",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })

    out = d / "news_signals.json"
    with open(out, "w") as f:
        json.dump({"generated_at": datetime.now(timezone.utc).isoformat(), "signals": signals, "max_urgency": max_urgency}, f, indent=2)

    urgent_flag = "true" if max_urgency >= 8 else "false"
    if args.emit_setups:
        # Explicit stdout marker consumed by Modal news_scan to trigger hot path
        print(f"urgent={urgent_flag} max_urgency={max_urgency} signals={len(signals)}")
    print(f"[urgency] {len(signals)} news signals, max_urgency={max_urgency}")


if __name__ == "__main__":
    main()
