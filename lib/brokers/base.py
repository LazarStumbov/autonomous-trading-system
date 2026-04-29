"""BrokerAdapter — common interface for crypto, stocks, bonds, FX, and CFD venues.

Every adapter is a thin wrapper. It does NOT enforce risk rules — that's the
risk_engine's job. It does not pick strategies — that's the screener / strategy
engine's job. It only knows how to:

  * fetch market data (OHLCV, ticker, depth)
  * fetch account state (balance, positions, open orders)
  * place / cancel orders
  * report supported asset classes
  * declare its trading hours / session info

Stub adapters (Alpaca, IBKR, CFD) raise NotImplementedError on actual order
placement so we can land the architecture without risking accidental live
trades. Stage 4 fills in the bodies.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional

from lib.constants import AssetClass


@dataclass
class Quote:
    symbol: str
    last: float
    bid: Optional[float] = None
    ask: Optional[float] = None
    timestamp: Optional[str] = None


@dataclass
class Position:
    symbol: str
    qty: float
    side: str               # "long" or "short"
    entry_price: float
    mark_price: float
    unrealized_pnl_usd: float
    leverage: float = 1.0


@dataclass
class OrderResult:
    ok: bool
    order_id: Optional[str]
    raw: Any = None
    error: Optional[str] = None


class BrokerAdapter(ABC):
    """Subclass once per venue."""

    name: str = "base"
    supported_classes: tuple[AssetClass, ...] = ()
    trading_hours: str = "24/7"     # human-readable; sessions enforced inside

    # ── Market data ──────────────────────────────────────────────────────────
    @abstractmethod
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 200) -> list[list[float]]:
        """[ [ts, open, high, low, close, volume], ... ]"""

    @abstractmethod
    def fetch_quote(self, symbol: str) -> Quote: ...

    # ── Account state ────────────────────────────────────────────────────────
    @abstractmethod
    def fetch_balance_usd(self) -> float: ...

    @abstractmethod
    def fetch_positions(self) -> list[Position]: ...

    # ── Trading ──────────────────────────────────────────────────────────────
    @abstractmethod
    def place_market_order(
        self,
        symbol: str,
        side: str,                 # "buy" or "sell"
        qty: float,
        *,
        leverage: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        reduce_only: bool = False,
    ) -> OrderResult: ...

    @abstractmethod
    def cancel_all(self, symbol: str) -> bool: ...

    # ── Capabilities ─────────────────────────────────────────────────────────
    def supports(self, asset_class: AssetClass) -> bool:
        return asset_class in self.supported_classes

    def is_session_open(self) -> bool:
        """24/7 by default. Stock/CFD adapters override based on market hours."""
        return True
