"""IBKR adapter — STUB. Stage 4 will wire this against ib_insync / IB Gateway.

Targets US Treasury futures (ZN/ZB), FX spot (EUR/USD, USD/JPY, etc.), and
optionally equities if we don't standardize on Alpaca for those. Same stub
semantics as alpaca_adapter — fail-closed on any trading call until Stage 4.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from lib.constants import AssetClass
from lib.brokers.base import BrokerAdapter, Quote, Position, OrderResult


class IBKRAdapter(BrokerAdapter):
    name = "ibkr"
    supported_classes = (AssetClass.BOND_FUTURE, AssetClass.FOREX_SPOT)
    trading_hours = "Sun 17:00 ET → Fri 17:00 ET (futures); FX nearly 24x5"

    def __init__(self):
        # Stage 4: ib_insync.IB().connect(host, port, clientId)
        self._ib = None

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 200):
        raise NotImplementedError("IBKRAdapter is a Stage-4 stub.")

    def fetch_quote(self, symbol: str) -> Quote:
        raise NotImplementedError("IBKRAdapter is a Stage-4 stub.")

    def fetch_balance_usd(self) -> float:
        raise NotImplementedError("IBKRAdapter is a Stage-4 stub.")

    def fetch_positions(self) -> list[Position]:
        return []

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
            error="IBKRAdapter not yet implemented (Stage 4 work).",
        )

    def cancel_all(self, symbol: str) -> bool:
        return False

    def is_session_open(self) -> bool:
        now = datetime.now(timezone.utc)
        # Weekend gap roughly Sat 22:00 UTC → Sun 22:00 UTC.
        if now.weekday() == 5:  # Saturday
            return False
        if now.weekday() == 6 and now.hour < 22:  # Sunday before 22:00
            return False
        return True
