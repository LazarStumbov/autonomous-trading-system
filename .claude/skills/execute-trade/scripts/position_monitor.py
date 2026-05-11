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

from lib.db import (
    get_connection, init_db, get_open_trades, close_trade,
    set_system_state, get_system_state,
    log_partial_close, get_partial_closes, get_remaining_quantity,
)
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


def _tier_trigger_price(entry: float, sl: float, direction: str, r: float) -> float:
    """Return the absolute price for a tier defined in r-multiples of risk."""
    risk_distance = abs(entry - sl)
    sign = 1 if direction == "long" else -1
    return entry + sign * r * risk_distance


def _price_hit_tier(direction: str, current_price: float, trigger_price: float) -> bool:
    """Has current_price reached/passed the tier trigger in the trade's direction?"""
    return current_price >= trigger_price if direction == "long" else current_price <= trigger_price


def _apply_sl_action(action: str, entry: float, sl: float, direction: str, current_sl: float) -> float:
    """Compute the new SL after a tier fires. 'activate_trail' leaves SL alone
    (the existing progressive trailing logic will tighten it next cycle).

    Enforces SL monotonicity: SL only moves in the trade's favor. For longs
    the SL never moves down; for shorts it never moves up. Without this,
    a `breakeven` action could move SL backwards relative to a prior
    `lock_1r` or trailing transition.
    """
    risk_distance = abs(entry - sl)
    sign = 1 if direction == "long" else -1
    if action == "breakeven":
        proposed = entry
    elif action == "lock_1r":
        proposed = entry + sign * risk_distance
    else:
        return current_sl
    if direction == "long":
        return max(proposed, current_sl)
    return min(proposed, current_sl)


def _update_trade_sl(conn, trade_id: int, new_sl: float) -> None:
    conn.execute("UPDATE trades SET stop_loss=? WHERE id=?", (new_sl, trade_id))
    conn.commit()


