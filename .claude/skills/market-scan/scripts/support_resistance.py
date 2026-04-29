"""Identify key support and resistance levels from price action."""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)


def find_pivot_points(highs: list[float], lows: list[float], closes: list[float], lookback: int = 5) -> dict:
    """Find pivot highs and lows using a lookback window.

    A pivot high is a bar whose high is the highest in the surrounding `lookback` bars.
    A pivot low is a bar whose low is the lowest in the surrounding `lookback` bars.
    """
    pivot_highs = []
    pivot_lows = []

    for i in range(lookback, len(highs) - lookback):
        # Check if this bar's high is the highest in the window
        window_highs = highs[i - lookback:i + lookback + 1]
        if highs[i] == max(window_highs):
            pivot_highs.append({"index": i, "price": highs[i]})

        # Check if this bar's low is the lowest in the window
        window_lows = lows[i - lookback:i + lookback + 1]
        if lows[i] == min(window_lows):
            pivot_lows.append({"index": i, "price": lows[i]})

    return {"pivot_highs": pivot_highs, "pivot_lows": pivot_lows}


def cluster_levels(levels: list[float], tolerance_pct: float = 0.5) -> list[dict]:
    """Cluster nearby price levels into zones.

    Levels within `tolerance_pct` of each other are merged into a single zone.
    More touches = stronger level.
    """
    if not levels:
        return []

    sorted_levels = sorted(levels)
    clusters = []
    current_cluster = [sorted_levels[0]]

    for price in sorted_levels[1:]:
        cluster_center = sum(current_cluster) / len(current_cluster)
        if abs(price - cluster_center) / cluster_center * 100 <= tolerance_pct:
            current_cluster.append(price)
        else:
            clusters.append(current_cluster)
            current_cluster = [price]
    clusters.append(current_cluster)

    return [
        {
            "price": round(sum(c) / len(c), 2),
            "touches": len(c),
            "range_low": round(min(c), 2),
            "range_high": round(max(c), 2),
        }
        for c in clusters
    ]


def find_sr_levels(candles: list[dict], lookback: int = 5, tolerance_pct: float = 0.5) -> dict:
    """Find support and resistance levels from candle data.

    Args:
        candles: List of OHLCV candle dicts
        lookback: Pivot point lookback window
        tolerance_pct: Clustering tolerance as percentage

    Returns:
        Dict with support levels, resistance levels, and current price context.
    """
    if len(candles) < lookback * 2 + 1:
        return {"error": "Insufficient candles", "support": [], "resistance": []}

    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    closes = [c["close"] for c in candles]
    current_price = closes[-1]

    pivots = find_pivot_points(highs, lows, closes, lookback)

    # Cluster pivot highs (potential resistance) and lows (potential support)
    resistance_prices = [p["price"] for p in pivots["pivot_highs"]]
    support_prices = [p["price"] for p in pivots["pivot_lows"]]

    resistance_zones = cluster_levels(resistance_prices, tolerance_pct)
    support_zones = cluster_levels(support_prices, tolerance_pct)

    # Classify relative to current price
    support = sorted(
        [z for z in support_zones if z["price"] < current_price],
        key=lambda z: z["price"],
        reverse=True,
    )
    resistance = sorted(
        [z for z in resistance_zones if z["price"] > current_price],
        key=lambda z: z["price"],
    )

    # Nearest levels
    nearest_support = support[0]["price"] if support else None
    nearest_resistance = resistance[0]["price"] if resistance else None

    return {
        "current_price": current_price,
        "nearest_support": nearest_support,
        "nearest_resistance": nearest_resistance,
        "support_levels": support[:5],  # Top 5 nearest
        "resistance_levels": resistance[:5],
        "total_pivots": len(pivots["pivot_highs"]) + len(pivots["pivot_lows"]),
    }


def analyze_all_symbols(market_data_path: str = None, timeframe: str = "1d") -> dict:
    """Find S/R levels for all symbols from saved market data."""
    if market_data_path is None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        market_data_path = os.path.join(PROJECT_ROOT, "data", "signals", today, "market_data.json")

    with open(market_data_path) as f:
        raw = json.load(f)

    data = raw.get("data", raw)
    results = {}

    for symbol, sdata in data.items():
        tf_data = sdata.get("timeframes", {}).get(timeframe, {})
        candles = tf_data.get("candles", [])
        results[symbol] = find_sr_levels(candles)

    return results


def main():
    parser = argparse.ArgumentParser(description="Find support and resistance levels")
    parser.add_argument("--input", help="Path to market_data.json")
    parser.add_argument("--timeframe", default="1d", help="Timeframe for S/R detection")
    parser.add_argument("--symbol", help="Single symbol to analyze")
    args = parser.parse_args()

    if args.symbol and args.input:
        with open(args.input) as f:
            raw = json.load(f)
        data = raw.get("data", raw)
        candles = data.get(args.symbol, {}).get("timeframes", {}).get(args.timeframe, {}).get("candles", [])
        result = find_sr_levels(candles)
        print(json.dumps({args.symbol: result}, indent=2))
    else:
        results = analyze_all_symbols(args.input, args.timeframe)
        for symbol, sr in results.items():
            s = sr.get("nearest_support", "?")
            r = sr.get("nearest_resistance", "?")
            print(f"  {symbol}: Support={s} | Resistance={r}")


if __name__ == "__main__":
    main()
