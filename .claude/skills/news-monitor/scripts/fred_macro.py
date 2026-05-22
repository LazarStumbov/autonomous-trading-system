"""FRED macro data fetcher (free, requires FRED_API_KEY).

Pulls the headline US macro series the brain needs for regime reads:
  - DGS10 (10y treasury yield)
  - DGS2  (2y treasury — yield curve)
  - DTWEXBGS (broad dollar index, USD strength proxy)
  - CPIAUCSL (headline CPI)
  - UNRATE (unemployment rate)
  - FEDFUNDS (effective fed funds rate)
  - T10Y2Y (yield curve spread — calculated by FRED)
  - WTISPLC (WTI oil)
  - M2SL (M2 money supply)

Writes data/signals/<date>/macro_fred.json with latest value + 30-day delta
per series, plus a coarse regime tag (risk-on / risk-off / mixed).

Free tier limit: 120 req/min. We do 9 calls per run → trivially under cap.
On missing API key the script writes an empty payload and exits 0 so the
cron stays green.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import urllib.request

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

def _env(key: str, default: str = "") -> str:
    """Read env var, fall back to .env at PROJECT_ROOT. Truthy default isn't
    short-circuited (the OKX adapter had a bug where it was — same pattern fixed)."""
    v = os.environ.get(key, "")
    if not v:
        try:
            from dotenv import dotenv_values  # type: ignore
            env = dotenv_values(os.path.join(PROJECT_ROOT, ".env"))
            v = env.get(key, "") or ""
        except Exception:
            pass
    return v or default


SERIES = {
    "DGS10": "10y treasury yield",
    "DGS2": "2y treasury yield",
    "DTWEXBGS": "broad USD index",
    "CPIAUCSL": "CPI headline",
    "UNRATE": "unemployment rate",
    "FEDFUNDS": "fed funds rate",
    "T10Y2Y": "yield curve spread (10y-2y)",
    "WTISPLC": "WTI oil price",
    "M2SL": "M2 money supply",
}


def _fetch_series(series_id: str, api_key: str) -> list[dict]:
    """Return last 90 observations for a series. Empty list on failure."""
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=90)
    url = (
        f"https://api.stlouisfed.org/fred/series/observations"
        f"?series_id={series_id}"
        f"&observation_start={start.isoformat()}"
        f"&observation_end={end.isoformat()}"
        f"&api_key={api_key}&file_type=json"
    )
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.loads(r.read())
        out = []
        for obs in data.get("observations") or []:
            v = obs.get("value")
            if v in (None, ".", ""):
                continue
            try:
                out.append({"date": obs["date"], "value": float(v)})
            except (ValueError, TypeError):
                continue
        return out
    except Exception as e:
        print(f"[fred_macro] {series_id} fetch failed: {e}")
        return []


def _regime_from_series(payload: dict) -> dict:
    """Coarse regime tag from yield curve + DXY direction.

    Signals:
      - Inverted curve (T10Y2Y < 0)         → recession risk
      - Strong USD trend (DXY +>1% in 30d)  → risk-off
      - High oil ROC (WTI +>10% in 30d)     → inflation risk
    """
    tags: list[str] = []
    notes: list[str] = []
    spread_obs = payload.get("T10Y2Y", {}).get("history") or []
    if spread_obs and spread_obs[-1]["value"] < 0:
        tags.append("inverted_curve")
        notes.append(f"T10Y2Y={spread_obs[-1]['value']:.2f}")
    dxy_obs = payload.get("DTWEXBGS", {}).get("history") or []
    if len(dxy_obs) >= 2:
        delta = (dxy_obs[-1]["value"] - dxy_obs[0]["value"]) / max(dxy_obs[0]["value"], 1e-9)
        if delta > 0.01:
            tags.append("dxy_rising")
            notes.append(f"DXY +{delta*100:.2f}% 30d")
    oil_obs = payload.get("WTISPLC", {}).get("history") or []
    if len(oil_obs) >= 2:
        delta = (oil_obs[-1]["value"] - oil_obs[0]["value"]) / max(oil_obs[0]["value"], 1e-9)
        if delta > 0.10:
            tags.append("oil_inflation_risk")
            notes.append(f"WTI +{delta*100:.1f}% 30d")
    bias = "risk_off" if ("inverted_curve" in tags or "dxy_rising" in tags) else "neutral"
    return {"bias": bias, "tags": tags, "notes": notes}


def main() -> int:
    api_key = _env("FRED_API_KEY").strip()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir = Path(PROJECT_ROOT) / "data" / "signals" / today
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "macro_fred.json"

    if not api_key:
        print("[fred_macro] FRED_API_KEY missing — writing empty stub")
        out_path.write_text(json.dumps({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "error": "FRED_API_KEY missing",
            "series": {},
            "regime": {"bias": "unknown", "tags": [], "notes": []},
        }, indent=2))
        return 0

    payload: dict[str, dict] = {}
    for sid, label in SERIES.items():
        history = _fetch_series(sid, api_key)
        if not history:
            continue
        latest = history[-1]
        delta_30d = None
        if len(history) >= 2:
            delta_30d = round(latest["value"] - history[0]["value"], 4)
        payload[sid] = {
            "label": label,
            "latest_value": latest["value"],
            "latest_date": latest["date"],
            "delta_30d": delta_30d,
            "history": history,
        }
    regime = _regime_from_series(payload)
    out_path.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "series": payload,
        "regime": regime,
    }, indent=2))
    print(f"[fred_macro] {len(payload)} series fetched, bias={regime['bias']}, "
          f"tags={regime['tags']} → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
