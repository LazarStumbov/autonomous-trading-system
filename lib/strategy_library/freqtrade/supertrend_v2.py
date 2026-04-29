"""Supertrend v2 — supertrend flip with EMA trend confirmation.

Pattern origin: Olivier Seban, Supertrend (popularized via TradingView).
Source URL:     https://github.com/freqtrade/freqtrade-strategies
License:        GPLv3 (preserved from upstream freqtrade-strategies repo).
                This file MUST NOT import from non-GPL parts of our codebase
                beyond lib.strategy_engine + lib.technical_indicators (both MIT,
                mere-aggregation OK).
"""

from __future__ import annotations
from typing import Optional
from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import supertrend, ema, atr


class SupertrendV2(Strategy):
    metadata = StrategyMetadata(
        id="freqtrade.supertrend_v2",
        name="Supertrend Flip v2",
        description="Trade Supertrend flip only when EMA100 confirms direction.",
        source="freqtrade",
        source_url="https://github.com/freqtrade/freqtrade-strategies",
        license="GPLv3",
        version="1.0.0",
        timeframes=["1h", "4h"],
        asset_classes=["crypto_perp"],
        risk_notes="Trend filter avoids counter-trend flips.",
    )
    params = {
        "st_period": 10,
        "st_multiplier": 3.0,
        "trend_period": 100,
        "stop_loss_atr_multiplier": 2.5,
        "take_profit_rr_ratio": 2.5,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "st_period": [7, 20],
        "st_multiplier": [2.0, 4.0],
        "trend_period": [50, 200],
        "stop_loss_atr_multiplier": [1.5, 4.0],
        "take_profit_rr_ratio": [1.5, 4.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        c = ohlcv["close"]
        return {
            "st": supertrend(ohlcv["high"], ohlcv["low"], c, int(p["st_period"]), p["st_multiplier"]),
            "ema_trend": ema(c, int(p["trend_period"])),
            "atr_14": atr(ohlcv["high"], ohlcv["low"], c, 14),
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        st = indicators["st"]["trend"]
        et = indicators["ema_trend"][-1]
        if len(st) < 2 or et is None:
            return None
        price = last_bar["close"]
        if st[-2] == -1 and st[-1] == 1 and price > et:
            return EntrySignal(direction="long", confidence=72.0,
                               reasons=["Supertrend flip bullish", "above EMA100"],
                               tags=["trend_follow", "supertrend"])
        if st[-2] == 1 and st[-1] == -1 and price < et:
            return EntrySignal(direction="short", confidence=70.0,
                               reasons=["Supertrend flip bearish", "below EMA100"],
                               tags=["trend_follow", "supertrend"])
        return None
