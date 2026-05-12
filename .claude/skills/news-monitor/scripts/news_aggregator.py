"""Aggregate crypto/market news from MarketAux + Finnhub into data/signals/<date>/news.json.

Graceful degradation: if API keys aren't set, writes an empty list but does not raise.
The confluence engine tolerates either an empty file or a missing file.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    import requests  # type: ignore
except ImportError:
    requests = None


def _marketaux(api_key: str) -> list[dict]:
    if not api_key or requests is None:
        return []
    url = "https://api.marketaux.com/v1/news/all"
    params = {"symbols": "BTC,ETH", "filter_entities": "true", "limit": 25, "language": "en", "api_token": api_key}
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        return [
            {
                "source": "marketaux",
                "title": x.get("title"),
                "url": x.get("url"),
                "published_at": x.get("published_at"),
                "summary": x.get("description") or "",
                "entities": [e.get("symbol") for e in x.get("entities", []) if e.get("symbol")],
            }
            for x in r.json().get("data", [])
        ]
    except Exception as e:
        print(f"[news] marketaux failed: {e}")
        return []


def _coindesk_rss() -> list[dict]:
    """Free RSS fallback. No key required. Runs in paper mode so the news
    pillar produces a non-empty news.json even with no MarketAux/Finnhub keys.

    CoinDesk RSS has been the most reliable free crypto feed for ~10 years;
    if it ever changes shape, fall back silently rather than crashing the
    cron job.
    """
    if requests is None:
        return []
    url = "https://www.coindesk.com/arc/outboundfeeds/rss/"
    try:
        r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0 trading-bot"})
        r.raise_for_status()
        # Minimal RSS parser — avoids adding feedparser as a hard dep.
        import re
        text = r.text
        items = []
        for m in re.finditer(r"<item>(.*?)</item>", text, flags=re.DOTALL):
            block = m.group(1)
            title = (re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", block, flags=re.DOTALL) or [None, ""])[1].strip()
            link  = (re.search(r"<link>(.*?)</link>", block, flags=re.DOTALL) or [None, ""])[1].strip()
            desc  = (re.search(r"<description>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</description>", block, flags=re.DOTALL) or [None, ""])[1].strip()
            pub   = (re.search(r"<pubDate>(.*?)</pubDate>", block, flags=re.DOTALL) or [None, ""])[1].strip()
            try:
                from email.utils import parsedate_to_datetime
                pub_iso = parsedate_to_datetime(pub).astimezone(timezone.utc).isoformat() if pub else None
            except Exception:
                pub_iso = None
            if title:
                items.append({
                    "source": "coindesk_rss",
                    "title": title,
                    "url": link,
                    "published_at": pub_iso,
                    "summary": re.sub(r"<[^>]+>", "", desc)[:500],
                    "entities": [],
                    "categories": ["economic"],  # baseline category so urgency picks up
                })
        return items[:25]
    except Exception as e:
        print(f"[news] coindesk_rss failed: {e}")
        return []


def _finnhub(api_key: str) -> list[dict]:
    if not api_key or requests is None:
        return []
    url = "https://finnhub.io/api/v1/news"
    try:
        r = requests.get(url, params={"category": "crypto", "token": api_key}, timeout=10)
        r.raise_for_status()
        return [
            {
                "source": "finnhub",
                "title": x.get("headline"),
                "url": x.get("url"),
                "published_at": datetime.fromtimestamp(x.get("datetime", 0), tz=timezone.utc).isoformat() if x.get("datetime") else None,
                "summary": x.get("summary") or "",
                "entities": [x.get("related")] if x.get("related") else [],
            }
            for x in (r.json() or [])[:25]
        ]
    except Exception as e:
        print(f"[news] finnhub failed: {e}")
        return []


def main():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir = Path(PROJECT_ROOT) / "data" / "signals" / today
    out_dir.mkdir(parents=True, exist_ok=True)

    items = _marketaux(os.getenv("MARKETAUX_API_KEY", "")) + _finnhub(os.getenv("FINNHUB_API_KEY", ""))
    # Free no-key fallback so news_signals.json is never empty in paper mode.
    # Always merged (additive, not exclusive) — paid sources still take priority.
    items += _coindesk_rss()
    # Dedupe by title
    seen = set()
    deduped = []
    for it in items:
        k = (it.get("title") or "").lower().strip()
        if k and k not in seen:
            seen.add(k)
            deduped.append(it)

    out = out_dir / "news.json"
    with open(out, "w") as f:
        json.dump({"generated_at": datetime.now(timezone.utc).isoformat(), "count": len(deduped), "items": deduped}, f, indent=2)
    print(f"[news_aggregator] wrote {len(deduped)} items to {out}")


if __name__ == "__main__":
    main()