def monitor_positions(dry_run: bool = False) -> dict:
    """Check all open positions and apply management rules.

    Returns:
        Dict with position statuses and actions taken.
    """
    config = load_risk_config()
    sl_config = config["market_trading"]["stop_loss"]
    tp_config = config["market_trading"]["take_profit"]
    tp_tiers_cfg = tp_config.get("tp_tiers", [])
    time_stop_hours = float(tp_config.get("time_stop_hours", 0))

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

                # Position closed on exchange but DB still shows open. The
                # exchange-side TP/SL fills aren't visible to us, so we log a
                # catch-all partial close for whatever quantity is still open
                # and finalize the trade row.
                pos_result["actions"].append("POSITION_CLOSED_ON_EXCHANGE")
                remaining_qty = get_remaining_quantity(
                    conn, trade["id"], float(trade.get("quantity") or 0)
                )
                if remaining_qty > 0:
                    sign = 1 if direction == "long" else -1
                    catchup_pnl = sign * (current_price - entry) * remaining_qty
                    log_partial_close(
                        conn, trade["id"], 97, "EXCHANGE_CLOSED",
                        current_price, remaining_qty, catchup_pnl,
                    )
                    if is_paper_trade(trade):
                        credit_paper_balance(
                            catchup_pnl,
                            reason=f"trade #{trade['id']} {asset} EXCHANGE_CLOSED",
                        )
                _finalize_trade(conn, trade, current_price)
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
        initial_qty = float(trade.get("quantity") or 0)
        sign = 1 if direction == "long" else -1
        partials_before = get_partial_closes(conn, trade_id)
        closed_tier_ids = {p["tier"] for p in partials_before}
        # Tier prices and SL transitions are r-multiples of the *original* risk
        # distance (entry → initial SL). The `stop_loss` column gets mutated by
        # breakeven/lock_1r/trailing transitions, so anchor to `initial_sl`
        # (immutable, set at trade open). If initial_sl is NULL on a legacy
        # trade AND any tier already fired, the live `sl` has been mutated
        # and we can't safely reconstruct r-math — skip the trade with a
        # warning. If no tiers have fired yet, `sl` is still pristine.
        if trade.get("initial_sl") is not None:
            original_sl = float(trade["initial_sl"])
        elif not partials_before:
            original_sl = sl
        else:
            pos_result["actions"].append(
                "SKIPPED: legacy trade with NULL initial_sl and existing partial closes; "
                "cannot reconstruct original risk distance"
            )
            results.append(pos_result)
            continue

        # ─── TP TIER PARTIAL CLOSES ─────────────────────────────────────────
        # For each configured tier we haven't fired yet, if r_moved cleared
        # its r threshold, close `close_pct` of the *initial* quantity, log
        # the partial close, credit paper P&L, and apply the configured
        # sl_action. In live mode the exchange placed these as conditional
        # orders at order time; here we mirror their fills into the DB.
        for idx, tier in enumerate(tp_tiers_cfg, start=1):
            if idx in closed_tier_ids:
                continue
            tier_r = float(tier["r"])
            tier_price = _tier_trigger_price(entry, original_sl, direction, tier_r)
            if not _price_hit_tier(direction, current_price, tier_price):
                continue
            close_pct = float(tier["close_pct"])
            qty_close = initial_qty * (close_pct / 100.0)
            if qty_close <= 0:
                continue
            tier_pnl = sign * (current_price - entry) * qty_close
            label = f"TP{idx}"
            log_partial_close(conn, trade_id, idx, label, current_price, qty_close, tier_pnl)
            closed_tier_ids.add(idx)
            pos_result["actions"].append(
                f"{label}_HIT: closed {close_pct}% ({qty_close:.6f}) @ {current_price} "
                f"r={tier_r:.1f} pnl=${tier_pnl:+.2f}"
            )
            if is_paper_trade(trade):
                credit_paper_balance(tier_pnl, reason=f"trade #{trade_id} {asset} {label}")

            # Apply SL action for this tier (uses original SL so lock_1r maps to
            # the entry-time +1R level, not the trailing SL).
            new_sl = _apply_sl_action(tier.get("sl_action", ""), entry, original_sl, direction, sl)
            if new_sl != sl:
                pos_result["actions"].append(f"SL_TRANSITION[{tier.get('sl_action')}]: {sl} -> {new_sl}")
                _update_trade_sl(conn, trade_id, new_sl)
                sl = new_sl
                if exchange and not dry_run:
                    remaining_after = get_remaining_quantity(conn, trade_id, initial_qty)
                    if remaining_after > 0:
                        _update_stop_loss(exchange, asset, direction, remaining_after, new_sl)

        # Recompute remaining qty after any tier fires
        remaining_qty = get_remaining_quantity(conn, trade_id, initial_qty)
        pos_result["remaining_qty"] = round(remaining_qty, 6)

        # ─── PROGRESSIVE TRAILING STOP (runner) ─────────────────────────────
        # Existing crypto-scaled tier table: as profit grows the trail tightens.
        trailing_activation = sl_config["trailing_stop_activation_pct"]
        base_trailing_distance = sl_config["trailing_stop_distance_pct"]
        prog_tiers = _load_progressive_tiers()
        pnl_pct = ((current_price - entry) / entry * 100) if direction == "long" else ((entry - current_price) / entry * 100)
        progressive = _progressive_distance(pnl_pct, prog_tiers)
        if progressive is not None:
            trailing_distance = progressive
            tier_label = f"PROGRESSIVE_TRAIL[{trailing_distance:.2f}%]"
        else:
            trailing_distance = base_trailing_distance
            tier_label = "TRAILING_STOP"

        if pnl_pct >= trailing_activation or progressive is not None:
            if direction == "long":
                trail_sl = current_price * (1 - trailing_distance / 100)
                if trail_sl > sl:
                    pos_result["actions"].append(f"{tier_label}: {sl} -> {trail_sl:.4f} (pnl={pnl_pct:.2f}%)")
                    _update_trade_sl(conn, trade_id, trail_sl)
                    sl = trail_sl
                    if exchange and not dry_run and remaining_qty > 0:
                        _update_stop_loss(exchange, asset, direction, remaining_qty, trail_sl)
            else:
                trail_sl = current_price * (1 + trailing_distance / 100)
                if trail_sl < sl:
                    pos_result["actions"].append(f"{tier_label}: {sl} -> {trail_sl:.4f} (pnl={pnl_pct:.2f}%)")
                    _update_trade_sl(conn, trade_id, trail_sl)
                    sl = trail_sl
                    if exchange and not dry_run and remaining_qty > 0:
                        _update_stop_loss(exchange, asset, direction, remaining_qty, trail_sl)

        # ─── TIME STOP ──────────────────────────────────────────────────────
        # If the trade has been open for `time_stop_hours` and hasn't reached
        # +1R, exit at market. Dead positions tie up the correlated-positions
        # cap and capital — kill them. tier=98 distinguishes from SL_HIT (99)
        # so the UNIQUE(trade_id, tier) constraint can't collapse the two.
        if time_stop_hours > 0 and remaining_qty > 0 and r_moved < 1.0:
            opened_at_raw = trade.get("opened_at") or trade.get("timestamp")
            try:
                opened_dt = datetime.fromisoformat(opened_at_raw.replace("Z", "+00:00")) if opened_at_raw else None
                if opened_dt and opened_dt.tzinfo is None:
                    opened_dt = opened_dt.replace(tzinfo=timezone.utc)
            except (ValueError, AttributeError):
                opened_dt = None
            if opened_dt is not None:
                age_hours = (datetime.now(timezone.utc) - opened_dt).total_seconds() / 3600.0
                if age_hours >= time_stop_hours:
                    ts_pnl = sign * (current_price - entry) * remaining_qty
                    log_partial_close(conn, trade_id, 98, "TIME_STOP", current_price, remaining_qty, ts_pnl)
                    pos_result["actions"].append(
                        f"TIME_STOP_HIT: age={age_hours:.1f}h >= {time_stop_hours}h, "
                        f"closed {remaining_qty:.6f} @ {current_price} pnl=${ts_pnl:+.2f}"
                    )
                    if is_paper_trade(trade):
                        credit_paper_balance(ts_pnl, reason=f"trade #{trade_id} {asset} TIME_STOP")
                    _finalize_trade(conn, trade, current_price)
                    pos_result["closed"] = True
                    results.append(pos_result)
                    continue

        # ─── SL HIT — finalize remaining ────────────────────────────────────
        sl_hit = (direction == "long" and current_price <= sl) or (direction == "short" and current_price >= sl)
        if sl_hit and remaining_qty > 0:
            sl_pnl = sign * (current_price - entry) * remaining_qty
            log_partial_close(conn, trade_id, 99, "SL_HIT", current_price, remaining_qty, sl_pnl)
            pos_result["actions"].append(
                f"STOP_LOSS_HIT: closed runner {remaining_qty:.6f} @ {current_price} pnl=${sl_pnl:+.2f}"
            )
            if is_paper_trade(trade):
                credit_paper_balance(sl_pnl, reason=f"trade #{trade_id} {asset} SL_HIT")
            _finalize_trade(conn, trade, current_price)
            pos_result["closed"] = True
            results.append(pos_result)
            continue

        # ─── All tiers + runner closed → finalize trade row ─────────────────
        if remaining_qty <= 0:
            pos_result["actions"].append("ALL_TIERS_CLOSED")
            _finalize_trade(conn, trade, current_price)
            pos_result["closed"] = True

        results.append(pos_result)

    conn.close()

    return {
        "status": "MONITORED",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "positions_checked": len(results),
        "positions": results,
    }


def _finalize_trade(conn, trade: dict, exit_price: float):
    """Mark a trade fully closed once all tiers + runner have exited.

    Aggregates pnl_usd from `partial_closes` (the source of truth for
    per-tier P&L) so the trade row reflects the *realized* total across
    every scale-out, not just the last close. Also rolls forward the daily
    P&L, consecutive-loss counter, and per-category cooldown bookkeeping.
    """
    entry = trade["entry_price"]
    qty = float(trade.get("quantity") or 0)
    direction = trade["direction"]
    trade_id = trade["id"]

    partials = get_partial_closes(conn, trade_id)
    pnl_usd = sum(float(p["pnl_usd"]) for p in partials)
    pnl_pct = (pnl_usd / (entry * qty)) * 100 if (entry and qty) else 0.0

    close_trade(conn, trade_id, exit_price, pnl_usd, pnl_pct)

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
        print(f"[position_monitor] category cooldown update failed: {e}")

    # Update daily P&L
    daily_pnl = float(get_system_state(conn, "daily_pnl_usd") or "0")
    set_system_state(conn, "daily_pnl_usd", str(daily_pnl + pnl_usd))
    print(f"[position_monitor] finalized trade #{trade_id} {direction}: total pnl=${pnl_usd:+.2f}")


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
