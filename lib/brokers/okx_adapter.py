"""OKX broker adapter — primary crypto derivatives path.

OKX replaces Bybit as the execution venue after Bybit EU restricted
perpetual/derivative trading for retail clients under ESMA rules.

OKX supports:
  - USDT-margined perpetual swaps (CRYPTO_PERP)
  - Spot trading (CRYPTO_SPOT)
  - Demo trading environment (demo=True in options)
  - Full ccxt integration including setLeverage, set_margin_mode

Symbol format expected by this adapter: "BTC/USDT:USDT"
  - ccxt unified symbol for OKX USDT perpetual swap
  - Maps to OKX instrument ID: BTC-USDT-SWAP

Demo / testnet:
  Set OKX_DEMO=true in .env OR pass demo=True to constructor.
  OKX demo uses the same API as live but with virtual funds.
  Create demo API keys at: https://www.okx.com/account/demo-mode/api-management

Environment variables:
  OKX_API_KEY      — required
  OKX_SECRET_KEY   — required
  OKX_PASSPHRASE   — required (OKX requires a passphrase for all API keys)
  OKX_DEMO         — "true" to use demo/testnet environment
"""

from __future__ import annotations

import os
import sys
from typing import Optional

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from lib.constants import AssetClass
from lib.brokers.base import BrokerAdapter, Quote, Position, OrderResult


def _env(key: str, fallback: str = "") -> str:
    """Load from environment, supporting dotenv files."""
    val = os.environ.get(key, fallback)
    if not val:
        try:
            from dotenv import dotenv_values  # type: ignore
            env = dotenv_values(os.path.join(PROJECT_ROOT, ".env"))
            val = env.get(key, fallback)
        except Exception:
            pass
    return val


def get_exchange(demo: Optional[bool] = None) -> "ccxt.okx":  # type: ignore
    """Return an authenticated ccxt.okx instance.

    demo=True  → OKX paper trading (virtual funds, same API endpoint)
    demo=None  → reads OKX_DEMO env var (defaults to True for safety)
    demo=False → live trading (REAL MONEY — only set after paper window done)
    """
    import ccxt  # type: ignore

    api_key = _env("OKX_API_KEY")
    secret = _env("OKX_SECRET_KEY")
    passphrase = _env("OKX_PASSPHRASE")

    if demo is None:
        demo = _env("OKX_DEMO", "true").lower().strip() == "true"

    exchange = ccxt.okx(
        {
            "apiKey": api_key,
            "secret": secret,
            "password": passphrase,  # OKX calls it 'password' in ccxt
            "options": {
                "defaultType": "swap",  # perpetual swaps by default
                "demo": demo,           # True = paper trading / demo account
            },
            "enableRateLimit": True,
        }
    )
    return exchange


class OkxAdapter(BrokerAdapter):
    """OKX broker adapter for crypto perpetual swaps and spot."""

    name = "okx"
    supported_classes = (AssetClass.CRYPTO_PERP, AssetClass.CRYPTO_SPOT)
    trading_hours = "24/7"

    def __init__(self, demo: Optional[bool] = None):
        self._exchange = get_exchange(demo=demo)

    # ── Market data ──────────────────────────────────────────────────────────

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 200) -> list[list[float]]:
        """Fetch OHLCV bars. Returns [[ts, open, high, low, close, volume], ...]."""
        return self._exchange.fetch_ohlcv(symbol, timeframe, limit=limit)

    def fetch_quote(self, symbol: str) -> Quote:
        ticker = self._exchange.fetch_ticker(symbol)
        return Quote(
            symbol=symbol,
            last=float(ticker.get("last") or 0),
            bid=ticker.get("bid"),
            ask=ticker.get("ask"),
            timestamp=str(ticker.get("timestamp")) if ticker.get("timestamp") else None,
        )

    # ── Account ──────────────────────────────────────────────────────────────

    def fetch_balance_usd(self) -> float:
        """Return USDT balance (total equity in the trading account)."""
        bal = self._exchange.fetch_balance({"type": "swap"})
        # ccxt normalizes balance under 'USDT' key
        usdt = bal.get("USDT") or bal.get("total", {})
        if isinstance(usdt, dict):
            return float(usdt.get("total") or 0)
        return float(usdt or 0)

    def fetch_positions(self) -> list[Position]:
        """Return all open positions."""
        raw = self._exchange.fetch_positions()
        out = []
        for p in raw:
            if not p.get("contracts") or float(p.get("contracts") or 0) == 0:
                continue  # skip empty/closed positions
            side = "long" if p.get("side") == "long" else "short"
            out.append(
                Position(
                    symbol=p["symbol"],
                    qty=float(p.get("contracts") or 0),
                    side=side,
                    entry_price=float(p.get("entryPrice") or 0),
                    mark_price=float(p.get("markPrice") or 0),
                    unrealized_pnl_usd=float(p.get("unrealizedPnl") or 0),
                    leverage=float(p.get("leverage") or 1),
                )
            )
        return out

    # ── Trading ──────────────────────────────────────────────────────────────

    def place_market_order(
        self,
        symbol: str,
        side: str,                  # "buy" (long) or "sell" (short)
        qty: float,
        *,
        leverage: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        reduce_only: bool = False,
    ) -> OrderResult:
        """Place a market order on OKX. Sets leverage and attaches SL/TP."""
        try:
            # Set leverage before placing the order
            if leverage:
                margin_mode = "cross"  # cross margin — can be overridden via config
                self._exchange.set_leverage(int(leverage), symbol, {"mgnMode": margin_mode})

            params: dict = {"tdMode": "cross"}  # cross margin
            if reduce_only:
                params["reduceOnly"] = True

            # Attach SL/TP as attached orders (OKX algo orders)
            if stop_loss is not None:
                params["stopLoss"] = {
                    "triggerPrice": str(stop_loss),
                    "orderPrice": "-1",  # market order on trigger
                    "triggerPxType": "last",
                }
            if take_profit is not None:
                params["takeProfit"] = {
                    "triggerPrice": str(take_profit),
                    "orderPrice": "-1",
                    "triggerPxType": "last",
                }

            order = self._exchange.create_order(
                symbol=symbol,
                type="market",
                side=side,
                amount=qty,
                params=params,
            )
            return OrderResult(ok=True, order_id=order.get("id"), raw=order)

        except Exception as e:
            return OrderResult(ok=False, order_id=None, error=str(e))

    def cancel_all(self, symbol: str) -> bool:
        """Cancel all open orders for a symbol."""
        try:
            self._exchange.cancel_all_orders(symbol)
            return True
        except Exception as e:
            print(f"[okx] cancel_all failed for {symbol}: {e}")
            return False

    # ── Auth test ─────────────────────────────────────────────────────────────

    def test_auth(self) -> dict:
        """Smoke-test API credentials. Returns {'ok': True/False, 'balance': ...}"""
        try:
            bal = self.fetch_balance_usd()
            return {"ok": True, "balance_usd": bal, "demo": self._exchange.options.get("demo")}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def auth_test(self) -> tuple[bool, str]:
        """Alias matching the AlpacaAdapter/OandaAdapter signature so the
        router's auth_test_all() works consistently across all adapters."""
        r = self.test_auth()
        if r.get("ok"):
            mode = "demo" if r.get("demo") else "live"
            return True, f"okx {mode} ok, balance=${r.get('balance_usd', '?')}"
        return False, r.get("error", "okx auth failed")
