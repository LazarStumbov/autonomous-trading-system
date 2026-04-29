"""MACD Cross v1 — basic MACD line crosses signal line.

Pattern origin: Gerald Appel, "Technical Analysis: Power Tools for Active Investors".
Source URL:     https://github.com/freqtrade/freqtrade-strategies (MACD strategies)
License:        GPLv3 (preserved from upstream freqtrade-strategies repo).
                This file MUST NOT import from non-GPL parts of our codebase
                beyond lib.strategy_engine + lib.technical_indicators (both MIT,
                mere-aggregation OK).
"""

from __future__ import annotations
from typing import Optional
from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import macd, ema, atr, cross_above, cross_below


class MacdCrossV1(Strategy):
    metadata = StrategyMetadata(
        id="freqtrade.macd_cross_v1",
        name="MACD Line Cross",
        description="MACD line crosses signal line, EMA200 trend filter.",
        source="freqtrade",
        source_url="https://github.com/freqtrade/freqtrade-strategies",
        license="GPLv3",
        version="1.0.0",
        timeframes=["1h", "4h"],
        asset_classes=["crypto_perp"],
        risk_notes="MACD lags. Use EMA200 to avoid against-trend trades.",
    )
    params = {
        "fast": 12,
        "slow": 26,
        "signal": 9,
        "trend_period": 200,
        "stop_loss_atr_multiplier": 2.0,
        "take_profit_rr_ratio": 2.0,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "fast": [6, 16],
        "slow": [18, 40],
        "signal": [5, 13],
        "trend_period": [100, 300],
        "stop_loss_atr_multiplier": [1.0, 4.0],
        "take_profit_rr_ratio": [1.5, 4.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        c = ohlcv["close"]
        return {
            "macd": macd(c, int(p["fast"]), int(p["slow"]), int(p["signal"])),
            "ema_trend": ema(c, int(p["trend_period"])),
            "atr_14": atr(ohlcv["high"], ohlcv["low"], c, 14),
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        m = indicators["macd"]["macd"]
        s = indicators["macd"]["signal"]
        t = indicators["ema_trend"]
        if len(m) < 2 or t[-1] is None:
            return None
        price = last_bar["close"]
        if cross_above(m, s) and price > t[-1]:
            return EntrySignal(direction="long", confidence=66.0,
                               reasons=["MACD bullish cross", "above EMA200"],
                               tags=["momentum", "macd"])
        if cross_below(m, s) and price < t[-1]:
            return EntrySignal(direction="short", confidence=64.0,
                               reasons=["MACD bearish cross", "below EMA200"],
                               tags=["momentum", "macd"])
        return None
