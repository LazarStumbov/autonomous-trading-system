"""Awesome+MACD Combo — MACD momentum confirmed by SMA34/SMA5 (Awesome Oscillator proxy).

Pattern origin: Bill Williams' Awesome Oscillator (SMA5(median) - SMA34(median)).
Source URL:     https://github.com/freqtrade/freqtrade-strategies
License:        GPLv3 (preserved from upstream freqtrade-strategies repo).
                This file MUST NOT import from non-GPL parts of our codebase
                beyond lib.strategy_engine + lib.technical_indicators (both MIT,
                mere-aggregation OK).
Notes:          AO computed inline from helpers.
"""

from __future__ import annotations
from typing import Optional
from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import macd, sma, atr


class AwesomeMacdCombo(Strategy):
    metadata = StrategyMetadata(
        id="freqtrade.awesome_macd_combo",
        name="Awesome Oscillator + MACD",
        description="Both AO and MACD histogram positive (long) or negative (short) and rising.",
        source="freqtrade",
        source_url="https://github.com/freqtrade/freqtrade-strategies",
        license="GPLv3",
        version="1.0.0",
        timeframes=["1h", "4h"],
        asset_classes=["crypto_perp"],
        risk_notes="Two-momentum-indicator confluence reduces false signals.",
    )
    params = {
        "stop_loss_atr_multiplier": 2.0,
        "take_profit_rr_ratio": 2.5,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "stop_loss_atr_multiplier": [1.0, 4.0],
        "take_profit_rr_ratio": [1.5, 4.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        median = [(h + l) / 2 for h, l in zip(ohlcv["high"], ohlcv["low"])]
        sma5 = sma(median, 5)
        sma34 = sma(median, 34)
        ao = [(a - b) if (a is not None and b is not None) else None for a, b in zip(sma5, sma34)]
        return {
            "ao": ao,
            "macd": macd(ohlcv["close"]),
            "atr_14": atr(ohlcv["high"], ohlcv["low"], ohlcv["close"], 14),
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        ao = indicators["ao"]
        hist = indicators["macd"]["histogram"]
        if len(ao) < 2 or len(hist) < 2:
            return None
        if None in (ao[-1], ao[-2], hist[-1], hist[-2]):
            return None
        if ao[-1] > 0 and ao[-1] > ao[-2] and hist[-1] > 0 and hist[-1] > hist[-2]:
            return EntrySignal(direction="long", confidence=72.0,
                               reasons=["AO rising positive", "MACD hist rising positive"],
                               tags=["momentum", "ao_macd"])
        if ao[-1] < 0 and ao[-1] < ao[-2] and hist[-1] < 0 and hist[-1] < hist[-2]:
            return EntrySignal(direction="short", confidence=70.0,
                               reasons=["AO falling negative", "MACD hist falling negative"],
                               tags=["momentum", "ao_macd"])
        return None
