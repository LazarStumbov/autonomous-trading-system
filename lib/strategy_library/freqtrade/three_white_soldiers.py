"""Three White Soldiers — three consecutive bullish closes each higher than previous.

Pattern origin: Steve Nison, "Japanese Candlestick Charting Techniques".
Source URL:     https://github.com/freqtrade/freqtrade-strategies
License:        GPLv3 (preserved from upstream freqtrade-strategies repo).
                This file MUST NOT import from non-GPL parts of our codebase
                beyond lib.strategy_engine + lib.technical_indicators (both MIT,
                mere-aggregation OK).
"""

from __future__ import annotations
from typing import Optional
from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import ema, atr, volume_ratio


class ThreeWhiteSoldiers(Strategy):
    metadata = StrategyMetadata(
        id="freqtrade.three_white_soldiers",
        name="Three White Soldiers / Black Crows",
        description="Three consecutive bullish (or bearish) closing higher (lower).",
        source="freqtrade",
        source_url="https://github.com/freqtrade/freqtrade-strategies",
        license="GPLv3",
        version="1.0.0",
        timeframes=["4h", "1d"],
        asset_classes=["crypto_perp"],
        risk_notes="Pattern can mark exhaustion as easily as continuation.",
    )
    params = {
        "trend_period": 50,
        "min_volume_ratio": 1.0,
        "stop_loss_atr_multiplier": 2.0,
        "take_profit_rr_ratio": 2.0,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "trend_period": [20, 100],
        "min_volume_ratio": [0.7, 2.0],
        "stop_loss_atr_multiplier": [1.0, 3.5],
        "take_profit_rr_ratio": [1.2, 3.5],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        return {
            "ema_trend": ema(ohlcv["close"], int(p["trend_period"])),
            "atr_14": atr(ohlcv["high"], ohlcv["low"], ohlcv["close"], 14),
            "vol_ratio": volume_ratio(ohlcv["volume"], 20),
            "opens": ohlcv["open"],
            "closes": ohlcv["close"],
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        p = self._effective_params
        opens = indicators["opens"]
        closes = indicators["closes"]
        et = indicators["ema_trend"][-1]
        if et is None or len(closes) < 4:
            return None
        if indicators["vol_ratio"] < p["min_volume_ratio"]:
            return None
        # Three white soldiers: each bar bullish, each close > prev close
        soldiers_long = all(closes[-i] > opens[-i] for i in range(1, 4)) and \
            closes[-1] > closes[-2] > closes[-3]
        soldiers_short = all(closes[-i] < opens[-i] for i in range(1, 4)) and \
            closes[-1] < closes[-2] < closes[-3]
        price = last_bar["close"]
        if soldiers_long and price > et:
            return EntrySignal(direction="long", confidence=70.0,
                               reasons=["3 white soldiers", "above trend"],
                               tags=["candlestick", "continuation"])
        if soldiers_short and price < et:
            return EntrySignal(direction="short", confidence=68.0,
                               reasons=["3 black crows", "below trend"],
                               tags=["candlestick", "continuation"])
        return None
