"""TradingView — Hull Moving Average Cross (HMA, Alan Hull).

Pattern origin:  Hull MA — Alan Hull (2005). Reduces lag vs traditional MAs.
                 Approximated here via 2*EMA(N/2) - EMA(N), then EMA(sqrt(N))
                 — standard textbook formulation.
Source URL:      https://alanhull.com/hull-moving-average
License:         MIT.
Notes:           Approximates HMA by stacking EMAs; not a perfect 1:1 with weighted
                 MA implementation but captures the same lag-reduction behaviour.
"""

from __future__ import annotations
import math
from typing import Optional

from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import ema, cross_above, cross_below


class TVHullMACross(Strategy):
    metadata = StrategyMetadata(
        id="tradingview.hull_ma_cross",
        name="TradingView Hull MA Cross",
        description="Hull MA fast/slow cross (low-lag MA system).",
        source="tradingview",
        source_url="https://alanhull.com/hull-moving-average",
        license="MIT",
        version="1.0.0",
        timeframes=["1h", "4h"],
        asset_classes=["crypto_perp"],
        risk_notes="Less laggy = more whipsaws in chop. Pair with trend filter.",
    )
    params = {
        "fast_period": 9,
        "slow_period": 21,
        "stop_loss_atr_multiplier": 2.0,
        "take_profit_rr_ratio": 2.0,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "fast_period": [5, 30],
        "slow_period": [15, 90],
        "stop_loss_atr_multiplier": [1.5, 3.5],
        "take_profit_rr_ratio": [1.5, 4.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def _hma(self, closes, period):
        half = max(2, period // 2)
        sqrt_p = max(2, int(math.sqrt(period)))
        e_half = ema(closes, half)
        e_full = ema(closes, period)
        diff = []
        for a, b in zip(e_half, e_full):
            diff.append(2 * a - b if (a is not None and b is not None) else None)
        valid = [v for v in diff if v is not None]
        smoothed = ema(valid, sqrt_p) if len(valid) >= sqrt_p else [None] * len(valid)
        result = [None] * (len(diff) - len(smoothed)) + smoothed
        return result

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        return {
            "hma_fast": self._hma(ohlcv["close"], int(p["fast_period"])),
            "hma_slow": self._hma(ohlcv["close"], int(p["slow_period"])),
        }

    def entry_signal(self, indicators, last_bar) -> Optional[EntrySignal]:
        f = indicators["hma_fast"]; s = indicators["hma_slow"]
        if len(f) < 3 or f[-1] is None or s[-1] is None or f[-2] is None or s[-2] is None:
            return None
        if cross_above(f, s):
            return EntrySignal(direction="long", confidence=66.0,
                               reasons=["HMA fast crossed above slow"],
                               tags=["ma_cross", "trend_follow"])
        if cross_below(f, s):
            return EntrySignal(direction="short", confidence=66.0,
                               reasons=["HMA fast crossed below slow"],
                               tags=["ma_cross", "trend_follow"])
        return None
