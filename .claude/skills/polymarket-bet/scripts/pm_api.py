"""Thin HTTP client for Polymarket APIs.

Three endpoints:
  - Gamma  https://gamma-api.polymarket.com   — market discovery + metadata
  - CLOB   https://clob.polymarket.com        — orderbooks, prices, order placement
  - Data   https://data-api.polymarket.com    — wallet activity, leaderboard

Reads are public. Writes (place_limit_order) require wallet signing and are
disabled by default — guarded behind the `PM_LIVE_TRADING=true` env var so
paper-mode never accidentally hits the chain.

All functions return native Python (list/dict). On HTTP failure they log to
stderr and return [] / {} — the cron pipeline must never crash on a flaky
upstream.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

import requests


def project_root() -> Path:
    """Walk up from this file until we find config/risk_params.json (the
    canonical anchor). On Modal the repo lives at /app; locally it lives at
    the workspace root. parents[3] only works in one of those — the walk
    handles both."""
    for cand in Path(__file__).resolve().parents:
        if (cand / "config" / "risk_params.json").exists():
            return cand
    # Fallback: explicit Modal layout
    if Path("/app/config/risk_params.json").exists():
        return Path("/app")
    raise RuntimeError("Could not locate project root (no config/risk_params.json found in any ancestor)")

GAMMA_BASE = os.environ.get("PM_GAMMA_BASE", "https://gamma-api.polymarket.com")
CLOB_BASE = os.environ.get("PM_CLOB_BASE", "https://clob.polymarket.com")
DATA_BASE = os.environ.get("PM_DATA_BASE", "https://data-api.polymarket.com")

DEFAULT_TIMEOUT = 15
USER_AGENT = "trading-system/polymarket-bet (research)"

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})


def _get(url: str, params: Optional[dict] = None, timeout: int = DEFAULT_TIMEOUT) -> Optional[dict | list]:
    """GET with one retry on 429/5xx. Returns parsed JSON or None on failure."""
    for attempt in range(2):
        try:
            r = _session.get(url, params=params, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503, 504) and attempt == 0:
                time.sleep(1.5)
                continue
            print(f"[pm_api] GET {url} -> {r.status_code} {r.text[:200]}", file=sys.stderr)
            return None
        except requests.RequestException as e:
            if attempt == 0:
                time.sleep(1)
                continue
            print(f"[pm_api] GET {url} network error: {e}", file=sys.stderr)
            return None
    return None


def _post(url: str, payload: dict, timeout: int = DEFAULT_TIMEOUT) -> Optional[dict | list]:
    for attempt in range(2):
        try:
            r = _session.post(url, json=payload, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503, 504) and attempt == 0:
                time.sleep(1.5)
                continue
            print(f"[pm_api] POST {url} -> {r.status_code} {r.text[:200]}", file=sys.stderr)
            return None
        except requests.RequestException as e:
            if attempt == 0:
                time.sleep(1)
                continue
            print(f"[pm_api] POST {url} network error: {e}", file=sys.stderr)
            return None
    return None


# ── Gamma: market discovery ─────────────────────────────────────────────────
def get_active_markets(
    limit: int = 200,
    min_liquidity: float = 10_000.0,
    closed: bool = False,
    archived: bool = False,
) -> list[dict]:
    """Pull active Polymarket markets via Gamma /markets.

    Returns up to `limit` markets passing the liquidity filter. Each entry
    includes id, question, slug, category, outcomePrices, liquidity, volume,
    endDate, clobTokenIds (the per-outcome token IDs needed for CLOB calls).
    """
    out: list[dict] = []
    offset = 0
    page = 100
    while len(out) < limit:
        data = _get(
            f"{GAMMA_BASE}/markets",
            params={
                "limit": min(page, limit - len(out)),
                "offset": offset,
                "active": "true",
                "closed": "true" if closed else "false",
                "archived": "true" if archived else "false",
            },
        )
        if not data:
            break
        if not isinstance(data, list):
            break
        if not data:
            break
        out.extend(data)
        if len(data) < page:
            break
        offset += page
    # Liquidity filter (Gamma sometimes returns string)
    filtered = []
    for m in out:
        try:
            liq = float(m.get("liquidity") or 0)
        except (TypeError, ValueError):
            liq = 0
        if liq >= min_liquidity:
            filtered.append(m)
    return filtered


def get_market_by_id(market_id: str) -> Optional[dict]:
    data = _get(f"{GAMMA_BASE}/markets/{market_id}")
    return data if isinstance(data, dict) else None


# ── CLOB: orderbook + prices ────────────────────────────────────────────────
def get_orderbook_batch(token_ids: list[str]) -> dict:
    """Batch orderbook fetch via CLOB POST /books. ~50× cheaper than per-token /book.

    Returns dict keyed by token_id. Empty dict on failure.
    """
    if not token_ids:
        return {}
    # CLOB batch endpoint expects a list of {token_id} objects per docs
    payload = [{"token_id": t} for t in token_ids]
    data = _post(f"{CLOB_BASE}/books", payload)
    if not isinstance(data, list):
        return {}
    out = {}
    for entry in data:
        tid = entry.get("asset_id") or entry.get("token_id")
        if tid:
            out[tid] = entry
    return out


def get_midprice(token_id: str) -> Optional[float]:
    data = _get(f"{CLOB_BASE}/midpoint", params={"token_id": token_id})
    if not isinstance(data, dict):
        return None
    try:
        return float(data.get("mid"))
    except (TypeError, ValueError):
        return None


def get_price_history(token_id: str, interval: str = "1d", days: int = 30) -> list[dict]:
    """Historical price series. interval ∈ {1m, 1h, 6h, 1d, 1w, max}."""
    end_ts = int(time.time())
    start_ts = end_ts - days * 86400
    data = _get(
        f"{CLOB_BASE}/prices-history",
        params={"market": token_id, "startTs": start_ts, "endTs": end_ts, "interval": interval},
    )
    if not isinstance(data, dict):
        return []
    return data.get("history", [])


# ── Data API: wallet activity + leaderboard ─────────────────────────────────
def get_wallet_activity(wallet: str, limit: int = 100, since_ts: Optional[int] = None) -> list[dict]:
    """Pull recent activity (trades) for a wallet via Data API /activity.

    Returns list of activity entries with marketId, side (BUY/SELL), outcome,
    size, price, timestamp.
    """
    params: dict = {"user": wallet, "limit": limit}
    data = _get(f"{DATA_BASE}/activity", params=params)
    if not isinstance(data, list):
        return []
    if since_ts is not None:
        data = [e for e in data if int(e.get("timestamp") or 0) >= since_ts]
    return data


def get_wallet_positions(wallet: str) -> list[dict]:
    data = _get(f"{DATA_BASE}/positions", params={"user": wallet})
    return data if isinstance(data, list) else []


def get_leaderboard(period: str = "month", limit: int = 100) -> list[dict]:
    """Return ranked traders by profit. Tries several endpoint shapes since the
    data-api /leaderboard path was removed in mid-2025.

    Falls back to seed wallets from config/polymarket_accounts.json if all
    endpoints return 404 — so at least activity-scoring can run on known wallets.
    """
    # Try current and legacy endpoint shapes
    for path, params in [
        (f"{DATA_BASE}/leaderboard", {"window": period, "limit": limit}),
        (f"{DATA_BASE}/leaderboard", {"period": period, "limit": limit}),
        (f"{GAMMA_BASE}/leaderboard", {"limit": limit}),
    ]:
        data = _get(path, params=params)
        if isinstance(data, list) and data:
            return data
        if isinstance(data, dict):
            for key in ("leaderboard", "users", "data", "results"):
                if isinstance(data.get(key), list) and data[key]:
                    return data[key]

    # All remote endpoints failed — seed from config so scoring can still run
    try:
        cfg_path = project_root() / "config" / "polymarket_accounts.json"
        with open(cfg_path) as f:
            cfg = json.load(f)
        seeds = cfg.get("seed_wallets", [])
        if seeds:
            print(f"[pm_api] leaderboard unavailable; using {len(seeds)} seed wallets from config")
            return [{"proxyWallet": w, "profit": 0} for w in seeds]
    except Exception:
        pass

    return []


# ── Live order placement (Phase 2 — gated by env var) ───────────────────────
def is_live_enabled() -> bool:
    return os.environ.get("PM_LIVE_TRADING", "false").lower() == "true"


def place_limit_order(token_id: str, side: str, price: float, size: float) -> dict:
    """Place a CLOB limit order. Disabled unless PM_LIVE_TRADING=true.

    Wallet signing not yet wired — Phase 2 will add py-clob-client integration.
    """
    if not is_live_enabled():
        return {"ok": False, "reason": "PM_LIVE_TRADING is false; refusing to place real order"}
    return {
        "ok": False,
        "reason": "py-clob-client signing not yet implemented (Phase 2)",
        "would_have_sent": {"token_id": token_id, "side": side, "price": price, "size": size},
    }


if __name__ == "__main__":
    import json

    print("[pm_api] self-test")
    markets = get_active_markets(limit=5, min_liquidity=10_000)
    print(f"  fetched {len(markets)} markets")
    if markets:
        print(json.dumps({k: markets[0].get(k) for k in ("id", "question", "liquidity", "endDate")}, indent=2))
