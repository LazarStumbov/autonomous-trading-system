"""Layer 1: pull active Polymarket markets and write a daily snapshot.

No LLM, no extra HTTP cost beyond Gamma. Outputs:
  data/signals/<date>/pm_markets.json

Each entry is a normalized dict so downstream scripts don't have to deal with
the messy raw Gamma fields. We dedupe by `id` and drop markets resolving in
< 6h (unless yes_price > 0.95 — those are late-stage convergence candidates).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
import pm_api  # noqa: E402

ROOT = pm_api.project_root()
SIGNALS_DIR = ROOT / "data" / "signals"
CONFIG_PATH = ROOT / "config" / "polymarket_accounts.json"


def _safe_float(x, default: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _hours_to_resolution(end_iso: str | None) -> float:
    if not end_iso:
        return 1e9
    try:
        end = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        return (end - now).total_seconds() / 3600
    except (ValueError, TypeError):
        return 1e9


def _yes_price(market: dict) -> float | None:
    """Extract YES outcome price from messy Gamma payload."""
    raw = market.get("outcomePrices")
    prices: list[float] = []
    if isinstance(raw, str):
        try:
            prices = [_safe_float(p) for p in json.loads(raw)]
        except (ValueError, TypeError):
            return None
    elif isinstance(raw, list):
        prices = [_safe_float(p) for p in raw]
    if not prices:
        return None
    return prices[0]


def _categories(market: dict) -> list[str]:
    """Extract category proxies from Gamma payload.

    Gamma's `category`/`categories`/`tags` are usually null at the market level.
    Fall back to event title + slug + market slug — these contain enough text
    to keyword-match against our `categories_of_interest` config.
    """
    cats: list[str] = []
    for k in ("category", "categories", "tags"):
        v = market.get(k)
        if isinstance(v, str):
            cats.append(v)
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, str):
                    cats.append(item)
                elif isinstance(item, dict) and item.get("label"):
                    cats.append(item["label"])
    # Event-level fallback (Gamma exposes the parent event when present)
    for ev in market.get("events") or []:
        for k in ("title", "slug", "ticker"):
            v = ev.get(k)
            if isinstance(v, str):
                cats.append(v)
        for tag in ev.get("tags") or []:
            if isinstance(tag, dict) and tag.get("label"):
                cats.append(tag["label"])
            elif isinstance(tag, str):
                cats.append(tag)
    if market.get("slug"):
        cats.append(market["slug"])
    return list({c.lower() for c in cats if c})


def _is_fee_free_geopolitical(cats: list[str]) -> bool:
    return any(c in {"world", "geopolitics", "world events", "international"} for c in cats)


def _normalize(market: dict) -> dict:
    return {
        "id": market.get("id") or market.get("conditionId"),
        "condition_id": market.get("conditionId"),
        "slug": market.get("slug"),
        "question": market.get("question"),
        "categories": _categories(market),
        "yes_price": _yes_price(market),
        "liquidity_usd": _safe_float(market.get("liquidity")),
        "volume_24h_usd": _safe_float(market.get("volume24hr") or market.get("volume24Hr") or market.get("volume24hrAmm")),
        "volume_total_usd": _safe_float(market.get("volume")),
        "end_date": market.get("endDate"),
        "hours_to_resolution": _hours_to_resolution(market.get("endDate")),
        "clob_token_ids": market.get("clobTokenIds"),
        "fee_free": _is_fee_free_geopolitical(_categories(market)),
    }


def _load_categories_filter() -> list[str] | None:
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    cats = cfg.get("categories_of_interest") or []
    # config uses snake_case like "politics_us" — Gamma uses "Politics" / "US Election"
    # We'll loosely match by token presence rather than exact string.
    return [c.lower() for c in cats]


def _category_match(market_cats: list[str], wanted: list[str] | None) -> bool:
    if not wanted:
        return True
    text = " ".join(market_cats)
    # Gamma's per-market category fields are null; categories are extracted from
    # event-level slug/title fallbacks which many markets lack. Default-allow so
    # all markets reach Layer 2; signal_engine filters by confluence score.
    # Set PM_STRICT_CATEGORIES=true to enforce hard keyword filtering.
    if not text:
        return os.environ.get("PM_STRICT_CATEGORIES", "").lower() != "true"
    for w in wanted:
        token = w.replace("_", " ").lower()
        head = token.split()[0]
        if head and head in text:
            return True
    return os.environ.get("PM_STRICT_CATEGORIES", "").lower() != "true"


def main() -> int:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir = SIGNALS_DIR / today
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "pm_markets.json"

    raw = pm_api.get_active_markets(limit=500, min_liquidity=10_000)
    print(f"[discover_markets] raw markets fetched: {len(raw)}")
    wanted = _load_categories_filter()

    seen: set[str] = set()
    out: list[dict] = []
    for m in raw:
        nm = _normalize(m)
        mid = nm["id"]
        if not mid or mid in seen:
            continue
        if nm["yes_price"] is None:
            continue
        # Drop markets resolving < 6h unless deep in-the-money
        if nm["hours_to_resolution"] < 6 and (nm["yes_price"] or 0) < 0.95:
            continue
        if not _category_match(nm["categories"], wanted):
            continue
        seen.add(mid)
        out.append(nm)

    # Rank by liquidity descending — downstream takes top-N
    out.sort(key=lambda x: x["liquidity_usd"], reverse=True)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(out),
        "markets": out,
    }
    out_path.write_text(json.dumps(payload, indent=2))
    print(f"[discover_markets] wrote {len(out)} markets → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
