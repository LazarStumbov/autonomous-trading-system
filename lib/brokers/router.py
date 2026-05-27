"""Per-asset-class broker router.

Single source of truth for: given a symbol, which adapter handles it and
in what mode (paper/demo/live)? Used by execution_engine and position_monitor
so the dispatch logic isn't duplicated.

Resolution order for any given symbol:
  1. Infer asset_class from symbol (delegated to lib.risk_engine._infer_asset_class)
  2. Look up the asset class → broker name in `BROKER_BY_CLASS` (config dict
     built from env vars at module-load time)
  3. Instantiate the adapter; the adapter itself reads its own paper/demo
     flag from env (BROKER_MODE=demo → OKX_DEMO=true / ALPACA_PAPER=true /
     OANDA_PRACTICE=true)
  4. Cache the instance per process so we don't reconstruct on every call

Env vars (override defaults):
  CRYPTO_PERP_BROKER  default 'alpaca'     — crypto (now routed to Alpaca spot post-MiCA blockade)
  CRYPTO_SPOT_BROKER  default 'alpaca'     — crypto spot
  STOCKS_BROKER       default 'alpaca'     — equities, bond ETFs
  BONDS_BROKER        default 'alpaca'     — bond ETFs (TLT, IEF, AGG)
  FOREX_BROKER        default 'oanda'      — forex spot
  CFD_BROKER          default 'synthetic'  — indices, commodities (no real broker yet)

When the resolver returns 'synthetic', the caller should fall through to the
existing paper_engine.simulate_order() path (this is what bonds and CFDs do
until those adapters are wired).

Post-MiCA crypto routing (2026-05): OKX blocks BTC/ETH and all alt perps for
EU residents. We re-route all crypto through Alpaca spot for BTC/ETH/SOL
(the only pairs we trade for real), and fall through to synthetic for alts
(ARB/OP/SUI/etc.) which are paper-only research.
"""

from __future__ import annotations

import os
from typing import Optional

from lib.brokers.base import BrokerAdapter


_DEFAULT_BROKER_BY_CLASS = {
    "crypto_perp":     "alpaca",   # post-MiCA: OKX blocks EU residents; Alpaca spot for BTC/ETH/SOL
    "crypto_spot":     "alpaca",
    "stock_equity":    "alpaca",
    "bond_etf":        "alpaca",
    "bond_future":     "synthetic",  # IBKR-only, deferred
    "forex_spot":      "oanda",
    "cfd_forex":       "synthetic",
    "cfd_index":       "synthetic",
    "cfd_commodity":   "synthetic",
    "polymarket_binary": "polymarket",  # handled by polymarket-bet skill, not here
    "unknown":         "synthetic",
}


def _broker_for_class(asset_class: str) -> str:
    """Read the env override (e.g. STOCKS_BROKER) and fall back to the default."""
    env_key = {
        "crypto_perp":   "CRYPTO_PERP_BROKER",
        "crypto_spot":   "CRYPTO_SPOT_BROKER",
        "stock_equity":  "STOCKS_BROKER",
        "bond_etf":      "BONDS_BROKER",
        "forex_spot":    "FOREX_BROKER",
        "cfd_forex":     "CFD_BROKER",
        "cfd_index":     "CFD_BROKER",
        "cfd_commodity": "CFD_BROKER",
    }.get(asset_class)
    if env_key:
        val = os.environ.get(env_key, "").strip().lower()
        if val:
            return val
    return _DEFAULT_BROKER_BY_CLASS.get(asset_class, "synthetic")


_ADAPTER_CACHE: dict[str, BrokerAdapter] = {}


