"""Alpaca adapter — STUB. Stage 4 will wire this with the alpaca-py SDK.

Targets US equities + bond ETFs (TLT, IEF, etc.). Until Stage 4:
  * fetch_* methods raise NotImplementedError
  * place_market_order returns an OrderResult with ok=False so any caller
    that hits this path fails closed instead of silently no-op-ing.

ASSET_CLASS_ENABLED keeps STOCK_EQUITY/BOND_ETF disabled by default so the
adapter is never called in production today; this stub is purely so the
strategy registry / screener can reference symbols in those classes without
import errors.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from lib.constants import AssetClass
from lib.brokers.base import BrokerAdapter, Quote, Position, OrderResult


class AlpacaAdapter(BrokerAdapter):
    name = "alpaca"
    supported_classes = (AssetClass.STOCK_EQUITY, AssetClass.BOND_ETF)
    # NYSE/Nasdaq core hours; pre/post pruning is the strategy's job.
    trading_hours = "Mon-Fri 09:30-16:00 ET"

    def __init__(self):
        # Stage 4: instantiate alpaca.trading.client.TradingClient
        # using ALPACA_KEY_ID / ALPACA_SECRET_KEY / ALPACA_PAPER env vars.
        self._client = None

    # ── Market data ──────────────────────────────────────────────────────────
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 200):
        raise NotImplementedError("AlpacaAdapter is a Stage-4 stub.")

    def fetch_quote(self, symbol: str) -> Quote:
        raise NotImplementedError("AlpacaAdapter is a Stage-4 stub.")

    # ── Account ──────────────────────────────────────────────────────────────
    def fetch_balance_usd(self) -> float:
        raise NotImplementedError("AlpacaAdapter is a Stage-4 stub.")

    def fetch_positions(self) -> list[Position]:
        return []

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
        return OrderResult(
            ok=False,
            order_id=None,
            error="AlpacaAdapter not yet implemented (Stage 4 work).",
        )

    def cancel_all(self, symbol: str) -> bool:
        return False

    # ── Capabilities ─────────────────────────────────────────────────────────
    def is_session_open(self) -> bool:
        # Naive check: weekday + 13:30-20:00 UTC ≈ NYSE 09:30-16:00 ET.
        # Real implementation pulls Alpaca's calendar API.
        now = datetime.now(timezone.utc)
        if now.weekday() >= 5:
            return False
        minutes = now.hour * 60 + now.minute
        return 13 * 60 + 30 <= minutes <= 20 * 60
