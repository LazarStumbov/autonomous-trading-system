"""Technical analysis engine. Calculates RSI, MACD, Bollinger Bands, ATR, EMA, and volume metrics."""

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)


# ── Pure-Python TA implementations (no pandas/numpy/ta-lib dependency) ──────


def ema(values: list[float], period: int) -> list[float]:
    """Exponential Moving Average."""
    if len(values) < period:
        return [None] * len(values)
    k = 2 / (period + 1)
    result = [None] * (period - 1)
    sma = sum(values[:period]) / period
    result.append(sma)
    for i in range(period, len(values)):
        sma = values[i] * k + result[-1] * (1 - k)
        result.append(sma)
    return result


def sma(values: list[float], period: int) -> list[float]:
    """Simple Moving Average."""
    result = [None] * (period - 1)
    for i in range(period - 1, len(values)):
        result.append(sum(values[i - period + 1:i + 1]) / period)
    return result


def rsi(closes: list[float], period: int = 14) -> list[float]:
    """Relative Strength Index."""
    if len(closes) < period + 1:
        return [None] * len(closes)

    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    result = [None] * period
    if avg_loss == 0:
        result.append(100.0)
    else:
        rs = avg_gain / avg_loss
        result.append(100 - 100 / (1 + rs))

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            result.append(100.0)
        else:
            rs = avg_gain / avg_loss
            result.append(100 - 100 / (1 + rs))

    return result


def macd(closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    """MACD with signal line and histogram."""
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)

    macd_line = []
    for f, s in zip(ema_fast, ema_slow):
        if f is not None and s is not None:
            macd_line.append(f - s)
        else:
            macd_line.append(None)

    # Signal line is EMA of MACD values
    valid_macd = [v for v in macd_line if v is not None]
    signal_line_values = ema(valid_macd, signal) if len(valid_macd) >= signal else [None] * len(valid_macd)

    # Pad signal line to match length
    pad = len(macd_line) - len(signal_line_values)
    signal_line = [None] * pad + signal_line_values

    # Histogram
    histogram = []
    for m, s in zip(macd_line, signal_line):
        if m is not None and s is not None:
            histogram.append(m - s)
        else:
            histogram.append(None)

    return {"macd": macd_line, "signal": signal_line, "histogram": histogram}


def bollinger_bands(closes: list[float], period: int = 20, std_dev: float = 2.0) -> dict:
    """Bollinger Bands."""
    middle = sma(closes, period)
    upper = []
    lower = []

    for i in range(len(closes)):
        if middle[i] is None:
            upper.append(None)
            lower.append(None)
        else:
            window = closes[i - period + 1:i + 1]
            mean = middle[i]
            variance = sum((x - mean) ** 2 for x in window) / period
            sd = math.sqrt(variance)
            upper.append(mean + std_dev * sd)
            lower.append(mean - std_dev * sd)

    # BB width (squeeze indicator)
    width = []
    for u, l, m in zip(upper, lower, middle):
        if u is not None and l is not None and m is not None and m > 0:
            width.append((u - l) / m)
        else:
            width.append(None)

    return {"upper": upper, "middle": middle, "lower": lower, "width": width}


def atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[float]:
    """Average True Range."""
    if len(closes) < 2:
        return [None] * len(closes)

    true_ranges = [highs[0] - lows[0]]
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        true_ranges.append(tr)

    return ema(true_ranges, period)


def volume_analysis(volumes: list[float], period: int = 20) -> dict:
    """Volume analysis: average, ratio to average, spike detection."""
    avg = sma(volumes, period)
    last_vol = volumes[-1] if volumes else 0
    last_avg = avg[-1] if avg and avg[-1] is not None else 1

    return {
        "current": last_vol,
        "average": round(last_avg, 2),
        "ratio": round(last_vol / last_avg, 2) if last_avg > 0 else 0,
        "is_spike": last_vol > last_avg * 2.5,
    }


# ── Main analysis function ──────────────────────────────────────────────────


