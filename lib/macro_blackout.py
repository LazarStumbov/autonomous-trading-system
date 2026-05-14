"""Macro event blackout gate.

Reads data/signals/<date>/econ_calendar.json and exposes:
  - is_in_blackout(asset_class)         → bool, True if NOW is inside an active window
  - active_blackouts(asset_class)       → list[dict] of currently-active windows
  - next_blackout(asset_class)          → next upcoming blackout for that class

risk_engine.check_trade() should call is_in_blackout() and reject new positions
when True. Stage 1 ships the standalone module + tests; wiring into the live
risk gate is a follow-up edit so we don't accidentally block paper trades
that the user wants for the journal.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# Map our internal asset_class string (lib.constants.AssetClass.value) to the
# coarse classes used by econ_calendar event tagging.
_ASSET_CLASS_TO_BUCKET = {
    "crypto_perp": "crypto",
    "crypto_spot": "crypto",
    "stock_equity": "equities",
    "bond_etf": "bonds",
    "bond_future": "bonds",
    "forex_spot": "fx",
    "cfd_forex": "fx",
    "cfd_index": "equities",
    "cfd_commodity": "commodities",
    "polymarket_binary": "polymarket",
}


def _load_calendar(date_str: str | None = None) -> dict:
    if not date_str:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = Path(PROJECT_ROOT) / "data" / "signals" / date_str / "econ_calendar.json"
    if not path.exists():
        return {"events": [], "blackouts": []}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {"events": [], "blackouts": []}


def _bucket_for(asset_class: str) -> str:
    return _ASSET_CLASS_TO_BUCKET.get((asset_class or "").lower(), asset_class or "")


def active_blackouts(asset_class: str) -> list[dict]:
    """All blackout windows that contain NOW and affect this asset class."""
    cal = _load_calendar()
    now = datetime.now(timezone.utc)
    bucket = _bucket_for(asset_class)
    out: list[dict] = []
    for b in cal.get("blackouts", []):
        try:
            start = datetime.fromisoformat(b["start_utc"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(b["end_utc"].replace("Z", "+00:00"))
        except (ValueError, KeyError):
            continue
        if start <= now <= end and bucket in (b.get("affected_classes") or []):
            out.append(b)
    return out


def is_in_blackout(asset_class: str) -> bool:
    return len(active_blackouts(asset_class)) > 0


def next_blackout(asset_class: str) -> dict | None:
    cal = _load_calendar()
    now = datetime.now(timezone.utc)
    bucket = _bucket_for(asset_class)
    upcoming: list[tuple[datetime, dict]] = []
    for b in cal.get("blackouts", []):
        try:
            start = datetime.fromisoformat(b["start_utc"].replace("Z", "+00:00"))
        except (ValueError, KeyError):
            continue
        if start > now and bucket in (b.get("affected_classes") or []):
            upcoming.append((start, b))
    if not upcoming:
        return None
    upcoming.sort(key=lambda t: t[0])
    return upcoming[0][1]


if __name__ == "__main__":
    import sys as _sys
    cls = _sys.argv[1] if len(_sys.argv) > 1 else "crypto_perp"
    print(f"asset_class={cls}  bucket={_bucket_for(cls)}")
    print(f"in_blackout_now={is_in_blackout(cls)}")
    print(f"active={active_blackouts(cls)}")
    print(f"next={next_blackout(cls)}")
