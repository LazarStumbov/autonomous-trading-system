"""Build complete order objects with entry, stop loss, take profit, and position sizing."""

import argparse
import json
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from lib.risk_engine import calculate_position_size, check_leverage, load_risk_config
from lib.constants import Direction


def compute_tp_tiers(entry: float, stop_loss: float, direction: str, tp_tiers_cfg: list) -> list[dict]:
    """Translate r-multiple tier config into absolute trigger prices.

    For each tier {r, close_pct, sl_action} returns the price the position
    should partial-close at. Long: entry + r*risk_distance. Short: entry - r*risk_distance.
    """
    risk_distance = abs(entry - stop_loss)
    if risk_distance == 0:
        return []
    sign = 1 if direction == "long" else -1
    out = []
    for tier in tp_tiers_cfg:
        r = float(tier["r"])
        price = entry + sign * r * risk_distance
        out.append({
            "r": r,
            "close_pct": float(tier["close_pct"]),
            "sl_action": tier.get("sl_action"),
            "trigger_price": round(price, 8),
        })
    return out


def build_order(
    asset: str,
    direction: str,
    capital: float,
    entry_price: float,
    stop_loss_price: float,
    take_profit_price: float,
    leverage: float = 3,
    confluence_score: float = 0,
    strategy: str = "manual",
    order_type: str = "market",
) -> dict:
    """Build a complete order with all parameters validated.

    Returns:
        Dict with order details ready for execution_engine.
    """
    # Validate direction
    if direction not in ("long", "short"):
        return {"error": f"Invalid direction: {direction}. Must be 'long' or 'short'"}

    # Validate SL/TP relative to direction
    if direction == "long":
        if stop_loss_price >= entry_price:
            return {"error": "Long SL must be below entry price"}
        if take_profit_price <= entry_price:
            return {"error": "Long TP must be above entry price"}
    else:
        if stop_loss_price <= entry_price:
            return {"error": "Short SL must be above entry price"}
        if take_profit_price >= entry_price:
            return {"error": "Short TP must be below entry price"}

    # Position sizing from risk engine
    sizing = calculate_position_size(capital, entry_price, stop_loss_price)
    if "error" in sizing:
        return sizing

    # Leverage validation (per-asset cap when applicable)
    lev_check = check_leverage(leverage, confluence_score, asset_symbol=asset)
    approved_leverage = lev_check["approved"]

    # Calculate notional value
    position_size = sizing["position_size"]
    notional = position_size * entry_price
    margin_required = notional / approved_leverage

    # Risk-reward ratio
    risk_distance = abs(entry_price - stop_loss_price)
    reward_distance = abs(take_profit_price - entry_price)
    rr_ratio = reward_distance / risk_distance if risk_distance > 0 else 0

    # Multi-tier TP: compute tier trigger prices from config (entry + r*risk_distance).
    # Falls back to a single-tier proxy if config is missing the new structure.
    cfg = load_risk_config()
    tp_cfg = cfg.get("market_trading", {}).get("take_profit", {})
    tier_defs = tp_cfg.get("tp_tiers", [])
    tp_tiers = compute_tp_tiers(entry_price, stop_loss_price, direction, tier_defs)

    order = {
        "asset": asset,
        "direction": direction,
        "order_type": order_type,
        "entry_price": entry_price,
        "stop_loss": stop_loss_price,
        "take_profit": take_profit_price,
        "tp_tiers": tp_tiers,
        "position_size": round(position_size, 6),
        "notional_usd": round(notional, 2),
        "margin_required_usd": round(margin_required, 2),
        "leverage": approved_leverage,
        "risk_usd": sizing["risk_usd"],
        "risk_pct": sizing["risk_pct"],
        "rr_ratio": round(rr_ratio, 2),
        "confluence_score": confluence_score,
        "strategy": strategy,
        "sl_distance_pct": round(risk_distance / entry_price * 100, 2),
        "tp_distance_pct": round(reward_distance / entry_price * 100, 2),
    }

    return order


def main():
    parser = argparse.ArgumentParser(description="Build a trade order")
    parser.add_argument("--asset", required=True, help="Trading pair e.g. BTC/USDT:USDT")
    parser.add_argument("--direction", required=True, choices=["long", "short"])
    parser.add_argument("--capital", type=float, default=500, help="Account capital USD")
    parser.add_argument("--entry", type=float, required=True, help="Entry price")
    parser.add_argument("--sl", type=float, required=True, help="Stop loss price")
    parser.add_argument("--tp", type=float, required=True, help="Take profit price")
    parser.add_argument("--leverage", type=float, default=3, help="Requested leverage")
    parser.add_argument("--confluence", type=float, default=0, help="Confluence score 0-100")
    parser.add_argument("--strategy", default="manual", help="Strategy name")
    parser.add_argument("--size", type=float, help="Override position size")

    args = parser.parse_args()

    order = build_order(
        asset=args.asset,
        direction=args.direction,
        capital=args.capital,
        entry_price=args.entry,
        stop_loss_price=args.sl,
        take_profit_price=args.tp,
        leverage=args.leverage,
        confluence_score=args.confluence,
        strategy=args.strategy,
    )

    if args.size:
        order["position_size"] = args.size
        order["notional_usd"] = round(args.size * args.entry, 2)
        order["margin_required_usd"] = round(order["notional_usd"] / order["leverage"], 2)

    print(json.dumps(order, indent=2))


if __name__ == "__main__":
    main()
