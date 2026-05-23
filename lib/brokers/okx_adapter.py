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
    """Load from environment, supporting dotenv files.

    Bug fix 2026-05: the previous version did
        val = os.environ.get(key, fallback)
        if not val: ...
    which short-circuited when fallback was truthy (e.g. 'global'), so the
    .env file was never consulted. Now we explicitly use an empty default
    for os.environ and only apply the caller's fallback at the very end.
    """
    val = os.environ.get(key, "")
    if not val:
        try:
            from dotenv import dotenv_values  # type: ignore
            env = dotenv_values(os.path.join(PROJECT_ROOT, ".env"))
            val = env.get(key, "") or ""
        except Exception:
            pass
    return val or fallback


def get_exchange(demo: Optional[bool] = None):  # type: ignore
    """Return an authenticated ccxt OKX instance.

    demo=True  → OKX paper trading (virtual funds, x-simulated-trading header)
    demo=None  → reads OKX_DEMO env var (defaults to True for safety)
    demo=False → live trading (REAL MONEY — only after paper window passes)

    OKX has two ccxt variants:
      - ccxt.okx     → global okx.com (default)
      - ccxt.myokx   → EU subsidiary (my.okx.com), MiCA-licensed for EEA users

    EU accounts have keys registered against the EU entity ONLY. Calling
    ccxt.okx with EU keys returns 50119 "API key doesn't exist". Set
    OKX_REGION=eu to route through ccxt.myokx instead. Default is 'global'.
    """
    import ccxt  # type: ignore

    api_key = _env("OKX_API_KEY")
    secret = _env("OKX_SECRET_KEY")
    passphrase = _env("OKX_PASSPHRASE")
    region = _env("OKX_REGION", "global").lower().strip()

    if demo is None:
        demo = _env("OKX_DEMO", "true").lower().strip() == "true"

    exchange_cls = ccxt.myokx if region in ("eu", "eea", "myokx") else ccxt.okx

    exchange = exchange_cls(
        {
            "apiKey": api_key,
            "secret": secret,
            "password": passphrase,  # OKX calls it 'password' in ccxt
            "options": {
                "defaultType": "swap",  # perpetual swaps by default
            },
            "enableRateLimit": True,
        }
    )
    # OKX demo trading uses the x-simulated-trading: 1 header. ccxt sets it
    # via set_sandbox_mode(True). The previous code set options.demo, which
    # ccxt does NOT read — every request hit the live endpoint and 50119'd
    # demo keys.
    if demo:
        exchange.set_sandbox_mode(True)
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
        """Return total trading-account equity in USD.

        Resolution order:
          1. OKX unified account: `info.data[0].totalEq` is the USD-equivalent
             of ALL assets (BTC + USDC + USD + EUR + ...) at current marks.
             This is what OKX itself uses to size positions, so it's the
             right field for risk-engine bankroll calculations.
          2. Plain USDT balance: for classic non-unified swap accounts that
             hold only USDT.
          3. 0 — safe default; risk_engine will refuse to size trades.

        Note: the old code did `bal.get("USDT") or bal.get("total", {})` which
        returned the whole `total` dict (a Mapping, not a number) when USDT
        was absent, and float() silently turned that into 0. This patch is
        why a $159k virtual account was being read as $0.
        """
        bal = self._exchange.fetch_balance({"type": "swap"})
        # Path 1: unified-account totalEq (preferred for OKX)
        try:
            info = bal.get("info") or {}
            data = info.get("data") or []
            if data and isinstance(data, list):
                total_eq = data[0].get("totalEq")
                if total_eq not in (None, "", "0"):
                    return float(total_eq)
        except (KeyError, ValueError, TypeError):
            pass
        # Path 2: plain USDT
        usdt = bal.get("USDT")
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
        """Smoke-test API credentials. Returns {'ok': True/False, 'balance': ...}.

        `demo` flag is read from the sandbox header (set by ccxt.set_sandbox_mode),
        not from `options.demo` (which ccxt does not interpret).
        """
        try:
            bal = self.fetch_balance_usd()
            is_demo = bool(getattr(self._exchange, "headers", {}).get("x-simulated-trading"))
            return {"ok": True, "balance_usd": bal, "demo": is_demo,
                    "venue": type(self._exchange).__name__}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def auth_test(self) -> tuple[bool, str]:
        """Alias matching the AlpacaAdapter/OandaAdapter signature so the
        router's auth_test_all() works consistently across all adapters."""
        r = self.test_auth()
        if r.get("ok"):
            mode = "demo" if r.get("demo") else "live"
            venue = r.get("venue", "okx")
            return True, f"{venue} {mode} ok, balance=${r.get('balance_usd', '?')}"
        return False, r.get("error", "okx auth failed")
