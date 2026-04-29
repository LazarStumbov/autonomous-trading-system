"""Range Filter Break — multi-bar range, breakout in trend direction.

Pattern origin: Donovan Wall "Range Filter" indicator family (TradingView).
Source URL:     https://github.com/freqtrade/freqtrade-strategies
License:        GPLv3 (preserved from upstream freqtrade-strategies repo).
                This file MUST NOT import from non-GPL parts of our codebase
                beyond lib.strategy_engine + lib.technical_indicators (both MIT,
                mere-aggregation OK).
"""

from __future__ import annotations
from typing import Optional
from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import atr, ema


class RangeFilterBreak(Strategy):
    metadata = StrategyMetadata(
        id="freqtrade.range_filter_break",
        name="Range Filter Break",
        description="Price has been within ±k*ATR for N bars; break the band in EMA direction.",
        source="freqtrade",
        source_url="https://github.com/freqtrade/freqtrade-strategies",
        license="GPLv3",
        version="1.0.0",
        timeframes=["1h", "4h"],
        asset_classes=["crypto_perp"],
        risk_notes="Avoid quick re-entries; tighter ATR=more trades.",
    )
    params = {
        "lookback": 20,
        "k_atr": 1.5,
        "trend_period": 50,
        "stop_loss_atr_multiplier": 1.5,
        "take_profit_rr_ratio": 3.0,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "lookback": [10, 50],
        "k_atr": [1.0, 3.0],
        "trend_period": [20, 100],
        "stop_loss_atr_multiplier": [1.0, 3.0],
        "take_profit_rr_ratio": [2.0, 5.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        c = ohlcv["close"]
        return {
            "atr_14": atr(ohlcv["high"], ohlcv["low"], c, 14),
            "ema_trend": ema(c, int(p["trend_period"])),
            "closes": c,
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        p = self._effective_params
        n = int(p["lookback"])
        c = indicators["closes"]
        a = indicators["atr_14"]
        et = indicators["ema_trend"][-1]
        if len(c) < n + 2 or a[-2] is None or et is None:
            return None
        anchor = c[-n - 1]
        atr_val = a[-2]
        upper = anchor + p["k_atr"] * atr_val
        lower = anchor - p["k_atr"] * atr_val
        # Check all closes in range[anchor-n..anchor-1] stayed within [lower, upper]
        if not all(lower <= x <= upper for x in c[-n - 1:-1]):
            return None
        price = last_bar["close"]
        if price > upper and price > et:
            return EntrySignal(direction="long", confidence=72.0,
                               reasons=[f"break of {n}-bar range up"],
                               tags=["breakout", "range"])
        if price < lower and price < et:
            return EntrySignal(direction="short", confidence=70.0,
                               reasons=[f"break of {n}-bar range down"],
                               tags=["breakout", "range"])
        return None
