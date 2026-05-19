"""Alpaca adapter — stocks + crypto spot, paper or live.

Uses Alpaca's REST API directly (no SDK dependency) to keep the Modal image
slim. All endpoints documented at https://docs.alpaca.markets/.

Two distinct domains:
  - Trading: https://paper-api.alpaca.markets (paper) | https://api.alpaca.markets (live)
  - Market data: https://data.alpaca.markets (same for paper and live)

Env vars:
  ALPACA_KEY_ID         — API key id (paper or live)
  ALPACA_SECRET_KEY     — API secret
  ALPACA_PAPER          — 'true' (default) | 'false'
  ALPACA_DATA_FEED      — 'iex' (default, free) | 'sip' (paid)

Asset class routing:
  - STOCK_EQUITY → /v2/orders with symbol like "SPY"
  - CRYPTO_SPOT  → /v2/orders with symbol like "BTC/USD" (Alpaca uses slash form)
  - BOND_ETF     → same as equity (TLT, IEF, AGG are ETFs)

Paper-trading note: Alpaca paper fills against real-market quotes with
simulated slippage. It is NOT a synthetic price; the order book is real.
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


PAPER_BASE = "https://paper-api.alpaca.markets"
LIVE_BASE = "https://api.alpaca.markets"
DATA_BASE = "https://data.alpaca.markets"


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


def _is_crypto_symbol(symbol: str) -> bool:
    """Alpaca crypto symbols look like 'BTC/USD' or 'ETH/USD'.

    The system's canonical crypto symbols are 'BTC/USDT:USDT' (perp). For
    Alpaca spot we map base → BASE/USD. Non-slash, non-perp tickers like
    'SPY' are equities.
    """
    s = (symbol or "").upper()
    if "/USD" in s and ":USDT" not in s:
        return True
    return False


def _normalize_crypto(symbol: str) -> str:
    """Convert canonical perp form to Alpaca spot form. 'BTC/USDT:USDT' -> 'BTC/USD'."""
    s = (symbol or "").upper()
    if ":USDT" in s:
        base = s.split("/")[0]
        return f"{base}/USD"
    if "/USD" in s:
        return s
    return f"{s}/USD"


class AlpacaAdapter(BrokerAdapter):
    name = "alpaca"
    supported_classes = (
        AssetClass.STOCK_EQUITY,
        AssetClass.BOND_ETF,
        AssetClass.CRYPTO_SPOT,
    )
    trading_hours = "Stocks: Mon-Fri 09:30-16:00 ET | Crypto: 24/7"

    def __init__(self, paper: Optional[bool] = None):
        if paper is None:
            paper = _env("ALPACA_PAPER", "true").lower().strip() != "false"
        self._paper = paper
        self._base = PAPER_BASE if paper else LIVE_BASE
        self._key = _env("ALPACA_KEY_ID")
        self._secret = _env("ALPACA_SECRET_KEY")
        self._data_feed = _env("ALPACA_DATA_FEED", "iex").lower()

    # ── HTTP plumbing ────────────────────────────────────────────────────────

    def _headers(self) -> dict:
        return {
            "APCA-API-KEY-ID": self._key,
            "APCA-API-SECRET-KEY": self._secret,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request(self, method: str, base: str, path: str, *,
                 params: Optional[dict] = None, body: Optional[dict] = None,
                 timeout: float = 15.0) -> dict | list:
        url = base + path
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
            raise RuntimeError(f"alpaca {method} {path} → {e.code}: {body_str[:300]}") from e

    # ── Market data ──────────────────────────────────────────────────────────

    def fetch_quote(self, symbol: str) -> Quote:
        if _is_crypto_symbol(symbol) or ":USDT" in symbol.upper():
            sym = _normalize_crypto(symbol)
            r = self._request("GET", DATA_BASE,
                              "/v1beta3/crypto/us/latest/quotes",
                              params={"symbols": sym})
            q = (r.get("quotes") or {}).get(sym) or {}
            ap, bp = float(q.get("ap") or 0), float(q.get("bp") or 0)
            last = (ap + bp) / 2 if ap and bp else (ap or bp)
            return Quote(symbol=symbol, last=last, bid=bp or None, ask=ap or None,
                         timestamp=q.get("t"))
        else:
            # Equities. Use the latest trade endpoint — most robust on free IEX tier.
            r = self._request("GET", DATA_BASE, f"/v2/stocks/{symbol}/trades/latest",
                              params={"feed": self._data_feed})
            t = r.get("trade") or {}
            last = float(t.get("p") or 0)
            return Quote(symbol=symbol, last=last, bid=None, ask=None,
                         timestamp=t.get("t"))

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 200) -> list[list[float]]:
        """Returns [[ts_ms, open, high, low, close, volume], ...]."""
        tf_map = {"1m": "1Min", "5m": "5Min", "15m": "15Min",
                  "1h": "1Hour", "4h": "4Hour", "1d": "1Day"}
        tf = tf_map.get(timeframe, "1Hour")
        if _is_crypto_symbol(symbol) or ":USDT" in symbol.upper():
            sym = _normalize_crypto(symbol)
            r = self._request("GET", DATA_BASE, "/v1beta3/crypto/us/bars",
                              params={"symbols": sym, "timeframe": tf, "limit": limit})
            bars = (r.get("bars") or {}).get(sym) or []
        else:
            r = self._request("GET", DATA_BASE, f"/v2/stocks/{symbol}/bars",
                              params={"timeframe": tf, "limit": limit, "feed": self._data_feed})
            bars = r.get("bars") or []
        out = []
        for b in bars:
            ts = b.get("t")
            ts_ms = int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() * 1000) \
                if isinstance(ts, str) else int(ts or 0)
            out.append([ts_ms, float(b.get("o") or 0), float(b.get("h") or 0),
                        float(b.get("l") or 0), float(b.get("c") or 0),
                        float(b.get("v") or 0)])
        return out

    # ── Account ──────────────────────────────────────────────────────────────

    def fetch_balance_usd(self) -> float:
        r = self._request("GET", self._base, "/v2/account")
        return float(r.get("equity") or 0)

    def fetch_positions(self) -> list[Position]:
        r = self._request("GET", self._base, "/v2/positions")
        out = []
        for p in (r if isinstance(r, list) else []):
            qty = float(p.get("qty") or 0)
            side = "long" if qty > 0 else "short"
            out.append(Position(
                symbol=p.get("symbol"),
                qty=abs(qty),
                side=side,
                entry_price=float(p.get("avg_entry_price") or 0),
                mark_price=float(p.get("current_price") or 0),
                unrealized_pnl_usd=float(p.get("unrealized_pl") or 0),
                leverage=1.0,
            ))
        return out

    # ── Trading ──────────────────────────────────────────────────────────────

    def place_market_order(
        self,
        symbol: str,
        side: str,                  # "buy" or "sell"
        qty: float,
        *,
        leverage: Optional[float] = None,  # ignored — Alpaca uses portfolio margin
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        reduce_only: bool = False,
    ) -> OrderResult:
        """Market order; optional bracket with SL/TP.

        Crypto orders accept fractional qty and use 'gtc' time-in-force; equity
        orders use 'day'. Bracket orders are not supported for crypto on Alpaca;
        when crypto + SL/TP, we place the market entry alone and a separate
        sibling order can be placed later. For equities we use the bracket OCO.
        """
        is_crypto = _is_crypto_symbol(symbol) or ":USDT" in symbol.upper()
        sym = _normalize_crypto(symbol) if is_crypto else symbol

        order_body: dict = {
            "symbol": sym,
            "qty": str(qty),
            "side": side,
            "type": "market",
            "time_in_force": "gtc" if is_crypto else "day",
        }

        if not is_crypto and (stop_loss or take_profit):
            order_body["order_class"] = "bracket"
            if take_profit:
                order_body["take_profit"] = {"limit_price": str(take_profit)}
            if stop_loss:
                order_body["stop_loss"] = {"stop_price": str(stop_loss)}

        try:
            r = self._request("POST", self._base, "/v2/orders", body=order_body)
            order_id = r.get("id") if isinstance(r, dict) else None

            # Crypto: place SL/TP as separate stop orders since bracket isn't supported
            if is_crypto and order_id and (stop_loss or take_profit):
                opp = "sell" if side == "buy" else "buy"
                if stop_loss:
                    try:
                        self._request("POST", self._base, "/v2/orders", body={
                            "symbol": sym, "qty": str(qty), "side": opp,
                            "type": "stop", "stop_price": str(stop_loss),
                            "time_in_force": "gtc",
                        })
                    except Exception as e:
                        print(f"[alpaca] crypto stop_loss attach failed (non-fatal): {e}")
                if take_profit:
                    try:
                        self._request("POST", self._base, "/v2/orders", body={
                            "symbol": sym, "qty": str(qty), "side": opp,
                            "type": "limit", "limit_price": str(take_profit),
                            "time_in_force": "gtc",
                        })
                    except Exception as e:
                        print(f"[alpaca] crypto take_profit attach failed (non-fatal): {e}")

            return OrderResult(ok=True, order_id=order_id, raw=r)
        except Exception as e:
            return OrderResult(ok=False, order_id=None, error=str(e))

    def cancel_all(self, symbol: str) -> bool:
        try:
            # Alpaca's cancel-all endpoint cancels EVERY open order on the
            # account. For per-symbol we have to list then cancel individually.
            sym = _normalize_crypto(symbol) if (
                _is_crypto_symbol(symbol) or ":USDT" in symbol.upper()
            ) else symbol
            orders = self._request("GET", self._base, "/v2/orders",
                                   params={"status": "open", "symbols": sym})
            for o in (orders if isinstance(orders, list) else []):
                try:
                    self._request("DELETE", self._base, f"/v2/orders/{o.get('id')}")
                except Exception:
                    pass
            return True
        except Exception as e:
            print(f"[alpaca] cancel_all({symbol}) failed: {e}")
            return False

    # ── Capabilities ─────────────────────────────────────────────────────────

    def is_session_open(self) -> bool:
        """For equities: Mon-Fri 13:30-20:00 UTC (NYSE core). Crypto: always."""
        # This is asset-class-specific; the orchestrator should call this with
        # the specific symbol in mind. Conservative default: equity session.
        now = datetime.now(timezone.utc)
        if now.weekday() >= 5:
            return False
        minutes = now.hour * 60 + now.minute
        return 13 * 60 + 30 <= minutes <= 20 * 60

    def auth_test(self) -> tuple[bool, str]:
        """Quick health check: can we read the account? Returns (ok, message)."""
        if not (self._key and self._secret):
            return False, "ALPACA_KEY_ID / ALPACA_SECRET_KEY missing"
        try:
            r = self._request("GET", self._base, "/v2/account")
            status = r.get("status", "?")
            return True, f"alpaca {'paper' if self._paper else 'live'} ok, status={status}, equity=${r.get('equity', '?')}"
        except Exception as e:
            return False, str(e)
