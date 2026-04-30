"""Broker adapter registry.

Maps asset classes to a concrete `BrokerAdapter` subclass. The strategy
engine, screener, and execution engine route through `get_adapter_for(symbol)`
so they remain broker-agnostic.

Stage 4 status:
  - crypto_perp / crypto_spot → OkxAdapter (real, ccxt; OKX_DEMO=true → paper)
  - stock_equity / bond_etf   → AlpacaAdapter (stub — wire OAuth in Stage 4)
  - bond_future / forex_spot  → IBKRAdapter  (stub — wire IB Gateway in Stage 4)
  - cfd_*                     → CFDStubAdapter (placeholder; broker TBD)
  - polymarket_binary         → PolymarketAdapter (Stage 3)

Broker change log:
  2026-04: Switched from BybitAdapter → OkxAdapter. Bybit EU disabled
  perpetual/derivative trading for retail clients under ESMA restrictions.
  OKX supports USDT-margined perps with demo trading (OKX_DEMO=true).

`is_enabled(asset_class)` is the gate every caller must respect; if the
adapter exists but the asset class is disabled in `ASSET_CLASS_ENABLED`,
trading is blocked at the broker layer.
"""

from __future__ import annotations

from typing import Optional

from lib.constants import AssetClass, ASSET_CLASS_ENABLED
from lib.brokers.base import BrokerAdapter

# Lazy imports to avoid pulling ccxt etc. when not needed.
_REGISTRY: dict[AssetClass, str] = {
    AssetClass.CRYPTO_PERP: "lib.brokers.okx_adapter:OkxAdapter",
    AssetClass.CRYPTO_SPOT: "lib.brokers.okx_adapter:OkxAdapter",
    AssetClass.STOCK_EQUITY: "lib.brokers.alpaca_adapter:AlpacaAdapter",
    AssetClass.BOND_ETF: "lib.brokers.alpaca_adapter:AlpacaAdapter",
    AssetClass.BOND_FUTURE: "lib.brokers.ibkr_adapter:IBKRAdapter",
    AssetClass.FOREX_SPOT: "lib.brokers.ibkr_adapter:IBKRAdapter",
    AssetClass.CFD_INDEX: "lib.brokers.cfd_adapter:CFDStubAdapter",
    AssetClass.CFD_COMMODITY: "lib.brokers.cfd_adapter:CFDStubAdapter",
    AssetClass.CFD_FOREX: "lib.brokers.cfd_adapter:CFDStubAdapter",
}


def is_enabled(asset_class: AssetClass) -> bool:
    return ASSET_CLASS_ENABLED.get(asset_class, False)


def _import_class(dotted: str):
    module_path, class_name = dotted.split(":")
    mod = __import__(module_path, fromlist=[class_name])
    return getattr(mod, class_name)


def get_adapter(asset_class: AssetClass) -> Optional[BrokerAdapter]:
    """Return an instantiated adapter for the given asset class, or None
    if the class is disabled or has no adapter."""
    if not is_enabled(asset_class):
        return None
    target = _REGISTRY.get(asset_class)
    if not target:
        return None
    cls = _import_class(target)
    return cls()


def get_adapter_for(symbol: str) -> Optional[BrokerAdapter]:
    """Convenience: route by Bybit-style symbol heuristics.
    Falls back to lib.category_cooldown.asset_to_category for the mapping."""
    from lib.category_cooldown import asset_to_category

    cat = asset_to_category(symbol).lower()
    try:
        ac = AssetClass(cat)
    except ValueError:
        ac = AssetClass.UNKNOWN
    return get_adapter(ac)


__all__ = ["BrokerAdapter", "is_enabled", "get_adapter", "get_adapter_for"]
