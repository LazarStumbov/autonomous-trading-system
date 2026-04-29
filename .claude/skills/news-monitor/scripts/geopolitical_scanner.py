"""Tag news items with geopolitical/regulatory/economic categories via keyword matching.

Augments news.json in place with a "categories" field per item. Cheap first-pass
that feeds the sentiment scorer and urgency classifier without LLM calls.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))

CATEGORY_KEYWORDS = {
    "geopolitical": ["war", "sanction", "ceasefire", "invasion", "embargo", "tariff", "taiwan", "ukraine", "russia", "iran", "israel", "nato"],
    "regulatory":   ["sec", "cftc", "regulation", "ban", "approval", "etf", "lawsuit", "ruling", "legislation", "bill"],
    "economic":     ["fed", "fomc", "rate hike", "rate cut", "cpi", "inflation", "gdp", "unemployment", "nfp", "pce"],
    "crypto_spec":  ["halving", "hardfork", "upgrade", "hack", "exploit", "depeg", "liquidation", "whale"],
    "corporate":    ["earnings", "acquisition", "merger", "ipo", "bankrupt", "default"],
}


def categorize(text: str) -> list[str]:
    t = (text or "").lower()
    return [cat for cat, keywords in CATEGORY_KEYWORDS.items() if any(kw in t for kw in keywords)]


def main():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = Path(PROJECT_ROOT) / "data" / "signals" / today / "news.json"
    if not path.exists():
        print(f"[geopolitical] no news.json yet at {path}")
        return
    with open(path) as f:
        payload = json.load(f)

    tagged = 0
    for item in payload.get("items", []):
        cats = categorize(f"{item.get('title','')} {item.get('summary','')}")
        if cats:
            item["categories"] = cats
            tagged += 1

    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"[geopolitical] tagged {tagged}/{payload.get('count', 0)} items")


if __name__ == "__main__":
    main()