def _instantiate(broker_name: str) -> Optional[BrokerAdapter]:
    """Build (or fetch cached) adapter instance for a broker name."""
    if broker_name in _ADAPTER_CACHE:
        return _ADAPTER_CACHE[broker_name]
    if broker_name == "synthetic":
        return None  # caller falls through to paper_engine.simulate_order
    try:
        if broker_name == "okx":
            from lib.brokers.okx_adapter import OkxAdapter
            inst = OkxAdapter()
        elif broker_name == "alpaca":
            from lib.brokers.alpaca_adapter import AlpacaAdapter
            inst = AlpacaAdapter()
        elif broker_name == "oanda":
            from lib.brokers.oanda_adapter import OandaAdapter
            inst = OandaAdapter()
        else:
            print(f"[broker_router] unknown broker '{broker_name}' — falling through to synthetic")
            return None
        _ADAPTER_CACHE[broker_name] = inst
        return inst
    except Exception as e:
        print(f"[broker_router] failed to instantiate {broker_name}: {e}")
        return None


# Alpaca crypto whitelist — bases we actually trade for real. Everything
# outside this list falls through to synthetic (paper-only research). Keep
# small and explicit; expanding requires confirming Alpaca's supported list.
_ALPACA_CRYPTO_BASES = {"BTC", "ETH", "SOL"}


def _alpaca_supports_crypto_symbol(symbol: str) -> bool:
    """Extract the base asset from a crypto symbol and check the whitelist.

    Handles 'BTC/USDT:USDT', 'BTC/USDT', 'BTC/USD', 'BTC'.
    """
    s = (symbol or "").upper()
    base = s.split("/")[0].split(":")[0]
    return base in _ALPACA_CRYPTO_BASES


def adapter_for_symbol(symbol: str) -> tuple[Optional[BrokerAdapter], str, str]:
    """Return (adapter, broker_name, asset_class) for a given symbol.

    `adapter` is None when the asset class is mapped to 'synthetic' (no real
    broker available) — the caller should fall through to paper_engine.

    `broker_name` is always set ('synthetic' / 'okx' / 'alpaca' / 'oanda').
    `asset_class` is the inferred class string used for downstream tagging.
    """
    # Lazy import to avoid circular dep at module load
    from lib.risk_engine import _infer_asset_class

    asset_class = _infer_asset_class(symbol) or "unknown"
    broker_name = _broker_for_class(asset_class)

    # Crypto + Alpaca: only BTC/ETH/SOL are supported. Unsupported alts fall
    # through to synthetic so we don't send bad orders to the Alpaca API.
    if broker_name == "alpaca" and asset_class in ("crypto_perp", "crypto_spot"):
        if not _alpaca_supports_crypto_symbol(symbol):
            broker_name = "synthetic"

    adapter = _instantiate(broker_name)
    return adapter, broker_name, asset_class


def auth_test_all() -> list[dict]:
    """Run auth_test on every configured adapter. Returns list of results.

    Skips 'synthetic'. Used by the runbook + dashboard to verify creds are
    set correctly before the first cron tick.
    """
    out = []
    seen = set()
    for cls, broker in _DEFAULT_BROKER_BY_CLASS.items():
        env_override = os.environ.get({
            "crypto_perp": "CRYPTO_PERP_BROKER", "crypto_spot": "CRYPTO_SPOT_BROKER",
            "stock_equity": "STOCKS_BROKER", "bond_etf": "BONDS_BROKER",
            "forex_spot": "FOREX_BROKER",
        }.get(cls, ""), "").strip().lower()
        broker_name = env_override or broker
        if broker_name in seen or broker_name in ("synthetic", "polymarket"):
            continue
        seen.add(broker_name)
        adapter = _instantiate(broker_name)
        if adapter is None:
            out.append({"broker": broker_name, "ok": False, "msg": "could not instantiate"})
            continue
        if hasattr(adapter, "auth_test"):
            try:
                ok, msg = adapter.auth_test()
            except Exception as e:
                ok, msg = False, str(e)
        else:
            ok, msg = True, "no auth_test method (assumed ok)"
        out.append({"broker": broker_name, "ok": ok, "msg": msg})
    return out


if __name__ == "__main__":
    # CLI: smoke-test broker connectivity. Useful before deploying to Modal.
    import json
    print(json.dumps(auth_test_all(), indent=2))
