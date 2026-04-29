"""CFD adapter — STUB. Broker selection is TBD (OANDA / IG / Capital.com / Pepperstone).

CFDs are attractive for short-timeframe directional plays on indices
(SPX500, NAS100), commodities (XAU/USD, oil), and FX with leverage that
isn't available on regulated US venues. Selection criteria for the live
broker (Stage 4):

  * REST or FIX API with demo + live environments
  * Programmatic stop-loss/take-profit attachment on order entry
  * Reasonable spreads on SPX500 / XAU / EUR-USD
  * Compatible with our jurisdiction (skip US-restricted venues)

Until then this is a fail-closed stub.
"""

from __future__ import annotations

from typing import Optional

from lib.constants import AssetClass
from lib.brokers.base import BrokerAdapter, Quote, Position, OrderResult


class CFDStubAdapter(BrokerAdapter):
    name = "cfd_stub"
    supported_classes = (AssetClass.CFD_INDEX, AssetClass.CFD_COMMODITY, AssetClass.CFD_FOREX)
    trading_hours = "Sun 22:00 UTC → Fri 21:00 UTC (varies by instrument)"

    def __init__(self):
        self._broker = None

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 200):
        raise NotImplementedError("CFDStubAdapter — broker not selected yet.")

    def fetch_quote(self, symbol: str) -> Quote:
        raise NotImplementedError("CFDStubAdapter — broker not selected yet.")

    def fetch_balance_usd(self) -> float:
        raise NotImplementedError("CFDStubAdapter — broker not selected yet.")

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
            error="CFDStubAdapter — broker not selected; trading disabled.",
        )

    def cancel_all(self, symbol: str) -> bool:
        return False
