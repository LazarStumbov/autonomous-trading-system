"""Bybit broker adapter — production crypto path.

Wraps the existing ccxt-based helpers in
`.claude/skills/execute-trade/scripts/bybit_api.py` to satisfy the
`BrokerAdapter` interface. Crypto perp + spot only.
"""

from __future__ import annotations

import os
import sys
from typing import Optional

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# bybit_api lives inside the execute-trade skill folder; add it to path on demand
_BYBIT_API_DIR = os.path.join(PROJECT_ROOT, ".claude", "skills", "execute-trade", "scripts")
if _BYBIT_API_DIR not in sys.path:
    sys.path.insert(0, _BYBIT_API_DIR)

from lib.constants import AssetClass
from lib.brokers.base import BrokerAdapter, Quote, Position, OrderResult


class BybitAdapter(BrokerAdapter):
    name = "bybit"
    supported_classes = (AssetClass.CRYPTO_PERP, AssetClass.CRYPTO_SPOT)
    trading_hours = "24/7"

    def __init__(self, testnet: Optional[bool] = None):
        try:
            import bybit_api  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                f"Could not import bybit_api helpers from {_BYBIT_API_DIR}: {e}"
            ) from e
        self._helpers = bybit_api
        self._exchange = bybit_api.get_exchange(testnet=testnet)

    # ── Market data ──────────────────────────────────────────────────────────
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 200) -> list[list[float]]:
        return self._exchange.fetch_ohlcv(symbol, timeframe, limit=limit)

    def fetch_quote(self, symbol: str) -> Quote:
        t = self._helpers.get_ticker(self._exchange, symbol)
        return Quote(
            symbol=symbol,
            last=float(t.get("last") or 0),
            bid=t.get("bid"),
            ask=t.get("ask"),
            timestamp=str(t.get("timestamp")) if t.get("timestamp") else None,
        )

    # ── Account ──────────────────────────────────────────────────────────────
    def fetch_balance_usd(self) -> float:
        bal = self._helpers.get_balance(self._exchange)
        return float(bal.get("total") or 0)

    def fetch_positions(self) -> list[Position]:
        raw = self._helpers.get_positions(self._exchange)
        out = []
        for p in raw:
            out.append(
                Position(
                    symbol=p["symbol"],
                    qty=float(p.get("size") or 0),
                    side=p.get("side") or "long",
                    entry_price=float(p.get("entry_price") or 0),
                    mark_price=float(p.get("mark_price") or 0),
                    unrealized_pnl_usd=float(p.get("unrealized_pnl") or 0),
                    leverage=float(p.get("leverage") or 1),
                )
            )
        return out

    # ── Trading ──────────────────────────────────────────────────────────────
    def place_market_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        *,
        leverage: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        reduce_only: bool = False,
    ) -> OrderResult:
        params: dict = {"reduceOnly": reduce_only}
        if stop_loss is not None:
            params["stopLoss"] = {"triggerPrice": stop_loss, "type": "market"}
        if take_profit is not None:
            params["takeProfit"] = {"triggerPrice": take_profit, "type": "market"}
        try:
            if leverage:
                self._helpers.set_leverage(self._exchange, symbol, int(leverage))
            order = self._exchange.create_order(
                symbol=symbol, type="market", side=side, amount=qty, params=params
            )
            return OrderResult(ok=True, order_id=order.get("id"), raw=order)
        except Exception as e:
            return OrderResult(ok=False, order_id=None, error=str(e))

    def cancel_all(self, symbol: str) -> bool:
        try:
            self._exchange.cancel_all_orders(symbol)
            return True
        except Exception as e:
            print(f"[bybit] cancel_all failed for {symbol}: {e}")
            return False
