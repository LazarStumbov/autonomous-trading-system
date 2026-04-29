"""VWAP Pullback — pullback to session VWAP in established trend.

Pattern origin: classic VWAP-anchored intraday strategy (institutional execution benchmark).
Source URL:     https://github.com/freqtrade/freqtrade-strategies
License:        GPLv3 (preserved from upstream freqtrade-strategies repo).
                This file MUST NOT import from non-GPL parts of our codebase
                beyond lib.strategy_engine + lib.technical_indicators (both MIT,
                mere-aggregation OK).
"""

from __future__ import annotations
from typing import Optional
from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import vwap, ema, atr, rsi


class VwapPullback(Strategy):
    metadata = StrategyMetadata(
        id="freqtrade.vwap_pullback",
        name="VWAP Pullback Trend",
        description="In uptrend (price>EMA50), buy when price touches VWAP from above with RSI not oversold.",
        source="freqtrade",
        source_url="https://github.com/freqtrade/freqtrade-strategies",
        license="GPLv3",
        version="1.0.0",
        timeframes=["15m", "1h"],
        asset_classes=["crypto_perp"],
        risk_notes="Cumulative VWAP works on intraday timeframes.",
    )
    params = {
        "ema_period": 50,
        "rsi_min": 35.0,
        "stop_loss_atr_multiplier": 1.5,
        "take_profit_rr_ratio": 2.0,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "ema_period": [20, 100],
        "rsi_min": [25.0, 50.0],
        "stop_loss_atr_multiplier": [1.0, 3.0],
        "take_profit_rr_ratio": [1.5, 3.5],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        c = ohlcv["close"]
        return {
            "vwap": vwap(ohlcv["high"], ohlcv["low"], c, ohlcv["volume"]),
            "ema_trend": ema(c, int(p["ema_period"])),
            "rsi": rsi(c, 14),
            "atr_14": atr(ohlcv["high"], ohlcv["low"], c, 14),
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        p = self._effective_params
        v = indicators["vwap"][-1]
        et = indicators["ema_trend"][-1]
        r = indicators["rsi"][-1]
        if None in (v, et, r):
            return None
        price = last_bar["close"]
        low = last_bar["low"]
        if price > et and low <= v <= price and r >= p["rsi_min"]:
            return EntrySignal(direction="long", confidence=70.0,
                               reasons=["uptrend", "VWAP pullback touch", f"RSI {r:.1f}"],
                               tags=["trend_follow", "vwap"])
        high = last_bar["high"]
        if price < et and high >= v >= price and r <= 100 - p["rsi_min"]:
            return EntrySignal(direction="short", confidence=68.0,
                               reasons=["downtrend", "VWAP pullback touch", f"RSI {r:.1f}"],
                               tags=["trend_follow", "vwap"])
        return None
