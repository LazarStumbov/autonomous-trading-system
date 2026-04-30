"""Monitor open positions. Handle trailing stops, partial TP, breakeven moves, and closures.

Progressive trailing-stop tightening (crypto-scaled):
  As unrealized profit grows, the trailing distance SHRINKS. This lets
  winners run during normal noise but locks in profit aggressively once
  a move is decisively in our favour. Tiers are crypto-scaled (NOT
  Nate Herk's stock 7%/5% — those are way too wide for 5m–1h crypto).

  Tier table (configurable via PROGRESSIVE_TRAIL_TIERS env or the
  defaults below):
    +3 % → trail at 2.0 %  (loose; let it breathe)
    +7 % → trail at 1.5 %
    +15% → trail at 0.8 %
    +25% → trail at 0.4 %  (tight; we are deep in the money)

  The base trailing logic from config (`trailing_stop_*`) still triggers
  Rule 2; this tier table just *replaces* the flat distance with the
  tier-appropriate one once tier ≥1 is reached.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from lib.db import get_connection, init_db, get_open_trades, close_trade, set_system_state, get_system_state
from lib.risk_engine import load_risk_config
from lib.category_cooldown import register_trade_close, asset_to_category
from lib.paper_engine import is_paper_mode, get_public_price, credit_paper_balance, is_paper_trade

# Real-broker imports — only used when not in paper mode
def get_exchange():
    from lib.brokers.okx_adapter import get_exchange as _ge
    return _ge()

def get_positions(exchange):
    return exchange.fetch_positions()

def get_ticker(exchange, symbol: str) -> dict:
    return exchange.fetch_ticker(symbol)


# Progressive trailing tiers — (min_pnl_pct, trailing_distance_pct).
# Sorted ascending; we pick the LAST tier we've cleared.
DEFAULT_PROGRESSIVE_TIERS = [
    (3.0, 2.0),
    (7.0, 1.5),
    (15.0, 0.8),
    (25.0, 0.4),
]


def _load_progressive_tiers() -> list[tuple[float, float]]:
    """Read tiers from env (JSON) or fall back to defaults.

    Env format: PROGRESSIVE_TRAIL_TIERS='[[3,2],[7,1.5],[15,0.8],[25,0.4]]'
    """
    raw = os.environ.get("PROGRESSIVE_TRAIL_TIERS")
    if not raw:
        return DEFAULT_PROGRESSIVE_TIERS
    try:
        parsed = json.loads(raw)
        tiers = [(float(p), float(d)) for p, d in parsed]
        return sorted(tiers, key=lambda t: t[0])
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        print(f"[position_monitor] bad PROGRESSIVE_TRAIL_TIERS, using defaults: {e}")
        return DEFAULT_PROGRESSIVE_TIERS


def _progressive_distance(pnl_pct: float, tiers: list[tuple[float, float]]) -> float | None:
    """Return the tightest (smallest) trailing distance whose threshold pnl_pct has cleared.
    Returns None if no tier qualifies."""
    qualifying = [d for thresh, d in tiers if pnl_pct >= thresh]
    return min(qualifying) if qualifying else None


def monitor_positions(dry_run: bool = False) -> dict:
    """Check all open positions and apply management rules.

    Returns:
        Dict with position statuses and actions taken.
    """
    config = load_risk_config()
    sl_config = config["market_trading"]["stop_loss"]
    tp_config = config["market_trading"]["take_profit"]

    init_db()
    conn = get_connection()
    db_trades = get_open_trades(conn, pillar="market")

    if not db_trades:
        conn.close()
        return {"status": "NO_POSITIONS", "positions": []}

    paper = is_paper_mode()

    if paper:
        # Paper mode: no exchange queries, only public price fetches per-trade
        exchange = None
        ex_pos_map = {}
    else:
        exchange = get_exchange() if not dry_run else None
        exchange_positions = get_positions(exchange) if exchange else []
        ex_pos_map = {p["symbol"]: p for p in exchange_positions}

    results = []

    for trade in db_trades:
        asset = trade["asset"]
        direction = trade["direction"]
        entry = trade["entry_price"]
        sl = trade["stop_loss"]
        tp = trade["take_profit"]
        trade_id = trade["id"]

        pos_result = {
            "trade_id": trade_id,
            "asset": asset,
            "direction": direction,
            "entry": entry,
            "actions": [],
        }

        # Get current price
        if paper or is_paper_trade(trade):
            # Paper-mode: fetch live public price; no exchange position to query
            current_price = get_public_price(asset)
            if current_price is None:
                pos_result["actions"].append("PRICE_FETCH_FAILED")
                results.append(pos_result)
                continue
            pos_result["current_price"] = current_price
            # Estimate unrealized P&L for paper trades
            qty = float(trade.get("quantity") or 0)
            if direction == "long":
                pos_result["unrealized_pnl"] = (current_price - entry) * qty
            else:
                pos_result["unrealized_pnl"] = (entry - current_price) * qty
        elif exchange:
            ex_pos = ex_pos_map.get(asset)
            if ex_pos:
                current_price = ex_pos["mark_price"]
                unrealized_pnl = ex_pos["unrealized_pnl"]
                pos_result["current_price"] = current_price
                pos_result["unrealized_pnl"] = unrealized_pnl
            else:
                # Position closed on exchange but still open in DB
                try:
                    ticker = get_ticker(exchange, asset)
                    current_price = ticker["last"]
                except Exception:
                    current_price = entry

                # Check if SL or TP was hit
                pos_result["actions"].append("POSITION_CLOSED_ON_EXCHANGE")
                _close_position_in_db(conn, trade, current_price)
                pos_result["closed"] = True
                results.append(pos_result)
                continue
        else:
            current_price = entry  # Can't check in dry run without exchange
            pos_result["current_price"] = current_price

        # Calculate R (risk units moved)
        risk_distance = abs(entry - sl)
        if risk_distance == 0:
            results.append(pos_result)
            continue

        if direction == "long":
            r_moved = (current_price - entry) / risk_distance
        else:
            r_moved = (entry - current_price) / risk_distance

        pos_result["r_moved"] = round(r_moved, 2)

        # Rule 1: Move SL to breakeven at 1R profit
        if r_moved >= 1.0 and sl != entry:
            new_sl = entry
            pos_result["actions"].append(f"MOVE_SL_TO_BREAKEVEN: {sl} -> {new_sl}")
            if exchange and not dry_run:
                _update_stop_loss(exchange, asset, direction, trade["quantity"], new_sl)

        # Rule 2: Trailing stop activation (with progressive crypto-scaled tightening)
        trailing_activation = sl_config["trailing_stop_activation_pct"]
        base_trailing_distance = sl_config["trailing_stop_distance_pct"]
        tiers = _load_progressive_tiers()

        pnl_pct = ((current_price - entry) / entry * 100) if direction == "long" else ((entry - current_price) / entry * 100)

        # Pick the tightest trailing distance whose tier we've cleared.
        # Falls back to base distance if no tier has cleared but base activation
        # threshold has.
        progressive = _progressive_distance(pnl_pct, tiers)
        if progressive is not None:
            trailing_distance = progressive
            tier_label = f"PROGRESSIVE_TRAIL[{trailing_distance:.2f}%]"
        else:
            trailing_distance = base_trailing_distance
            tier_label = "TRAILING_STOP"

        if pnl_pct >= trailing_activation or progressive is not None:
            if direction == "long":
                new_sl = current_price * (1 - trailing_distance / 100)
                if new_sl > sl:
                    pos_result["actions"].append(f"{tier_label}: {sl} -> {new_sl:.2f} (pnl={pnl_pct:.2f}%)")
                    if exchange and not dry_run:
                        _update_stop_loss(exchange, asset, direction, trade["quantity"], new_sl)
            else:
                new_sl = current_price * (1 + trailing_distance / 100)
                if new_sl < sl:
                    pos_result["actions"].append(f"{tier_label}: {sl} -> {new_sl:.2f} (pnl={pnl_pct:.2f}%)")
                    if exchange and not dry_run:
                        _update_stop_loss(exchange, asset, direction, trade["quantity"], new_sl)

        # Rule 3: Partial TP at 1R
        if tp_config["partial_tp_at_1r_pct"] > 0 and r_moved >= 1.0:
            pos_result["actions"].append(f"PARTIAL_TP_ELIGIBLE: {tp_config['partial_tp_at_1r_pct']}% at 1R")

        # Rule 4: Check if SL/TP hit
        if direction == "long":
            if current_price <= sl:
                pos_result["actions"].append("STOP_LOSS_HIT")
                _close_position_in_db(conn, trade, current_price)
                pos_result["closed"] = True
            elif current_price >= tp:
                pos_result["actions"].append("TAKE_PROFIT_HIT")
                _close_position_in_db(conn, trade, current_price)
                pos_result["closed"] = True
        else:
            if current_price >= sl:
                pos_result["actions"].append("STOP_LOSS_HIT")
                _close_position_in_db(conn, trade, current_price)
                pos_result["closed"] = True
            elif current_price <= tp:
                pos_result["actions"].append("TAKE_PROFIT_HIT")
                _close_position_in_db(conn, trade, current_price)
                pos_result["closed"] = True

        results.append(pos_result)

    conn.close()

    return {
        "status": "MONITORED",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "positions_checked": len(results),
        "positions": results,
    }


def _close_position_in_db(conn, trade: dict, exit_price: float):
    """Close a trade in the database and update system state."""
    entry = trade["entry_price"]
    qty = trade["quantity"]
    direction = trade["direction"]

    if direction == "long":
        pnl_usd = (exit_price - entry) * qty
    else:
        pnl_usd = (entry - exit_price) * qty

    pnl_pct = (pnl_usd / (entry * qty)) * 100

    close_trade(conn, trade["id"], exit_price, pnl_usd, pnl_pct)

    # Paper-trade: credit/debit the virtual balance
    if is_paper_trade(trade):
        credit_paper_balance(pnl_usd, reason=f"trade #{trade['id']} {trade.get('asset','?')} {direction}")

    # Update consecutive losses (global circuit breaker)
    if pnl_usd < 0:
        current = int(get_system_state(conn, "consecutive_losses") or "0")
        set_system_state(conn, "consecutive_losses", str(current + 1))
    else:
        set_system_state(conn, "consecutive_losses", "0")

    # Update per-category cooldown counter (independent of global breaker)
    try:
        category = asset_to_category(trade.get("asset", ""))
        register_trade_close(conn, category, won=(pnl_usd > 0))
    except Exception as e:
        # Don't let cooldown bookkeeping break trade close
        print(f"[position_monitor] category cooldown update failed: {e}")

    # Update daily P&L
    daily_pnl = float(get_system_state(conn, "daily_pnl_usd") or "0")
    set_system_state(conn, "daily_pnl_usd", str(daily_pnl + pnl_usd))


def _update_stop_loss(exchange, symbol: str, direction: str, amount: float, new_sl: float):
    """Update stop loss on exchange. Cancel old SL and place new one."""
    try:
        # Cancel existing conditional orders
        exchange.cancel_all_orders(symbol, params={"stop": True})

        sl_side = "sell" if direction == "long" else "buy"
        exchange.create_order(
            symbol=symbol,
            type="market",
            side=sl_side,
            amount=amount,
            params={
                "stopLoss": {"triggerPrice": new_sl, "type": "market"},
                "reduceOnly": True,
                "triggerDirection": 2 if direction == "long" else 1,
            },
        )
    except Exception as e:
        print(f"Warning: Failed to update SL for {symbol}: {e}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Monitor open positions")
    parser.add_argument("--dry-run", action="store_true", help="Check without exchange connection")
    args = parser.parse_args()

    result = monitor_positions(dry_run=args.dry_run)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
