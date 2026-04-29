"""TradingView — Supertrend Pullback (KivancOzbilgic-style).

Pattern origin:  Olivier Seban "Supertrend"; popularised by KivancOzbilgic on TV.
Source URL:      https://www.tradingview.com/script/r6dAP7yi/
License:         MIT (our impl).
Notes:           Long when supertrend is bullish AND close pulls back to
                 within 0.5*ATR of supertrend value (better R:R than naive flip).
"""

from __future__ import annotations
from typing import Optional

from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import supertrend, atr


class TVSupertrendPullback(Strategy):
    metadata = StrategyMetadata(
        id="tradingview.supertrend_pullback",
        name="TradingView Supertrend Pullback",
        description="Wait for supertrend trend + close near supertrend line for entry.",
        source="tradingview",
        source_url="https://www.tradingview.com/script/r6dAP7yi/",
        license="MIT",
        version="1.0.0",
        timeframes=["1h", "4h"],
        asset_classes=["crypto_perp"],
        risk_notes="Misses pure breakouts; works best in established trends.",
    )
    params = {
        "st_period": 10,
        "st_mult": 3.0,
        "pullback_atr_frac": 0.5,
        "stop_loss_atr_multiplier": 2.0,
        "take_profit_rr_ratio": 2.5,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "st_period": [7, 20],
        "st_mult": [2.0, 5.0],
        "pullback_atr_frac": [0.2, 1.5],
        "stop_loss_atr_multiplier": [1.5, 3.5],
        "take_profit_rr_ratio": [1.5, 4.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        st = supertrend(ohlcv["high"], ohlcv["low"], ohlcv["close"],
                        int(p["st_period"]), p["st_mult"])
        a = atr(ohlcv["high"], ohlcv["low"], ohlcv["close"], 14)
        return {"st_trend": st["trend"], "st_value": st["line"], "atr": a}

    def entry_signal(self, indicators, last_bar) -> Optional[EntrySignal]:
        trend = indicators["st_trend"]; val = indicators["st_value"]; a = indicators["atr"]
        if not trend or trend[-1] is None or val[-1] is None or a[-1] is None:
            return None
        p = self._effective_params
        c = last_bar["close"]
        proximity = p["pullback_atr_frac"] * a[-1]
        if trend[-1] == 1 and abs(c - val[-1]) <= proximity and c > val[-1]:
            return EntrySignal(direction="long", confidence=70.0,
                               reasons=[f"bullish supertrend, pullback within {p['pullback_atr_frac']}*ATR"],
                               tags=["trend_follow", "pullback"])
        if trend[-1] == -1 and abs(c - val[-1]) <= proximity and c < val[-1]:
            return EntrySignal(direction="short", confidence=70.0,
                               reasons=[f"bearish supertrend, pullback within {p['pullback_atr_frac']}*ATR"],
                               tags=["trend_follow", "pullback"])
        return None
