"""Fetch OHLCV market data for all watchlist assets from Bybit via ccxt."""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, ".claude", "skills", "execute-trade", "scripts"))

from bybit_api import get_exchange, get_ticker, fetch_ohlcv


def load_watchlist() -> dict:
    config_path = os.path.join(PROJECT_ROOT, "config", "watchlist.json")
    with open(config_path) as f:
        return json.load(f)


def fetch_all_market_data(symbols: list[str] = None, timeframes: list[str] = None, candle_limit: int = 100) -> dict:
    """Fetch OHLCV data for all symbols across all timeframes.

    Returns:
        Dict keyed by symbol, each containing timeframe data with OHLCV arrays.
    """
    config = load_watchlist()

    if symbols is None:
        symbols = config["watchlist"]["crypto_perpetuals"]
    if timeframes is None:
        tf_config = config["timeframes"]
        timeframes = [tf_config["trend"], tf_config["confirmation"], tf_config["primary"], tf_config["entry"]]

    # Hot-path market-data fetches only need public endpoints; bypass auth so a
    # bad/missing API key doesn't block the screener.
    exchange = get_exchange(public_only=True)
    result = {}

    for symbol in symbols:
        result[symbol] = {"ticker": None, "timeframes": {}}

        # Get current ticker
        try:
            result[symbol]["ticker"] = get_ticker(exchange, symbol)
        except Exception as e:
            result[symbol]["ticker"] = {"error": str(e)}

        # Get OHLCV for each timeframe
        for tf in timeframes:
            try:
                candles = fetch_ohlcv(exchange, symbol, tf, candle_limit)
                # Convert to list of dicts
                ohlcv = [
                    {
                        "timestamp": c[0],
                        "open": c[1],
                        "high": c[2],
                        "low": c[3],
                        "close": c[4],
                        "volume": c[5],
                    }
                    for c in candles
                ]
                result[symbol]["timeframes"][tf] = {
                    "candles": ohlcv,
                    "count": len(ohlcv),
                }
            except Exception as e:
                result[symbol]["timeframes"][tf] = {"error": str(e), "candles": []}

    return result


def save_market_data(data: dict, output_dir: str = None) -> str:
    """Save market data to daily signals directory."""
    if output_dir is None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        output_dir = os.path.join(PROJECT_ROOT, "data", "signals", today)

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    filepath = os.path.join(output_dir, "market_data.json")

    with open(filepath, "w") as f:
        json.dump({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }, f, indent=2)

    return filepath


def main():
    parser = argparse.ArgumentParser(description="Fetch market data for watchlist")
    parser.add_argument("--symbols", nargs="+", help="Override symbols (e.g. BTC/USDT:USDT)")
    parser.add_argument("--timeframes", nargs="+", default=["1d", "4h", "1h", "15m"])
    parser.add_argument("--limit", type=int, default=100, help="Number of candles per timeframe")
    parser.add_argument("--no-save", action="store_true", help="Don't save to disk")
    args = parser.parse_args()

    print(f"Fetching market data...")
    data = fetch_all_market_data(args.symbols, args.timeframes, args.limit)

    if not args.no_save:
        path = save_market_data(data)
        print(f"Saved to: {path}")

    # Print summary
    for symbol, sdata in data.items():
        ticker = sdata.get("ticker", {})
        price = ticker.get("last", "?")
        change = ticker.get("change_pct", "?")
        print(f"  {symbol}: ${price} ({change}%)")


if __name__ == "__main__":
    main()
