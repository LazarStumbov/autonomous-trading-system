"""Pure-Python technical indicators shared across strategies.

Pulled out of .claude/skills/market-scan/scripts/technical_analysis.py so both
the live scanner and the strategy library / backtester can share one source of
truth. No pandas/numpy dependency: strategies stay fast to import in serverless
environments (Modal cold-start) and remain unit-testable in isolation.
"""

from __future__ import annotations

import math
from typing import Optional


Number = Optional[float]


def ema(values: list[float], period: int) -> list[Number]:
    """Exponential Moving Average."""
    if len(values) < period:
        return [None] * len(values)
    k = 2 / (period + 1)
    result: list[Number] = [None] * (period - 1)
    sma_init = sum(values[:period]) / period
    result.append(sma_init)
    for i in range(period, len(values)):
        prev = result[-1]
        result.append(values[i] * k + prev * (1 - k))
    return result


def sma(values: list[float], period: int) -> list[Number]:
    """Simple Moving Average."""
    result: list[Number] = [None] * (period - 1)
    for i in range(period - 1, len(values)):
        result.append(sum(values[i - period + 1:i + 1]) / period)
    return result


def rsi(closes: list[float], period: int = 14) -> list[Number]:
    """Relative Strength Index (Wilder smoothing)."""
    if len(closes) < period + 1:
        return [None] * len(closes)

    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    result: list[Number] = [None] * period
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
    """MACD line, signal line, histogram."""
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)

    macd_line: list[Number] = []
    for f, s in zip(ema_fast, ema_slow):
        macd_line.append(f - s if (f is not None and s is not None) else None)

    valid = [v for v in macd_line if v is not None]
    sig_vals = ema(valid, signal) if len(valid) >= signal else [None] * len(valid)
    pad = len(macd_line) - len(sig_vals)
    signal_line = [None] * pad + sig_vals

    histogram: list[Number] = []
    for m, s in zip(macd_line, signal_line):
        histogram.append(m - s if (m is not None and s is not None) else None)

    return {"macd": macd_line, "signal": signal_line, "histogram": histogram}


def bollinger_bands(closes: list[float], period: int = 20, std_dev: float = 2.0) -> dict:
    """Bollinger Bands upper/middle/lower + width."""
    middle = sma(closes, period)
    upper: list[Number] = []
    lower: list[Number] = []
    for i in range(len(closes)):
        m = middle[i]
        if m is None:
            upper.append(None)
            lower.append(None)
            continue
        window = closes[i - period + 1:i + 1]
        variance = sum((x - m) ** 2 for x in window) / period
        sd = math.sqrt(variance)
        upper.append(m + std_dev * sd)
        lower.append(m - std_dev * sd)

    width: list[Number] = []
    for u, l, m in zip(upper, lower, middle):
        if u is not None and l is not None and m is not None and m > 0:
            width.append((u - l) / m)
        else:
            width.append(None)

    return {"upper": upper, "middle": middle, "lower": lower, "width": width}


def atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[Number]:
    """Average True Range (Wilder)."""
    if len(closes) < 2:
        return [None] * len(closes)
    tr = [highs[0] - lows[0]]
    for i in range(1, len(closes)):
        tr.append(max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        ))
    return ema(tr, period)


def donchian(highs: list[float], lows: list[float], period: int = 20) -> dict:
    """Donchian Channel."""
    upper: list[Number] = [None] * (period - 1)
    lower: list[Number] = [None] * (period - 1)
    for i in range(period - 1, len(highs)):
        upper.append(max(highs[i - period + 1:i + 1]))
        lower.append(min(lows[i - period + 1:i + 1]))
    mid = [(u + l) / 2 if (u is not None and l is not None) else None for u, l in zip(upper, lower)]
    return {"upper": upper, "middle": mid, "lower": lower}


def supertrend(highs: list[float], lows: list[float], closes: list[float],
               period: int = 10, multiplier: float = 3.0) -> dict:
    """Supertrend indicator. Returns 'trend' (+1 long, -1 short) and 'line' values."""
    atr_vals = atr(highs, lows, closes, period)
    hl2 = [(h + l) / 2 for h, l in zip(highs, lows)]

    upper_basic = [h + multiplier * a if a is not None else None for h, a in zip(hl2, atr_vals)]
    lower_basic = [h - multiplier * a if a is not None else None for h, a in zip(hl2, atr_vals)]

    upper_final: list[Number] = [None] * len(closes)
    lower_final: list[Number] = [None] * len(closes)
    trend = [1] * len(closes)
    line: list[Number] = [None] * len(closes)

    for i in range(len(closes)):
        if upper_basic[i] is None or lower_basic[i] is None:
            continue
        if i == 0 or upper_final[i - 1] is None:
            upper_final[i] = upper_basic[i]
            lower_final[i] = lower_basic[i]
            line[i] = lower_final[i]
            continue
        upper_final[i] = upper_basic[i] if (upper_basic[i] < upper_final[i - 1] or closes[i - 1] > upper_final[i - 1]) else upper_final[i - 1]
        lower_final[i] = lower_basic[i] if (lower_basic[i] > lower_final[i - 1] or closes[i - 1] < lower_final[i - 1]) else lower_final[i - 1]

        if trend[i - 1] == 1 and closes[i] < lower_final[i]:
            trend[i] = -1
        elif trend[i - 1] == -1 and closes[i] > upper_final[i]:
            trend[i] = 1
        else:
            trend[i] = trend[i - 1]
        line[i] = lower_final[i] if trend[i] == 1 else upper_final[i]
    return {"trend": trend, "line": line, "upper": upper_final, "lower": lower_final}


def vwap(highs: list[float], lows: list[float], closes: list[float], volumes: list[float]) -> list[Number]:
    """Volume-Weighted Average Price (cumulative, session-style)."""
    cum_vol = 0.0
    cum_pv = 0.0
    out: list[Number] = []
    for h, l, c, v in zip(highs, lows, closes, volumes):
        tp = (h + l + c) / 3
        cum_pv += tp * v
        cum_vol += v
        out.append(cum_pv / cum_vol if cum_vol > 0 else None)
    return out


def volume_ratio(volumes: list[float], period: int = 20) -> float:
    """Current volume / avg volume over period."""
    if len(volumes) < period + 1:
        return 0.0
    avg = sum(volumes[-period - 1:-1]) / period
    return volumes[-1] / avg if avg > 0 else 0.0


def pct_change(values: list[float], lookback: int = 1) -> Optional[float]:
    """Percent change over N bars."""
    if len(values) < lookback + 1 or values[-lookback - 1] == 0:
        return None
    return (values[-1] - values[-lookback - 1]) / values[-lookback - 1] * 100


def cross_above(a: list[Number], b: list[Number]) -> bool:
    """True if series a crossed above series b on the last bar."""
    if len(a) < 2 or len(b) < 2:
        return False
    if a[-1] is None or a[-2] is None or b[-1] is None or b[-2] is None:
        return False
    return a[-2] <= b[-2] and a[-1] > b[-1]


def cross_below(a: list[Number], b: list[Number]) -> bool:
    """True if series a crossed below series b on the last bar."""
    if len(a) < 2 or len(b) < 2:
        return False
    if a[-1] is None or a[-2] is None or b[-1] is None or b[-2] is None:
        return False
    return a[-2] >= b[-2] and a[-1] < b[-1]
