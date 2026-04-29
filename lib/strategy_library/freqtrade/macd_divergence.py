"""MACD Divergence — price new low/high but MACD doesn't confirm.

Pattern origin: classic divergence concept (Murphy "Technical Analysis").
Source URL:     https://github.com/freqtrade/freqtrade-strategies
License:        GPLv3 (preserved from upstream freqtrade-strategies repo).
                This file MUST NOT import from non-GPL parts of our codebase
                beyond lib.strategy_engine + lib.technical_indicators (both MIT,
                mere-aggregation OK).
Notes:          Simple two-pivot heuristic; not a full divergence engine.
"""

from __future__ import annotations
from typing import Optional
from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import macd, atr


class MacdDivergence(Strategy):
    metadata = StrategyMetadata(
        id="freqtrade.macd_divergence",
        name="MACD Divergence Reversal",
        description="Price new low over N bars but MACD higher = bullish divergence (mirror for short).",
        source="freqtrade",
        source_url="https://github.com/freqtrade/freqtrade-strategies",
        license="GPLv3",
        version="1.0.0",
        timeframes=["1h", "4h"],
        asset_classes=["crypto_perp"],
        risk_notes="Counter-trend; tight stop required.",
    )
    params = {
        "lookback": 20,
        "stop_loss_atr_multiplier": 1.8,
        "take_profit_rr_ratio": 2.0,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "lookback": [10, 40],
        "stop_loss_atr_multiplier": [1.0, 3.0],
        "take_profit_rr_ratio": [1.5, 3.5],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        c = ohlcv["close"]
        return {
            "macd": macd(c),
            "atr_14": atr(ohlcv["high"], ohlcv["low"], c, 14),
            "closes": c,
            "highs": ohlcv["high"],
            "lows": ohlcv["low"],
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        p = self._effective_params
        n = int(p["lookback"])
        m = indicators["macd"]["macd"]
        lows = indicators["lows"]
        highs = indicators["highs"]
        if len(m) < n + 1 or m[-1] is None:
            return None
        # Find lowest-low in lookback window (excluding current)
        recent_lows = lows[-n - 1:-1]
        recent_highs = highs[-n - 1:-1]
        recent_macd = [v for v in m[-n - 1:-1] if v is not None]
        if not recent_macd:
            return None
        cur_low = last_bar["low"]
        cur_high = last_bar["high"]
        # Bullish divergence: cur low < min(recent), but cur macd > min(recent macd)
        if cur_low < min(recent_lows) and m[-1] > min(recent_macd):
            return EntrySignal(direction="long", confidence=68.0,
                               reasons=["bullish MACD divergence"],
                               tags=["divergence", "reversal"])
        if cur_high > max(recent_highs) and m[-1] < max(recent_macd):
            return EntrySignal(direction="short", confidence=66.0,
                               reasons=["bearish MACD divergence"],
                               tags=["divergence", "reversal"])
        return None
