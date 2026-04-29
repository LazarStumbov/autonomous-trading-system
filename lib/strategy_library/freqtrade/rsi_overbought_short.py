"""RSI Overbought Short — fade RSI extremes against weak trend.

Pattern origin: J. Welles Wilder Jr., "New Concepts in Technical Trading Systems".
Source URL:     https://github.com/freqtrade/freqtrade-strategies
License:        GPLv3 (preserved from upstream freqtrade-strategies repo).
                This file MUST NOT import from non-GPL parts of our codebase
                beyond lib.strategy_engine + lib.technical_indicators (both MIT,
                mere-aggregation OK).
"""

from __future__ import annotations
from typing import Optional
from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import rsi, ema, atr


class RsiOverboughtShort(Strategy):
    metadata = StrategyMetadata(
        id="freqtrade.rsi_overbought_short",
        name="RSI Overbought Short Fade",
        description="Short when RSI(14) > 75 AND price below EMA200 (counter-rally fade).",
        source="freqtrade",
        source_url="https://github.com/freqtrade/freqtrade-strategies",
        license="GPLv3",
        version="1.0.0",
        timeframes=["1h", "4h"],
        asset_classes=["crypto_perp"],
        risk_notes="Short-only fade. Strong trends can stay overbought.",
    )
    params = {
        "rsi_threshold": 75.0,
        "trend_period": 200,
        "stop_loss_atr_multiplier": 1.8,
        "take_profit_rr_ratio": 1.8,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "rsi_threshold": [65.0, 85.0],
        "trend_period": [100, 300],
        "stop_loss_atr_multiplier": [1.0, 3.5],
        "take_profit_rr_ratio": [1.2, 3.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        c = ohlcv["close"]
        return {
            "rsi": rsi(c, 14),
            "ema_trend": ema(c, int(p["trend_period"])),
            "atr_14": atr(ohlcv["high"], ohlcv["low"], c, 14),
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        p = self._effective_params
        r = indicators["rsi"]
        et = indicators["ema_trend"][-1]
        if not r or r[-1] is None or et is None:
            return None
        if last_bar["close"] < et and r[-1] >= p["rsi_threshold"]:
            return EntrySignal(direction="short", confidence=66.0,
                               reasons=[f"RSI {r[-1]:.1f} >= {p['rsi_threshold']}", "below EMA200"],
                               tags=["mean_reversion", "fade"])
        return None
