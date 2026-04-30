"""Internal paper-trading engine.

When PAPER_MODE=true is set in the environment, the bot bypasses any real
exchange (Bybit, OKX, etc.) and instead:

  1. Fetches *real* current prices via public ccxt endpoints (no auth).
  2. Logs trades to the DB tagged broker='paper' at the live public price.
  3. Tracks a virtual balance in system_state (key='paper_balance_usd').
  4. Monitors open positions against live public prices each cron cycle.
  5. Auto-closes when SL/TP would be hit, credits/debits the virtual balance.

This mode exists for two reasons:
  - The user is in a region (Bulgaria/EU) where Bybit/OKX testnet is not
    accessible and OKX live KYC takes days. Internal paper trading lets the
    full pipeline run end-to-end with no exchange dependency.
  - It's a pure simulation against real-time market data, so the
    self-improvement loop, daily briefs, weekly reviews, and trade journal
    all accumulate as if real trading were happening.

When the user later configures real exchange keys and removes PAPER_MODE,
the bot transparently switches to live execution. No DB schema changes
needed; trades just have broker='paper' vs broker='okx' to distinguish.

Environment:
  PAPER_MODE=true               → enable internal paper trading
  PAPER_STARTING_BALANCE=500    → initial virtual capital (default 500 USD)
  PAPER_PRICE_EXCHANGE=okx      → which public exchange to fetch prices from
                                   (must match watchlist symbol format)
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from typing import Optional

PROJECT_ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from lib.db import get_connection, get_system_state, set_system_state


# ─── Config ───────────────────────────────────────────────────────────────


def is_paper_mode() -> bool:
    """Returns True if PAPER_MODE=true is in env or .env."""
    val = os.environ.get("PAPER_MODE", "").lower().strip()
    if val:
        return val == "true"
    # Fallback: check .env
    try:
        from dotenv import dotenv_values  # type: ignore
        env = dotenv_values(os.path.join(PROJECT_ROOT, ".env"))
        return env.get("PAPER_MODE", "").lower().strip() == "true"
    except Exception:
        return False


def starting_balance() -> float:
    val = os.environ.get("PAPER_STARTING_BALANCE", "")
    if not val:
        try:
            from dotenv import dotenv_values  # type: ignore
            env = dotenv_values(os.path.join(PROJECT_ROOT, ".env"))
            val = env.get("PAPER_STARTING_BALANCE", "500")
        except Exception:
            val = "500"
    try:
        return float(val)
    except ValueError:
        return 500.0


def _price_exchange_id() -> str:
    val = os.environ.get("PAPER_PRICE_EXCHANGE", "")
    if not val:
        try:
            from dotenv import dotenv_values  # type: ignore
            env = dotenv_values(os.path.join(PROJECT_ROOT, ".env"))
            val = env.get("PAPER_PRICE_EXCHANGE", "okx")
        except Exception:
            val = "okx"
    return val.lower()


# ─── Public price fetch (no auth) ─────────────────────────────────────────

_EXCHANGE_CACHE = {}


def _public_exchange():
    """Return a cached, unauthenticated ccxt exchange for price fetching."""
    eid = _price_exchange_id()
    if eid in _EXCHANGE_CACHE:
        return _EXCHANGE_CACHE[eid]
    import ccxt  # type: ignore
    exchange_cls = getattr(ccxt, eid, None)
    if exchange_cls is None:
        raise RuntimeError(f"unknown ccxt exchange id: {eid}")
    ex = exchange_cls({"options": {"defaultType": "swap"}, "enableRateLimit": True})
    _EXCHANGE_CACHE[eid] = ex
    return ex


def get_public_price(symbol: str) -> Optional[float]:
    """Fetch the current price for a symbol via public OHLCV (no auth).

    Returns the last close price, or None on failure (caller decides whether
    to skip the position this cycle).
    """
    try:
        ex = _public_exchange()
        # Use 1m latest candle close as the most recent price snapshot
        candles = ex.fetch_ohlcv(symbol, "1m", limit=2)
        if not candles:
            return None
        return float(candles[-1][4])  # close of latest candle
    except Exception as e:
        print(f"[paper_engine] price fetch failed for {symbol}: {e}")
        return None


# ─── Paper balance ────────────────────────────────────────────────────────


def get_paper_balance() -> dict:
    """Return the virtual paper balance.

    Initializes to PAPER_STARTING_BALANCE on first call.
    Returns: {'free': float, 'total': float}
        - 'total' is the virtual capital
        - 'free' subtracts margin currently locked in open paper positions
    """
    conn = get_connection()
    try:
        raw = get_system_state(conn, "paper_balance_usd")
        if raw is None or raw == "":
            initial = starting_balance()
            set_system_state(conn, "paper_balance_usd", str(initial))
            total = initial
        else:
            total = float(raw)
        # Compute locked margin from open paper trades
        rows = conn.execute(
            """SELECT COALESCE(SUM(quantity * entry_price / leverage), 0)
               FROM trades
               WHERE status='open' AND broker LIKE 'paper%'"""
        ).fetchone()
        locked = float(rows[0] or 0)
        return {"total": total, "free": max(0.0, total - locked), "locked": locked}
    finally:
        conn.close()


def credit_paper_balance(pnl_usd: float, reason: str = "") -> float:
    """Credit (or debit, if negative) the paper balance after a trade closes.
    Returns the new total balance.
    """
    conn = get_connection()
    try:
        raw = get_system_state(conn, "paper_balance_usd")
        cur = float(raw) if raw else starting_balance()
        new_total = cur + pnl_usd
        set_system_state(conn, "paper_balance_usd", str(new_total))
        print(f"[paper_engine] balance: ${cur:.2f} -> ${new_total:.2f} ({pnl_usd:+.2f}, {reason})")
        return new_total
    finally:
        conn.close()


# ─── Order simulation ─────────────────────────────────────────────────────


def simulate_order(order: dict) -> dict:
    """Simulate an order placement against the real public price feed.

    The trade is logged to the DB at the *current* public price (not the
    intended entry_price from the order — slippage is implicit since we
    fill at market). Position size and margin requirements are validated
    against the virtual balance.

    Returns the same shape as the real execute_order: a dict with status,
    orders, errors.
    """
    asset = order["asset"]
    direction = order["direction"]
    size = order["position_size"]
    leverage = int(order["leverage"])
    sl = order["stop_loss"]
    tp = order["take_profit"]

    result = {
        "asset": asset,
        "direction": direction,
        "size": size,
        "leverage": leverage,
        "paper": True,
        "orders": {},
        "errors": [],
    }

    # Pre-flight: sufficient balance?
    bal = get_paper_balance()
    margin_needed = order.get("margin_required_usd", (size * order["entry_price"]) / leverage)
    if bal["free"] < margin_needed:
        result["status"] = "REJECTED"
        result["errors"].append(
            f"Paper balance insufficient: ${bal['free']:.2f} free, need ${margin_needed:.2f}"
        )
        return result

    # Get the live price — this is our actual fill
    live_price = get_public_price(asset)
    if live_price is None:
        result["status"] = "ERROR"
        result["errors"].append(f"Could not fetch live price for {asset}")
        return result

    result["fill_price"] = live_price
    result["intended_entry"] = order["entry_price"]
    slippage_pct = ((live_price - order["entry_price"]) / order["entry_price"]) * 100
    result["slippage_pct"] = round(slippage_pct, 4)

    # Generate fake order IDs that look real
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    result["orders"] = {
        "entry": {"id": f"paper_{ts}_entry", "status": "filled", "filled": size, "avg_price": live_price},
        "stop_loss": {"id": f"paper_{ts}_sl", "trigger": sl},
        "take_profit": {"id": f"paper_{ts}_tp", "trigger": tp},
    }
    result["status"] = "EXECUTED"
    return result


# ─── Helper used by position_monitor ──────────────────────────────────────


def is_paper_trade(trade: dict) -> bool:
    """Returns True if the trade was placed via the paper engine."""
    broker = (trade.get("broker") or "").lower()
    return broker.startswith("paper")
