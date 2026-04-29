"""NR4 Breakout — narrowest range of last 4 bars precedes expansion.

Pattern origin: Tony Crabel, "Day Trading with Short Term Price Patterns and Opening Range Breakout".
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


class Nr4Breakout(Strategy):
    metadata = StrategyMetadata(
        id="freqtrade.nr4_breakout",
        name="NR4 Range Compression Breakout",
        description="Previous bar had narrowest range of last 4. Trade break of that bar.",
        source="freqtrade",
        source_url="https://github.com/freqtrade/freqtrade-strategies",
        license="GPLv3",
        version="1.0.0",
        timeframes=["1h", "4h", "1d"],
        asset_classes=["crypto_perp", "stock_equity"],
        risk_notes="Use tight stop = mother-bar opposite extreme.",
    )
    params = {
        "lookback": 4,
        "trend_period": 50,
        "stop_loss_atr_multiplier": 1.5,
        "take_profit_rr_ratio": 2.5,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "lookback": [4, 7],
        "trend_period": [20, 100],
        "stop_loss_atr_multiplier": [1.0, 3.0],
        "take_profit_rr_ratio": [1.5, 4.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        return {
            "ema_trend": ema(ohlcv["close"], int(p["trend_period"])),
            "atr_14": atr(ohlcv["high"], ohlcv["low"], ohlcv["close"], 14),
            "highs": ohlcv["high"],
            "lows": ohlcv["low"],
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        p = self._effective_params
        n = int(p["lookback"])
        highs = indicators["highs"]
        lows = indicators["lows"]
        if len(highs) < n + 2:
            return None
        # Look at bar -2 (the "NR" bar). Range of last n bars ending at -2
        ranges = [highs[-2 - i] - lows[-2 - i] for i in range(n)]
        nr_range = highs[-2] - lows[-2]
        if nr_range > min(ranges):
            return None
        et = indicators["ema_trend"][-1]
        if et is None:
            return None
        price = last_bar["close"]
        if price > highs[-2] and price > et:
            return EntrySignal(direction="long", confidence=72.0,
                               reasons=[f"NR{n} break up"],
                               tags=["price_action", "compression"])
        if price < lows[-2] and price < et:
            return EntrySignal(direction="short", confidence=70.0,
                               reasons=[f"NR{n} break down"],
                               tags=["price_action", "compression"])
        return None
