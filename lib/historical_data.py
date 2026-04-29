"""Historical OHLCV fetcher with on-disk cache.

Used exclusively by the backtester. Live code pulls through lib/market_data.py.

Cache layout:
    data/cache/ohlcv/<exchange>/<symbol_slug>/<timeframe>.json

Each cache file stores:
    {"exchange": ..., "symbol": ..., "timeframe": ..., "candles": [[ts, o, h, l, c, v], ...]}

The fetcher is idempotent: call fetch_ohlcv(...) and it will either hit the cache
or download the gap from the exchange. ccxt handles rate limits.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CACHE_DIR = os.path.join(PROJECT_ROOT, "data", "cache", "ohlcv")

TF_MS = {
    "1m": 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "1h": 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "1d": 24 * 60 * 60_000,
}


def _slug(symbol: str) -> str:
    return symbol.replace("/", "_").replace(":", "_")


def _cache_path(exchange: str, symbol: str, timeframe: str) -> str:
    d = os.path.join(CACHE_DIR, exchange, _slug(symbol))
    Path(d).mkdir(parents=True, exist_ok=True)
    return os.path.join(d, f"{timeframe}.json")


def _load_cache(path: str) -> list[list]:
    if not os.path.exists(path):
        return []
    try:
        with open(path) as f:
            return json.load(f).get("candles", [])
    except Exception:
        return []


def _save_cache(path: str, exchange: str, symbol: str, timeframe: str, candles: list[list]) -> None:
    with open(path, "w") as f:
        json.dump({
            "exchange": exchange,
            "symbol": symbol,
            "timeframe": timeframe,
            "candles": candles,
        }, f)


def fetch_ohlcv(
    symbol: str,
    timeframe: str = "1h",
    since_ms: Optional[int] = None,
    until_ms: Optional[int] = None,
    exchange_id: str = "bybit",
    max_bars: int = 5000,
    use_cache: bool = True,
) -> list[list]:
    """Fetch historical OHLCV bars as [[ts, open, high, low, close, volume], ...].

    Returns a list sorted ascending by timestamp. Deduplicated. If cache has
    overlapping data, gaps are filled incrementally.

    When ccxt or an exchange is not available (e.g. in CI or offline), this
    function falls back to whatever is cached — it does NOT raise.
    """
    cache_path = _cache_path(exchange_id, symbol, timeframe)
    cached = _load_cache(cache_path) if use_cache else []

    if since_ms is None and cached:
        # Only backfill from the latest cached candle
        since_ms = cached[-1][0] + TF_MS.get(timeframe, 60_000)
    if since_ms is None:
        since_ms = int(time.time() * 1000) - 90 * 24 * 60 * 60_000  # default 90 days

    if until_ms is None:
        until_ms = int(time.time() * 1000)

    new_candles: list[list] = []
    try:
        import ccxt  # type: ignore
        ex_class = getattr(ccxt, exchange_id)
        ex = ex_class({"enableRateLimit": True})

        cursor = since_ms
        while cursor < until_ms and len(new_candles) < max_bars:
            batch = ex.fetch_ohlcv(symbol, timeframe, since=cursor, limit=1000)
            if not batch:
                break
            new_candles.extend(batch)
            cursor = batch[-1][0] + TF_MS.get(timeframe, 60_000)
            if len(batch) < 1000:
                break
    except Exception as e:
        # Offline or ccxt missing — serve from cache only.
        print(f"[historical_data] fetch failed ({e!r}); using cache only for {symbol} {timeframe}")

    # Merge + dedupe by timestamp
    combined = {c[0]: c for c in cached}
    for c in new_candles:
        combined[c[0]] = c
    merged = sorted(combined.values(), key=lambda r: r[0])
    merged = [c for c in merged if since_ms - TF_MS.get(timeframe, 0) <= c[0] <= until_ms]

    if use_cache and new_candles:
        _save_cache(cache_path, exchange_id, symbol, timeframe, merged)

    return merged


def candles_to_ohlcv(candles: list[list]) -> dict:
    """Convert ccxt [ts,o,h,l,c,v] rows into the column-dict shape strategies expect."""
    return {
        "timestamp": [c[0] for c in candles],
        "open": [c[1] for c in candles],
        "high": [c[2] for c in candles],
        "low": [c[3] for c in candles],
        "close": [c[4] for c in candles],
        "volume": [c[5] for c in candles],
    }


def slice_ohlcv(ohlcv: dict, end_index: int) -> dict:
    """Return the portion of ohlcv up to (and including) end_index. Used by backtest to
    present a growing window to strategies bar-by-bar."""
    return {k: v[: end_index + 1] for k, v in ohlcv.items()}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Fetch historical OHLCV")
    parser.add_argument("symbol", help="e.g. BTC/USDT:USDT")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--exchange", default="bybit")
    args = parser.parse_args()

    since = int(time.time() * 1000) - args.days * 24 * 60 * 60_000
    candles = fetch_ohlcv(args.symbol, args.timeframe, since_ms=since, exchange_id=args.exchange)
    print(f"{len(candles)} candles for {args.symbol} {args.timeframe}")
    if candles:
        print(f"  first: {candles[0]}")
        print(f"  last:  {candles[-1]}")
