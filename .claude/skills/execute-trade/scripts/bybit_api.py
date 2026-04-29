"""Bybit exchange connection via ccxt. Handles authentication, testnet switching, and common operations."""

import os
import sys
import ccxt
from dotenv import load_dotenv

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))


def get_exchange(testnet: bool = None, public_only: bool = False) -> ccxt.bybit:
    """Create Bybit exchange instance.

    Args:
        testnet: Force testnet mode. If None, reads BYBIT_TESTNET env var (default: true).
        public_only: If True, skip auth credentials entirely (used by hot-path scripts
                     that only need OHLCV / ticker data). If False (default) and API
                     keys are set, uses authenticated client. If keys are empty and
                     public_only=False, ccxt still works for public endpoints — but
                     bybit may reject any header that looks like an auth attempt, so
                     pass public_only=True when you know you don't need trading.
    """
    if testnet is None:
        testnet = os.getenv("BYBIT_TESTNET", "true").lower() == "true"

    config = {
        "sandbox": testnet,
        "enableRateLimit": True,
        "options": {
            "defaultType": "swap",  # perpetual futures
            "adjustForTimeDifference": True,
        },
    }
    if not public_only:
        api_key = os.getenv("BYBIT_API_KEY", "")
        secret = os.getenv("BYBIT_SECRET_KEY", "")
        if api_key and secret:
            config["apiKey"] = api_key
            config["secret"] = secret
        # else: leave unauthenticated; trade calls will fail clearly,
        # public calls still work.

    return ccxt.bybit(config)


def get_balance(exchange: ccxt.bybit) -> dict:
    """Get USDT balance summary."""
    balance = exchange.fetch_balance({"type": "swap"})
    usdt = balance.get("USDT", {})
    return {
        "total": usdt.get("total", 0),
        "free": usdt.get("free", 0),
        "used": usdt.get("used", 0),
    }


def set_leverage(exchange: ccxt.bybit, symbol: str, leverage: int) -> dict:
    """Set leverage for a symbol."""
    try:
        result = exchange.set_leverage(leverage, symbol)
        return {"success": True, "symbol": symbol, "leverage": leverage, "result": result}
    except ccxt.ExchangeError as e:
        # Bybit returns error if leverage is already set to the same value
        if "leverage not modified" in str(e).lower() or "same" in str(e).lower():
            return {"success": True, "symbol": symbol, "leverage": leverage, "note": "already set"}
        raise


def set_margin_mode(exchange: ccxt.bybit, symbol: str, mode: str = "isolated") -> dict:
    """Set margin mode (isolated or cross) for a symbol."""
    try:
        result = exchange.set_margin_mode(mode, symbol)
        return {"success": True, "symbol": symbol, "mode": mode, "result": result}
    except ccxt.ExchangeError as e:
        if "not modified" in str(e).lower() or "same" in str(e).lower():
            return {"success": True, "symbol": symbol, "mode": mode, "note": "already set"}
        raise


def get_positions(exchange: ccxt.bybit, symbol: str = None) -> list[dict]:
    """Get open positions, optionally filtered by symbol."""
    positions = exchange.fetch_positions([symbol] if symbol else None)
    # Filter to only positions with non-zero size
    return [
        {
            "symbol": p["symbol"],
            "side": p["side"],
            "size": float(p["contracts"] or 0),
            "notional": float(p["notional"] or 0),
            "entry_price": float(p["entryPrice"] or 0),
            "mark_price": float(p["markPrice"] or 0),
            "unrealized_pnl": float(p["unrealizedPnl"] or 0),
            "leverage": float(p["leverage"] or 1),
            "liquidation_price": float(p["liquidationPrice"] or 0),
            "margin_mode": p.get("marginMode", "isolated"),
        }
        for p in positions
        if float(p["contracts"] or 0) > 0
    ]


def get_ticker(exchange: ccxt.bybit, symbol: str) -> dict:
    """Get current ticker for a symbol."""
    ticker = exchange.fetch_ticker(symbol)
    return {
        "symbol": symbol,
        "last": ticker["last"],
        "bid": ticker["bid"],
        "ask": ticker["ask"],
        "high": ticker["high"],
        "low": ticker["low"],
        "volume": ticker["baseVolume"],
        "change_pct": ticker["percentage"],
    }


def fetch_ohlcv(exchange: ccxt.bybit, symbol: str, timeframe: str = "1h", limit: int = 100) -> list:
    """Fetch OHLCV candles."""
    return exchange.fetch_ohlcv(symbol, timeframe, limit=limit)


if __name__ == "__main__":
    import json
    ex = get_exchange()
    mode = "TESTNET" if ex.sandbox else "LIVE"
    print(f"Bybit connection: {mode}")
    try:
        bal = get_balance(ex)
        print(f"Balance: {json.dumps(bal, indent=2)}")
    except Exception as e:
        print(f"Balance check failed (expected if no API keys): {e}")
