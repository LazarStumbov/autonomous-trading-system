"""Execute trades on Bybit. Places entry + SL + TP orders, logs everything to DB."""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from lib.db import get_connection, init_db, log_trade, log_signal
from lib.constants import Pillar, TradeStatus

# Import sibling module
sys.path.insert(0, os.path.dirname(__file__))
from bybit_api import get_exchange, get_balance, set_leverage, set_margin_mode, get_ticker


def execute_order(order: dict, dry_run: bool = False) -> dict:
    """Execute a fully-built order on Bybit.

    Args:
        order: Order dict from order_builder.build_order()
        dry_run: If True, simulate without placing real orders

    Returns:
        Dict with execution result, order IDs, and database trade ID
    """
    asset = order["asset"]
    direction = order["direction"]
    size = order["position_size"]
    leverage = int(order["leverage"])
    sl = order["stop_loss"]
    tp = order["take_profit"]
    entry_price = order["entry_price"]
    order_type = order.get("order_type", "market")

    result = {
        "asset": asset,
        "direction": direction,
        "size": size,
        "leverage": leverage,
        "dry_run": dry_run,
        "orders": {},
        "errors": [],
    }

    if dry_run:
        result["status"] = "DRY_RUN"
        result["orders"] = {
            "entry": {"id": "dry_run_entry", "status": "simulated"},
            "stop_loss": {"id": "dry_run_sl", "trigger": sl},
            "take_profit": {"id": "dry_run_tp", "trigger": tp},
        }
        # Log to database even in dry run
        _log_to_db(order, result)
        return result

    exchange = get_exchange()

    # Pre-flight: check balance
    balance = get_balance(exchange)
    margin_needed = order["margin_required_usd"]
    if balance["free"] < margin_needed:
        result["status"] = "REJECTED"
        result["errors"].append(
            f"Insufficient balance: ${balance['free']:.2f} free, need ${margin_needed:.2f}"
        )
        return result

    try:
        # Set leverage and margin mode
        set_margin_mode(exchange, asset, "isolated")
        set_leverage(exchange, asset, leverage)

        # Place entry order
        side = "buy" if direction == "long" else "sell"

        if order_type == "market":
            entry_order = exchange.create_order(
                symbol=asset,
                type="market",
                side=side,
                amount=size,
            )
        else:
            entry_order = exchange.create_order(
                symbol=asset,
                type="limit",
                side=side,
                amount=size,
                price=entry_price,
            )

        result["orders"]["entry"] = {
            "id": entry_order["id"],
            "status": entry_order["status"],
            "filled": entry_order.get("filled", 0),
            "avg_price": entry_order.get("average", entry_price),
        }

        # Place stop loss (conditional order)
        sl_side = "sell" if direction == "long" else "buy"
        sl_order = exchange.create_order(
            symbol=asset,
            type="market",
            side=sl_side,
            amount=size,
            params={
                "stopLoss": {
                    "triggerPrice": sl,
                    "type": "market",
                },
                "reduceOnly": True,
                "triggerDirection": 2 if direction == "long" else 1,  # 2=fall below, 1=rise above
            },
        )
        result["orders"]["stop_loss"] = {
            "id": sl_order.get("id", ""),
            "trigger": sl,
        }

        # Place take profit (conditional order)
        tp_order = exchange.create_order(
            symbol=asset,
            type="market",
            side=sl_side,
            amount=size,
            params={
                "takeProfit": {
                    "triggerPrice": tp,
                    "type": "market",
                },
                "reduceOnly": True,
                "triggerDirection": 1 if direction == "long" else 2,
            },
        )
        result["orders"]["take_profit"] = {
            "id": tp_order.get("id", ""),
            "trigger": tp,
        }

        result["status"] = "EXECUTED"

    except Exception as e:
        result["status"] = "ERROR"
        result["errors"].append(str(e))

    # Log to database
    _log_to_db(order, result)

    return result


def _log_to_db(order: dict, result: dict):
    """Log the trade attempt to the database."""
    try:
        init_db()
        conn = get_connection()

        trade_id = log_trade(
            conn,
            pillar=Pillar.MARKET,
            asset=order["asset"],
            direction=order["direction"],
            entry_price=order["entry_price"],
            quantity=order["position_size"],
            leverage=order["leverage"],
            stop_loss=order["stop_loss"],
            take_profit=order["take_profit"],
            status=TradeStatus.OPEN if result["status"] in ("EXECUTED", "DRY_RUN") else TradeStatus.CANCELLED,
            strategy=order.get("strategy", ""),
            confluence_score=order.get("confluence_score", 0),
            signals_json=json.dumps(order.get("signals", [])),
            reasoning=order.get("reasoning", ""),
            risk_check_result=result["status"],
            opened_at=datetime.now(timezone.utc).isoformat(),
            broker="bybit_testnet" if result.get("dry_run") else "bybit",
        )

        result["trade_id"] = trade_id
        conn.close()
    except Exception as e:
        result["db_error"] = str(e)


def main():
    parser = argparse.ArgumentParser(description="Execute a trade order on Bybit")
    parser.add_argument("--order-json", required=True, help="JSON string of order from order_builder")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without placing real orders")

    args = parser.parse_args()
    order = json.loads(args.order_json)

    result = execute_order(order, dry_run=args.dry_run)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
