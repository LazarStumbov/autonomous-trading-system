"""BB Width Squeeze — trade volatility expansion after compression.

Pattern origin: John Bollinger, "Bollinger on Bollinger Bands" (squeeze concept).
Source URL:     https://github.com/freqtrade/freqtrade-strategies (squeeze variants)
License:        GPLv3 (preserved from upstream freqtrade-strategies repo).
                This file MUST NOT import from non-GPL parts of our codebase
                beyond lib.strategy_engine + lib.technical_indicators (both MIT,
                mere-aggregation OK).
"""

from __future__ import annotations
from typing import Optional
from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import bollinger_bands, atr, ema


class BbWidthSqueeze(Strategy):
    metadata = StrategyMetadata(
        id="freqtrade.bb_width_squeeze",
        name="BB Width Squeeze Breakout",
        description="Enter on close outside BB after width is at multi-bar low (compression).",
        source="freqtrade",
        source_url="https://github.com/freqtrade/freqtrade-strategies",
        license="GPLv3",
        version="1.0.0",
        timeframes=["1h", "4h"],
        asset_classes=["crypto_perp"],
        risk_notes="Direction not given by squeeze itself; close decides.",
    )
    params = {
        "bb_period": 20,
        "bb_std": 2.0,
        "lookback_squeeze": 50,
        "stop_loss_atr_multiplier": 1.8,
        "take_profit_rr_ratio": 3.0,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "bb_period": [10, 30],
        "bb_std": [1.5, 2.5],
        "lookback_squeeze": [20, 100],
        "stop_loss_atr_multiplier": [1.0, 3.0],
        "take_profit_rr_ratio": [2.0, 5.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        return {
            "bb": bollinger_bands(ohlcv["close"], int(p["bb_period"]), p["bb_std"]),
            "ema_50": ema(ohlcv["close"], 50),
            "atr_14": atr(ohlcv["high"], ohlcv["low"], ohlcv["close"], 14),
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        p = self._effective_params
        bb = indicators["bb"]
        widths = bb["width"]
        n = int(p["lookback_squeeze"])
        if len(widths) < n + 1 or widths[-2] is None:
            return None
        recent_widths = [w for w in widths[-n - 1:-1] if w is not None]
        if len(recent_widths) < n // 2:
            return None
        # Squeeze: previous bar width was at minimum of recent N bars
        if widths[-2] > min(recent_widths):
            return None
        price = last_bar["close"]
        upper = bb["upper"][-1]
        lower = bb["lower"][-1]
        ema50 = indicators["ema_50"][-1]
        if upper is None or lower is None or ema50 is None:
            return None
        if price > upper:
            return EntrySignal(direction="long", confidence=72.0,
                               reasons=["BB squeeze release upward"],
                               tags=["volatility", "squeeze", "breakout"])
        if price < lower:
            return EntrySignal(direction="short", confidence=70.0,
                               reasons=["BB squeeze release downward"],
                               tags=["volatility", "squeeze", "breakout"])
        return None
