"""Economic calendar fetcher (free guest endpoint, no key required).

Trading Economics' guest tier returns ~25 upcoming events per call. We
filter to high-importance events (importance=3) for the next 7 days,
classify by affected asset class, and tag each as a `blackout` event
for macro_blackout.

Writes data/signals/<date>/econ_calendar.json with:
  - events: list of upcoming releases
  - blackouts: list of time windows during which we should reject new
    positions in affected asset classes
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)


# Maps event keywords -> affected asset classes. Coarse but load-bearing:
# any new position in an affected class within `blackout_minutes` of a
# scheduled release is rejected by lib.macro_blackout.is_in_blackout().
EVENT_RULES = [
    # (keyword_substring_lower, affected_classes, blackout_minutes_before, after)
    ("fomc", ["crypto", "equities", "bonds", "fx", "commodities"], 30, 60),
    ("rate decision", ["crypto", "equities", "bonds", "fx"], 30, 60),
    ("cpi", ["crypto", "equities", "bonds", "fx"], 15, 30),
    ("ppi", ["bonds", "fx"], 15, 30),
    ("non-farm payroll", ["fx", "equities", "bonds"], 15, 30),
    ("nfp", ["fx", "equities", "bonds"], 15, 30),
    ("gdp", ["fx", "equities"], 15, 30),
    ("unemployment rate", ["fx", "equities"], 15, 30),
    ("ecb", ["fx", "equities"], 30, 60),
    ("boj", ["fx", "equities"], 30, 60),
    ("boe", ["fx"], 30, 60),
    ("retail sales", ["fx", "equities"], 15, 30),
    ("ism", ["equities", "fx"], 15, 30),
    ("crude oil inventories", ["commodities"], 15, 30),
]


def _classify(event_name: str) -> tuple[list[str], int, int] | None:
    name = (event_name or "").lower()
    for kw, classes, before, after in EVENT_RULES:
        if kw in name:
            return classes, before, after
    return None


def _fetch() -> list[dict]:
    """Pull upcoming economic events. Uses Trading Economics free guest endpoint."""
    url = "https://api.tradingeconomics.com/calendar?c=guest:guest&format=json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "trading-system/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        if not isinstance(data, list):
            return []
        return data
    except Exception as e:
        print(f"[econ_calendar] fetch failed: {e}")
        return []


def main() -> int:
    raw = _fetch()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir = Path(PROJECT_ROOT) / "data" / "signals" / today
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "econ_calendar.json"

    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=7)
    events: list[dict] = []
    blackouts: list[dict] = []

    for ev in raw:
        # TE returns ISO timestamps in "Date" and importance in "Importance"
        try:
            ts = datetime.fromisoformat(str(ev.get("Date", "")).replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue
        if ts < now or ts > horizon:
            continue
        importance = int(ev.get("Importance") or 0)
        if importance < 2:
            continue
        country = ev.get("Country") or ""
        name = ev.get("Event") or ev.get("Category") or ""
        rule = _classify(name)
        record = {
            "time_utc": ts.isoformat(),
            "country": country,
            "event": name,
            "importance": importance,
            "forecast": ev.get("Forecast"),
            "previous": ev.get("Previous"),
        }
        events.append(record)
        if rule:
            classes, before, after = rule
            blackouts.append({
                "event": name,
                "country": country,
                "start_utc": (ts - timedelta(minutes=before)).isoformat(),
                "end_utc": (ts + timedelta(minutes=after)).isoformat(),
                "affected_classes": classes,
            })

    events.sort(key=lambda e: e["time_utc"])
    blackouts.sort(key=lambda b: b["start_utc"])

    out_path.write_text(json.dumps({
        "generated_at": now.isoformat(),
        "horizon_days": 7,
        "events": events,
        "blackouts": blackouts,
    }, indent=2))
    print(f"[econ_calendar] {len(events)} events ({len(blackouts)} blackouts) → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
