"""Execute trades on OKX. Places entry + SL + TP orders, logs everything to DB."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from lib.db import get_connection, init_db, log_trade, log_signal
from lib.constants import Pillar, TradeStatus
from lib.paper_engine import is_paper_mode, simulate_order, broker_mode

# OKX broker adapter — routed through the clean BrokerAdapter interface
from lib.brokers.okx_adapter import get_exchange, OkxAdapter as _OkxAdapter

def get_balance(exchange) -> dict:
    """Compatibility shim: return {'free': float, 'total': float} from OKX balance."""
    try:
        raw = exchange.fetch_balance({"type": "swap"})
        usdt = raw.get("USDT") or {}
        if isinstance(usdt, dict):
            return {"free": float(usdt.get("free") or 0), "total": float(usdt.get("total") or 0)}
        return {"free": float(usdt or 0), "total": float(usdt or 0)}
    except Exception:
        return {"free": 0.0, "total": 0.0}

def set_leverage(exchange, symbol: str, leverage: int) -> None:
    exchange.set_leverage(leverage, symbol, {"mgnMode": "cross"})

def set_margin_mode(exchange, symbol: str, mode: str) -> None:
    try:
        exchange.set_margin_mode(mode, symbol)
    except Exception:
        pass  # OKX may reject if mode already set

def get_ticker(exchange, symbol: str) -> dict:
    return exchange.fetch_ticker(symbol)


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

    # ─── Broker dispatch (P1: BROKER_MODE single-point switch) ───────────
    # synthetic → simulate_order against public price feed (legacy paper path)
    # demo      → real OKX demo trading endpoint, virtual capital, real fills
    # live      → real OKX, real money (gated by lib.live_readiness elsewhere)
    mode = broker_mode()

    if mode == "synthetic":
        sim = simulate_order(order)
        # Mirror simulated fields onto our result and DB-log it
        result["status"] = sim["status"]
        result["orders"] = sim["orders"]
        result["errors"] = sim.get("errors", [])
        result["paper"] = True
        result["broker_mode"] = "synthetic"
        result["fill_price"] = sim.get("fill_price")
        result["slippage_pct"] = sim.get("slippage_pct")
        # Use the actual fill price for DB logging — that's where the trade
        # really opens, not the intended entry_price.
        if sim["status"] == "EXECUTED" and sim.get("fill_price"):
            order = {**order, "entry_price": sim["fill_price"]}
        _log_to_db(order, result)
        return result

    # mode == 'demo' or 'live'. OKX adapter handles the URL switching via the
    # OKX_DEMO env var (already implemented at lib/brokers/okx_adapter.py:69).
    # When BROKER_MODE=demo we force OKX_DEMO=true for this call regardless of
    # what the env says — defensive coupling so we cannot accidentally fire a
    # live order from a demo-tagged container.
    if mode == "demo":
        os.environ["OKX_DEMO"] = "true"
    elif mode == "live":
        # Live mode requires explicit live keys; OKX_DEMO must be false.
        if os.environ.get("OKX_DEMO", "true").lower() != "false":
            result["status"] = "REJECTED"
            result["errors"].append(
                "BROKER_MODE=live but OKX_DEMO is not explicitly set to 'false'"
            )
            return result

    result["broker_mode"] = mode
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

        # Place take-profit orders. If multi-tier config is present, place one
        # conditional order per tier with quantity = size * close_pct/100.
        # Otherwise fall back to a single TP at the legacy `tp` price.
        tp_tiers = order.get("tp_tiers") or []
        if tp_tiers:
            tp_orders = []
            for idx, tier in enumerate(tp_tiers, start=1):
                tier_qty = size * (tier["close_pct"] / 100.0)
                tier_price = tier["trigger_price"]
                try:
                    tp_order = exchange.create_order(
                        symbol=asset,
                        type="market",
                        side=sl_side,
                        amount=tier_qty,
                        params={
                            "takeProfit": {"triggerPrice": tier_price, "type": "market"},
                            "reduceOnly": True,
                            "triggerDirection": 1 if direction == "long" else 2,
                        },
                    )
                    tp_orders.append({
                        "tier": idx,
                        "id": tp_order.get("id", ""),
                        "trigger": tier_price,
                        "qty": tier_qty,
                        "close_pct": tier["close_pct"],
                        "r": tier["r"],
                    })
                except Exception as e:
                    result["errors"].append(f"TP{idx} placement failed: {e}")
            result["orders"]["take_profit_tiers"] = tp_orders
        else:
            tp_order = exchange.create_order(
                symbol=asset,
                type="market",
                side=sl_side,
                amount=size,
                params={
                    "takeProfit": {"triggerPrice": tp, "type": "market"},
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

    # Capture chart screenshot (best-effort — never blocks execution)
    if result["status"] in ("EXECUTED", "DRY_RUN"):
        chart_url = _try_capture_screenshot(order)
        if chart_url:
            order.setdefault("reasoning", "")
            order["reasoning"] = (order["reasoning"] + f"\nchart_url:{chart_url}").lstrip()

    # Log to database
    _log_to_db(order, result)

    return result


def _try_capture_screenshot(order: dict) -> str | None:
    """Best-effort chart screenshot via TradingView MCP bridge.

    Saves to data/trades/<trade_id_or_timestamp>/entry.png. Never raises —
    failure to screenshot must not block trade execution. Returns the saved
    path or None.

    The actual MCP call is delegated to a callable in os.environ if present,
    otherwise this is a no-op. Real wiring lives in the Claude agent layer
    that has access to mcp__tradingview__* tools.
    """
    try:
        import os
        from pathlib import Path
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_dir = Path(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))) / "data" / "trades" / ts
        out_dir.mkdir(parents=True, exist_ok=True)
        save_path = str(out_dir / "entry.png")
        # Hook stub: callers running inside Claude Code can monkey-patch
        # `_screenshot_hook` to wire the real MCP bridge.
        hook = globals().get("_screenshot_hook")
        if callable(hook):
            return hook(order["asset"], save_path) or save_path
        # Otherwise leave a placeholder marker so post-trade tooling knows
        # a screenshot was *requested* but not captured (e.g. running on Modal).
        Path(save_path + ".pending").touch()
        return save_path + ".pending"
    except Exception:
        return None


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
            initial_sl=order["stop_loss"],
            take_profit=order["take_profit"],
            status=TradeStatus.OPEN if result["status"] in ("EXECUTED", "DRY_RUN") else TradeStatus.CANCELLED,
            strategy=order.get("strategy", ""),
            confluence_score=order.get("confluence_score", 0),
            signals_json=json.dumps(order.get("signals", [])),
            reasoning=order.get("reasoning", ""),
            risk_check_result=result["status"],
            opened_at=datetime.now(timezone.utc).isoformat(),
            broker=(
                "paper" if result.get("paper")
                else ("okx_demo" if result.get("dry_run") else "okx")
            ),
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