def analyze_symbol(symbol: str, ohlcv_by_timeframe: dict, config: dict = None) -> dict:
    """Run full technical analysis on a symbol across timeframes.

    Args:
        symbol: Trading pair
        ohlcv_by_timeframe: Dict of timeframe -> list of candle dicts
        config: Optional watchlist config for thresholds

    Returns:
        Dict with analysis results per timeframe and overall signals.
    """
    if config is None:
        config_path = os.path.join(PROJECT_ROOT, "config", "watchlist.json")
        with open(config_path) as f:
            config = json.load(f)

    thresholds = config.get("technical_analysis", {}).get("alert_thresholds", {})
    rsi_oversold = thresholds.get("rsi_oversold", 30)
    rsi_overbought = thresholds.get("rsi_overbought", 70)
    vol_spike_mult = thresholds.get("volume_spike_multiplier", 2.5)
    bb_squeeze = thresholds.get("bb_squeeze_threshold", 0.02)

    result = {"symbol": symbol, "timeframes": {}, "signals": []}

    for tf, tf_data in ohlcv_by_timeframe.items():
        candles = tf_data.get("candles", [])
        if len(candles) < 30:
            result["timeframes"][tf] = {"error": "Insufficient candles", "count": len(candles)}
            continue

        closes = [c["close"] for c in candles]
        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]
        volumes = [c["volume"] for c in candles]

        # Calculate indicators
        rsi_values = rsi(closes)
        macd_data = macd(closes)
        bb_data = bollinger_bands(closes)
        atr_values = atr(highs, lows, closes)
        ema_20 = ema(closes, 20)
        ema_50 = ema(closes, 50)
        ema_200 = ema(closes, 200)
        vol_data = volume_analysis(volumes)

        # Get latest values
        last = closes[-1]
        prev = closes[-2]

        latest = {
            "price": last,
            "rsi": _safe_round(rsi_values[-1]),
            "macd": _safe_round(macd_data["macd"][-1], 6),
            "macd_signal": _safe_round(macd_data["signal"][-1], 6),
            "macd_histogram": _safe_round(macd_data["histogram"][-1], 6),
            "bb_upper": _safe_round(bb_data["upper"][-1]),
            "bb_middle": _safe_round(bb_data["middle"][-1]),
            "bb_lower": _safe_round(bb_data["lower"][-1]),
            "bb_width": _safe_round(bb_data["width"][-1], 4),
            "atr": _safe_round(atr_values[-1]),
            "ema_20": _safe_round(ema_20[-1]),
            "ema_50": _safe_round(ema_50[-1]),
            "ema_200": _safe_round(ema_200[-1]),
            "volume": vol_data,
        }

        # Generate signals for this timeframe
        tf_signals = []

        # RSI signals
        if latest["rsi"] is not None:
            if latest["rsi"] <= rsi_oversold:
                tf_signals.append({"type": "rsi_oversold", "value": latest["rsi"], "bias": "bullish"})
            elif latest["rsi"] >= rsi_overbought:
                tf_signals.append({"type": "rsi_overbought", "value": latest["rsi"], "bias": "bearish"})

        # MACD crossover
        if macd_data["histogram"][-1] is not None and macd_data["histogram"][-2] is not None:
            curr_hist = macd_data["histogram"][-1]
            prev_hist = macd_data["histogram"][-2]
            if prev_hist <= 0 < curr_hist:
                tf_signals.append({"type": "macd_bullish_cross", "bias": "bullish"})
            elif prev_hist >= 0 > curr_hist:
                tf_signals.append({"type": "macd_bearish_cross", "bias": "bearish"})

        # BB squeeze
        if latest["bb_width"] is not None and latest["bb_width"] < bb_squeeze:
            tf_signals.append({"type": "bb_squeeze", "width": latest["bb_width"], "bias": "neutral"})

        # BB touch
        if latest["bb_upper"] and last >= latest["bb_upper"]:
            tf_signals.append({"type": "bb_upper_touch", "bias": "bearish"})
        elif latest["bb_lower"] and last <= latest["bb_lower"]:
            tf_signals.append({"type": "bb_lower_touch", "bias": "bullish"})

        # EMA alignment (trend)
        if latest["ema_20"] and latest["ema_50"] and latest["ema_200"]:
            if latest["ema_20"] > latest["ema_50"] > latest["ema_200"]:
                tf_signals.append({"type": "ema_bullish_alignment", "bias": "bullish"})
            elif latest["ema_20"] < latest["ema_50"] < latest["ema_200"]:
                tf_signals.append({"type": "ema_bearish_alignment", "bias": "bearish"})

        # Price above/below EMAs
        if latest["ema_20"]:
            if last > latest["ema_20"]:
                tf_signals.append({"type": "price_above_ema20", "bias": "bullish"})
            else:
                tf_signals.append({"type": "price_below_ema20", "bias": "bearish"})

        # Volume spike
        if vol_data["is_spike"]:
            tf_signals.append({"type": "volume_spike", "ratio": vol_data["ratio"], "bias": "neutral"})

        # Price change
        change_pct = (last - candles[0]["open"]) / candles[0]["open"] * 100
        latest["change_pct"] = round(change_pct, 2)

        result["timeframes"][tf] = {
            "indicators": latest,
            "signals": tf_signals,
            "candle_count": len(candles),
        }

        # Add timeframe-qualified signals to overall list
        for sig in tf_signals:
            result["signals"].append({**sig, "timeframe": tf, "symbol": symbol})

    return result


def _safe_round(val, decimals=2):
    if val is None:
        return None
    return round(val, decimals)


def run_full_scan(market_data_path: str = None) -> dict:
    """Run TA on all symbols from saved market data.

    Args:
        market_data_path: Path to market_data.json from fetch_market_data.py

    Returns:
        Dict with analysis per symbol.
    """
    if market_data_path is None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        market_data_path = os.path.join(PROJECT_ROOT, "data", "signals", today, "market_data.json")

    with open(market_data_path) as f:
        raw = json.load(f)

    data = raw.get("data", raw)
    results = {}

    for symbol, sdata in data.items():
        tf_data = sdata.get("timeframes", {})
        results[symbol] = analyze_symbol(symbol, tf_data)

    return results


def save_technicals(results: dict, output_dir: str = None) -> str:
    """Save technical analysis results."""
    if output_dir is None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        output_dir = os.path.join(PROJECT_ROOT, "data", "signals", today)

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    filepath = os.path.join(output_dir, "technicals.json")

    with open(filepath, "w") as f:
        json.dump({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "analysis": results,
        }, f, indent=2)

    return filepath


def main():
    parser = argparse.ArgumentParser(description="Run technical analysis on market data")
    parser.add_argument("--input", help="Path to market_data.json")
    parser.add_argument("--no-save", action="store_true")
    args = parser.parse_args()

    results = run_full_scan(args.input)

    if not args.no_save:
        path = save_technicals(results)
        print(f"Saved to: {path}")

    # Print signal summary
    for symbol, analysis in results.items():
        signals = analysis.get("signals", [])
        bull = sum(1 for s in signals if s.get("bias") == "bullish")
        bear = sum(1 for s in signals if s.get("bias") == "bearish")
        print(f"  {symbol}: {bull} bullish, {bear} bearish signals across {len(analysis.get('timeframes', {}))} timeframes")


if __name__ == "__main__":
    main()
