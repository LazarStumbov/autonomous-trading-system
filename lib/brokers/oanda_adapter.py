"""OANDA fxTrade adapter — forex spot, practice or live.

Pure-REST against OANDA v20 endpoints:
  Practice: https://api-fxpractice.oanda.com
  Live:     https://api-fxtrade.oanda.com

Auth is a single bearer token (Personal Access Token). No SDK — keeps the
Modal image slim. All API docs at https://developer.oanda.com/rest-live-v20/.

Env vars:
  OANDA_API_TOKEN    — Personal Access Token from the OANDA account portal
  OANDA_ACCOUNT_ID   — e.g. '101-001-12345678-001'  (from the portal)
  OANDA_PRACTICE     — 'true' (default) | 'false'

Symbol convention: OANDA uses underscore form ('EUR_USD'). The system's
canonical form is 'EURUSD'. _to_oanda() normalizes; everything else stays
in the canonical form so confluence engine / risk gate / DB rows match.

Quantity convention: OANDA quotes positions in *units of the base currency*.
A "1 lot" forex trade is 100,000 units. For paper at $500 we'll typically be
trading 1,000–10,000 units (micro/mini lots). The position_sizer in the
existing risk_engine already returns notional USD; we convert at order time
using the current quote.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Optional

from lib.constants import AssetClass
from lib.brokers.base import BrokerAdapter, Quote, Position, OrderResult


PRACTICE_BASE = "https://api-fxpractice.oanda.com"
LIVE_BASE = "https://api-fxtrade.oanda.com"


def _env(name: str, default: str = "") -> str:
    val = os.environ.get(name)
    if val:
        return val
    try:
        from dotenv import dotenv_values  # type: ignore
        env = dotenv_values(os.path.join(
            os.path.dirname(__file__), "..", "..", ".env"
        ))
        return env.get(name, default) or default
    except Exception:
        return default


def _to_oanda(symbol: str) -> str:
    """'EURUSD' -> 'EUR_USD'. Pass-through if already underscore form."""
    s = (symbol or "").upper()
    if "_" in s:
        return s
    if len(s) == 6:
        return f"{s[:3]}_{s[3:]}"
    return s


def _from_oanda(symbol: str) -> str:
    """'EUR_USD' -> 'EURUSD'."""
    return (symbol or "").replace("_", "").upper()


class OandaAdapter(BrokerAdapter):
    name = "oanda"
    supported_classes = (AssetClass.FOREX_SPOT,)
    # FX market: Sun 22:00 UTC → Fri 22:00 UTC. Practice account follows live hours.
    trading_hours = "Sun 22:00 UTC → Fri 22:00 UTC"

    def __init__(self, practice: Optional[bool] = None):
        if practice is None:
            practice = _env("OANDA_PRACTICE", "true").lower().strip() != "false"
        self._practice = practice
        self._base = PRACTICE_BASE if practice else LIVE_BASE
        self._token = _env("OANDA_API_TOKEN")
        self._account = _env("OANDA_ACCOUNT_ID")

    # ── HTTP plumbing ────────────────────────────────────────────────────────

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept-Datetime-Format": "RFC3339",
        }

    def _request(self, method: str, path: str, *,
                 params: Optional[dict] = None, body: Optional[dict] = None,
                 timeout: float = 15.0) -> dict | list:
        url = self._base + path
        if params:
            url = url + "?" + urllib.parse.urlencode(params)
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=method, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                if not raw:
                    return {}
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            body_str = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else ""
            raise RuntimeError(f"oanda {method} {path} → {e.code}: {body_str[:300]}") from e

    # ── Market data ──────────────────────────────────────────────────────────

    def fetch_quote(self, symbol: str) -> Quote:
        inst = _to_oanda(symbol)
        r = self._request("GET", f"/v3/accounts/{self._account}/pricing",
                          params={"instruments": inst})
        prices = r.get("prices") or []
        if not prices:
            return Quote(symbol=symbol, last=0)
        p = prices[0]
        bids = p.get("bids") or []
        asks = p.get("asks") or []
        bid = float(bids[0]["price"]) if bids else 0
        ask = float(asks[0]["price"]) if asks else 0
        last = (bid + ask) / 2 if bid and ask else (bid or ask)
        return Quote(symbol=symbol, last=last, bid=bid or None, ask=ask or None,
                     timestamp=p.get("time"))

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 200) -> list[list[float]]:
        """Returns [[ts_ms, open, high, low, close, volume], ...]."""
        tf_map = {"1m": "M1", "5m": "M5", "15m": "M15", "30m": "M30",
                  "1h": "H1", "4h": "H4", "1d": "D"}
        gran = tf_map.get(timeframe, "H1")
        inst = _to_oanda(symbol)
        r = self._request("GET", f"/v3/instruments/{inst}/candles",
                          params={"granularity": gran, "count": min(limit, 5000), "price": "M"})
        candles = r.get("candles") or []
        out = []
        for c in candles:
            if not c.get("complete"):
                continue
            mid = c.get("mid") or {}
            try:
                ts = datetime.fromisoformat(c["time"].replace("Z", "+00:00"))
                ts_ms = int(ts.timestamp() * 1000)
            except (ValueError, KeyError):
                continue
            out.append([
                ts_ms,
                float(mid.get("o") or 0),
                float(mid.get("h") or 0),
                float(mid.get("l") or 0),
                float(mid.get("c") or 0),
                float(c.get("volume") or 0),
            ])
        return out

    # ── Account ──────────────────────────────────────────────────────────────

    def fetch_balance_usd(self) -> float:
        """Account NAV in account currency. OANDA practice accounts are
        typically USD-denominated; if a user creates a non-USD account we
        return NAV as-is and let the caller handle FX (paper-only concern)."""
        r = self._request("GET", f"/v3/accounts/{self._account}/summary")
        acct = r.get("account") or {}
        return float(acct.get("NAV") or 0)

    def fetch_positions(self) -> list[Position]:
        r = self._request("GET", f"/v3/accounts/{self._account}/openPositions")
        out = []
        for p in (r.get("positions") or []):
            inst = p.get("instrument", "")
            long_data = p.get("long") or {}
            short_data = p.get("short") or {}
            long_units = float(long_data.get("units") or 0)
            short_units = float(short_data.get("units") or 0)
            if long_units != 0:
                out.append(Position(
                    symbol=_from_oanda(inst),
                    qty=abs(long_units),
                    side="long",
                    entry_price=float(long_data.get("averagePrice") or 0),
                    mark_price=0,  # not directly returned; would require a quote call
                    unrealized_pnl_usd=float(long_data.get("unrealizedPL") or 0),
                    leverage=1.0,
                ))
            if short_units != 0:
                out.append(Position(
                    symbol=_from_oanda(inst),
                    qty=abs(short_units),
                    side="short",
                    entry_price=float(short_data.get("averagePrice") or 0),
                    mark_price=0,
                    unrealized_pnl_usd=float(short_data.get("unrealizedPL") or 0),
                    leverage=1.0,
                ))
        return out

    # ── Trading ──────────────────────────────────────────────────────────────

    def place_market_order(
        self,
        symbol: str,
        side: str,                  # "buy" or "sell"
        qty: float,                  # units of base currency (NOT lots)
        *,
        leverage: Optional[float] = None,  # implicit via OANDA's margin tiers
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        reduce_only: bool = False,
    ) -> OrderResult:
        """Market order with optional SL/TP attached.

        OANDA orders accept positive (buy) or negative (sell) `units`. The
        smallest tradeable unit is 1 (micro micro lot); standard mini is
        10,000. We pass `qty` as an integer.
        """
        inst = _to_oanda(symbol)
        units = int(round(qty)) if qty > 0 else 1
        if side == "sell":
            units = -units

        order: dict = {
            "type": "MARKET",
            "instrument": inst,
            "units": str(units),
            "timeInForce": "FOK",
            "positionFill": "REDUCE_ONLY" if reduce_only else "DEFAULT",
        }
        if stop_loss is not None:
            order["stopLossOnFill"] = {"price": f"{stop_loss:.5f}", "timeInForce": "GTC"}
        if take_profit is not None:
            order["takeProfitOnFill"] = {"price": f"{take_profit:.5f}", "timeInForce": "GTC"}

        try:
            r = self._request("POST", f"/v3/accounts/{self._account}/orders",
                              body={"order": order})
            fill = r.get("orderFillTransaction") or r.get("orderCreateTransaction") or {}
            order_id = fill.get("id") or (r.get("lastTransactionID"))
            cancel_reason = (r.get("orderCancelTransaction") or {}).get("reason")
            if cancel_reason:
                return OrderResult(ok=False, order_id=None,
                                   error=f"order cancelled: {cancel_reason}", raw=r)
            return OrderResult(ok=True, order_id=str(order_id) if order_id else None, raw=r)
        except Exception as e:
            return OrderResult(ok=False, order_id=None, error=str(e))

    def cancel_all(self, symbol: str) -> bool:
        try:
            inst = _to_oanda(symbol)
            # Close the open position outright. Cancelling pending orders is
            # a separate call; for our market-only flow this is enough.
            try:
                self._request("PUT",
                              f"/v3/accounts/{self._account}/positions/{inst}/close",
                              body={"longUnits": "ALL", "shortUnits": "ALL"})
            except RuntimeError as e:
                # 404 means no position open; that's fine
                if "404" not in str(e):
                    print(f"[oanda] close position {inst}: {e}")
            return True
        except Exception as e:
            print(f"[oanda] cancel_all({symbol}) failed: {e}")
            return False

    # ── Capabilities ─────────────────────────────────────────────────────────

    def is_session_open(self) -> bool:
        """Forex market open from Sunday 22:00 UTC to Friday 22:00 UTC."""
        now = datetime.now(timezone.utc)
        wd, hour = now.weekday(), now.hour
        # weekday: Mon=0, Sun=6
        if wd == 5:  # Saturday
            return False
        if wd == 6 and hour < 22:  # Sunday before 22:00 UTC
            return False
        if wd == 4 and hour >= 22:  # Friday after 22:00 UTC
            return False
        return True

    def auth_test(self) -> tuple[bool, str]:
        """Quick health check. Returns (ok, message)."""
        if not (self._token and self._account):
            return False, "OANDA_API_TOKEN / OANDA_ACCOUNT_ID missing"
        try:
            r = self._request("GET", f"/v3/accounts/{self._account}/summary")
            acct = r.get("account") or {}
            return True, (
                f"oanda {'practice' if self._practice else 'live'} ok, "
                f"NAV={acct.get('NAV')} {acct.get('currency')}"
            )
        except Exception as e:
            return False, str(e)
