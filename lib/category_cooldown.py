"""Asset-category cooldown — sister of the global circuit breaker.

The global circuit breaker (`risk_engine.check_consecutive_losses`) halts
ALL trading after N consecutive losses across the whole portfolio. That's
too coarse: if 3 crypto perp trades go bad in a row, we don't want to also
freeze stock or bond trading.

This module tracks consecutive losses *per asset category*. When a category
hits the threshold (default 2), it goes on cooldown for `cooldown_hours`
(default 4). Losses in OTHER categories don't bump the counter, and a win
in the cooldowned category resets it.

State is persisted in `system_state['category_cooldowns']` as JSON:

  {
    "CRYPTO_PERP":   {"consecutive_losses": 1, "cooldown_until": null,
                       "last_updated": "2026-04-25T18:42:11Z"},
    "STOCK_EQUITY":  {"consecutive_losses": 0, "cooldown_until": null,
                       "last_updated": "2026-04-25T13:11:00Z"}
  }

Public API:
  - is_category_in_cooldown(conn, category) -> (bool, until_iso_or_None)
  - register_trade_close(conn, category, won: bool) -> dict  (the new state)
  - asset_to_category(symbol) -> str  (best-effort heuristic, falls back to CRYPTO_PERP)
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone, timedelta

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from lib.db import get_system_state, set_system_state

CATEGORY_COOLDOWN_KEY = "category_cooldowns"
DEFAULT_LOSS_THRESHOLD = int(os.environ.get("CATEGORY_LOSS_THRESHOLD", "2"))
DEFAULT_COOLDOWN_HOURS = float(os.environ.get("CATEGORY_COOLDOWN_HOURS", "4"))


# ── Heuristic: map a Bybit-style symbol to a coarse asset category. ─────────
# Will be replaced by lib/brokers/<adapter>.asset_class once Stage 4 lands.
def asset_to_category(symbol: str) -> str:
    if not symbol:
        return "UNKNOWN"
    s = symbol.upper()
    # Bybit perp pattern: "BTC/USDT:USDT"
    if ":" in s and "USDT" in s:
        return "CRYPTO_PERP"
    if "/USDT" in s or "/USDC" in s or "/BTC" in s:
        return "CRYPTO_SPOT"
    # CFD commodity tickers (gold, silver, oil, copper, etc.) — must come
    # before forex-pair check, since XAUUSD looks like an FX pair to a naive
    # 6-char regex but is actually gold-vs-USD priced via a CFD broker.
    if s in {"XAUUSD", "XAGUSD", "XPTUSD", "XPDUSD", "USOIL", "UKOIL",
             "BRENT", "WTI", "NATGAS", "COPPER", "XAU", "XAG"}:
        return "CFD_COMMODITY"
    # CFD index tickers (digits in name distinguish from stocks).
    if s in {"SPX500", "NAS100", "US30", "GER40", "UK100", "JPN225",
             "AUS200", "FRA40", "EU50", "HK50", "CHINA50"}:
        return "CFD_INDEX"
    # Forex pairs (ISO codes only)
    fx_majors = {"EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD", "USD"}
    parts = s.replace("/", "").replace(":", "")
    if len(parts) == 6 and parts[:3] in fx_majors and parts[3:] in fx_majors:
        return "FOREX_SPOT"
    # Stock-style symbols: short alphanumeric with no slash
    if "/" not in s and 1 <= len(s) <= 6 and s.isalpha():
        # Bond ETFs we care about
        if s in {"TLT", "IEF", "SHY", "AGG", "BND", "LQD", "HYG"}:
            return "BOND_ETF"
        return "STOCK_EQUITY"
    return "UNKNOWN"


def _load_state(conn) -> dict:
    raw = get_system_state(conn, CATEGORY_COOLDOWN_KEY)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}


def _save_state(conn, state: dict) -> None:
    set_system_state(conn, CATEGORY_COOLDOWN_KEY, json.dumps(state, default=str))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def is_category_in_cooldown(conn, category: str) -> tuple[bool, str | None]:
    """Returns (in_cooldown, cooldown_until_iso_or_None)."""
    state = _load_state(conn)
    entry = state.get(category)
    if not entry:
        return False, None
    until = entry.get("cooldown_until")
    if not until:
        return False, None
    try:
        until_dt = datetime.fromisoformat(until.replace("Z", "+00:00"))
    except ValueError:
        return False, None
    if _now() < until_dt:
        return True, until
    # Expired — clear it lazily but don't write back unless explicitly registering
    return False, None


def register_trade_close(
    conn,
    category: str,
    won: bool,
    *,
    loss_threshold: int = DEFAULT_LOSS_THRESHOLD,
    cooldown_hours: float = DEFAULT_COOLDOWN_HOURS,
) -> dict:
    """Update consecutive-loss counter for a category.

    A win resets the counter and clears any active cooldown. A loss bumps
    the counter; if it reaches `loss_threshold`, set cooldown_until to
    now + `cooldown_hours`.

    Returns the entry dict for this category after the update.
    """
    state = _load_state(conn)
    entry = state.get(category) or {
        "consecutive_losses": 0,
        "cooldown_until": None,
        "last_updated": None,
    }

    if won:
        entry["consecutive_losses"] = 0
        entry["cooldown_until"] = None
    else:
        entry["consecutive_losses"] = int(entry.get("consecutive_losses", 0)) + 1
        if entry["consecutive_losses"] >= loss_threshold:
            until = _now() + timedelta(hours=cooldown_hours)
            entry["cooldown_until"] = until.isoformat()

    entry["last_updated"] = _now().isoformat()
    state[category] = entry
    _save_state(conn, state)
    return entry


def list_active_cooldowns(conn) -> dict:
    """Return only categories currently in cooldown."""
    state = _load_state(conn)
    active = {}
    for cat in state:
        in_cd, until = is_category_in_cooldown(conn, cat)
        if in_cd:
            active[cat] = until
    return active


if __name__ == "__main__":
    # Tiny self-test against the live DB. Read-only style: register loss/win
    # for a test category and print resulting state.
    from lib.db import get_connection

    conn = get_connection()
    try:
        cat = "TEST_CATEGORY"
        state = register_trade_close(conn, cat, won=False)
        print(f"after loss 1 → {state}")
        state = register_trade_close(conn, cat, won=False)
        print(f"after loss 2 → {state}")
        in_cd, until = is_category_in_cooldown(conn, cat)
        print(f"in cooldown? {in_cd} until {until}")
        state = register_trade_close(conn, cat, won=True)
        print(f"after win → {state}")
        in_cd, until = is_category_in_cooldown(conn, cat)
        print(f"in cooldown? {in_cd} until {until}")
    finally:
        conn.close()
