"""Ichimoku Cloud Lite — simplified cloud trade using Senkou A/B proxies via EMA.

Pattern origin: Goichi Hosoda, "Ichimoku Kinko Hyo" (1969).
Source URL:     https://github.com/freqtrade/freqtrade-strategies
License:        GPLv3 (preserved from upstream freqtrade-strategies repo).
                This file MUST NOT import from non-GPL parts of our codebase
                beyond lib.strategy_engine + lib.technical_indicators (both MIT,
                mere-aggregation OK).
Notes:          We approximate Tenkan/Kijun via EMAs since no helper exists for high/low midpoints.
"""

from __future__ import annotations
from typing import Optional
from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import ema, atr


class IchimokuCloudLite(Strategy):
    metadata = StrategyMetadata(
        id="freqtrade.ichimoku_cloud_lite",
        name="Ichimoku Cloud Lite",
        description="Long above cloud (max(EMA9,EMA26)) with EMA9>EMA26. Mirror for short.",
        source="freqtrade",
        source_url="https://github.com/freqtrade/freqtrade-strategies",
        license="GPLv3",
        version="1.0.0",
        timeframes=["4h", "1d"],
        asset_classes=["crypto_perp"],
        risk_notes="Approximation of full Ichimoku; for higher timeframes only.",
    )
    params = {
        "tenkan": 9,
        "kijun": 26,
        "stop_loss_atr_multiplier": 2.5,
        "take_profit_rr_ratio": 3.0,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "tenkan": [5, 15],
        "kijun": [20, 40],
        "stop_loss_atr_multiplier": [1.5, 4.0],
        "take_profit_rr_ratio": [2.0, 5.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        c = ohlcv["close"]
        return {
            "tenkan": ema(c, int(p["tenkan"])),
            "kijun": ema(c, int(p["kijun"])),
            "atr_14": atr(ohlcv["high"], ohlcv["low"], c, 14),
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        t = indicators["tenkan"][-1]
        k = indicators["kijun"][-1]
        if t is None or k is None:
            return None
        cloud_top = max(t, k)
        cloud_bot = min(t, k)
        price = last_bar["close"]
        if price > cloud_top and t > k:
            return EntrySignal(direction="long", confidence=68.0,
                               reasons=["above cloud", "tenkan>kijun"],
                               tags=["trend_follow", "ichimoku"])
        if price < cloud_bot and t < k:
            return EntrySignal(direction="short", confidence=66.0,
                               reasons=["below cloud", "tenkan<kijun"],
                               tags=["trend_follow", "ichimoku"])
        return None
