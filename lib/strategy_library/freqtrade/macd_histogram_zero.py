"""MACD Histogram Zero-Cross — entry on histogram crossing zero from negative/positive.

Pattern origin: classic MACD histogram zero-cross pattern (Pring).
Source URL:     https://github.com/freqtrade/freqtrade-strategies
License:        GPLv3 (preserved from upstream freqtrade-strategies repo).
                This file MUST NOT import from non-GPL parts of our codebase
                beyond lib.strategy_engine + lib.technical_indicators (both MIT,
                mere-aggregation OK).
"""

from __future__ import annotations
from typing import Optional
from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import macd, atr, ema


class MacdHistogramZero(Strategy):
    metadata = StrategyMetadata(
        id="freqtrade.macd_histogram_zero",
        name="MACD Histogram Zero Cross",
        description="Long when histogram crosses up through 0 with price > EMA100.",
        source="freqtrade",
        source_url="https://github.com/freqtrade/freqtrade-strategies",
        license="GPLv3",
        version="1.0.0",
        timeframes=["1h", "4h"],
        asset_classes=["crypto_perp"],
        risk_notes="Earlier than MACD line cross; more whipsaw risk.",
    )
    params = {
        "trend_period": 100,
        "stop_loss_atr_multiplier": 2.0,
        "take_profit_rr_ratio": 2.0,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "trend_period": [50, 200],
        "stop_loss_atr_multiplier": [1.0, 4.0],
        "take_profit_rr_ratio": [1.5, 4.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        c = ohlcv["close"]
        return {
            "macd": macd(c),
            "ema_trend": ema(c, int(p["trend_period"])),
            "atr_14": atr(ohlcv["high"], ohlcv["low"], c, 14),
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        h = indicators["macd"]["histogram"]
        et = indicators["ema_trend"]
        if len(h) < 2 or h[-1] is None or h[-2] is None or et[-1] is None:
            return None
        price = last_bar["close"]
        if h[-2] <= 0 and h[-1] > 0 and price > et[-1]:
            return EntrySignal(direction="long", confidence=66.0,
                               reasons=["MACD hist crossed 0 up", "above trend"],
                               tags=["momentum"])
        if h[-2] >= 0 and h[-1] < 0 and price < et[-1]:
            return EntrySignal(direction="short", confidence=64.0,
                               reasons=["MACD hist crossed 0 down", "below trend"],
                               tags=["momentum"])
        return None
