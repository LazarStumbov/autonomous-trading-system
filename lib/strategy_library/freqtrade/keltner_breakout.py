"""Keltner Channel Breakout — close outside Keltner band signals trend acceleration.

Pattern origin: Chester W. Keltner, "How to Make Money in Commodities" (1960).
Source URL:     https://github.com/freqtrade/freqtrade-strategies (Keltner variants)
License:        GPLv3 (preserved from upstream freqtrade-strategies repo).
                This file MUST NOT import from non-GPL parts of our codebase
                beyond lib.strategy_engine + lib.technical_indicators (both MIT,
                mere-aggregation OK).
Notes:          Keltner = EMA ± multiplier × ATR. We synthesize from helpers.
"""

from __future__ import annotations
from typing import Optional
from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import ema, atr, volume_ratio


class KeltnerBreakout(Strategy):
    metadata = StrategyMetadata(
        id="freqtrade.keltner_breakout",
        name="Keltner Channel Breakout",
        description="Long when close > EMA + k*ATR; short when close < EMA - k*ATR.",
        source="freqtrade",
        source_url="https://github.com/freqtrade/freqtrade-strategies",
        license="GPLv3",
        version="1.0.0",
        timeframes=["1h", "4h"],
        asset_classes=["crypto_perp"],
        risk_notes="Volatility expansion play. False breakouts in chop.",
    )
    params = {
        "ema_period": 20,
        "atr_period": 10,
        "multiplier": 2.0,
        "min_volume_ratio": 1.2,
        "stop_loss_atr_multiplier": 2.0,
        "take_profit_rr_ratio": 2.5,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "ema_period": [10, 50],
        "atr_period": [7, 21],
        "multiplier": [1.0, 3.0],
        "min_volume_ratio": [0.8, 2.5],
        "stop_loss_atr_multiplier": [1.5, 4.0],
        "take_profit_rr_ratio": [1.5, 4.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        c = ohlcv["close"]
        return {
            "ema_mid": ema(c, int(p["ema_period"])),
            "atr_k": atr(ohlcv["high"], ohlcv["low"], c, int(p["atr_period"])),
            "atr_14": atr(ohlcv["high"], ohlcv["low"], c, 14),
            "vol_ratio": volume_ratio(ohlcv["volume"], 20),
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        p = self._effective_params
        mid = indicators["ema_mid"][-1]
        a = indicators["atr_k"][-1]
        if mid is None or a is None:
            return None
        if indicators["vol_ratio"] < p["min_volume_ratio"]:
            return None
        price = last_bar["close"]
        upper = mid + p["multiplier"] * a
        lower = mid - p["multiplier"] * a
        if price > upper:
            return EntrySignal(direction="long", confidence=70.0,
                               reasons=["close > Keltner upper", f"vol {indicators['vol_ratio']:.2f}x"],
                               tags=["breakout", "keltner"])
        if price < lower:
            return EntrySignal(direction="short", confidence=68.0,
                               reasons=["close < Keltner lower", f"vol {indicators['vol_ratio']:.2f}x"],
                               tags=["breakout", "keltner"])
        return None
