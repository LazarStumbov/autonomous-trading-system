"""TradingView — Engulfing-Pattern Filter (LonesomeTheBlue style).

Pattern origin:  Bullish/bearish engulfing candle, gated by EMA-200 trend filter.
                 LonesomeTheBlue's open-source pattern detector inspired the gate.
Source URL:      https://www.tradingview.com/u/LonesomeTheBlue/
License:         MIT.
Notes:           Pattern: prior candle red + current green engulfing (long); reverse for short.
                 Trend filter EMA-200 keeps us with the dominant flow.
"""

from __future__ import annotations
from typing import Optional

from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import ema


class TVLonesomeEngulfing(Strategy):
    metadata = StrategyMetadata(
        id="tradingview.lonesome_engulfing",
        name="TradingView Engulfing + EMA200 Trend",
        description="Engulfing candle in direction of EMA-200 trend.",
        source="tradingview",
        source_url="https://www.tradingview.com/u/LonesomeTheBlue/",
        license="MIT",
        version="1.0.0",
        timeframes=["1h", "4h"],
        asset_classes=["crypto_perp"],
        risk_notes="Engulfing alone has thin edge; trend filter is essential.",
    )
    params = {
        "ema_filter": 200,
        "stop_loss_atr_multiplier": 2.0,
        "take_profit_rr_ratio": 2.0,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "ema_filter": [50, 300],
        "stop_loss_atr_multiplier": [1.5, 3.5],
        "take_profit_rr_ratio": [1.5, 4.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        return {"ema": ema(ohlcv["close"], int(p["ema_filter"])),
                "open": ohlcv["open"], "close": ohlcv["close"],
                "high": ohlcv["high"], "low": ohlcv["low"]}

    def entry_signal(self, indicators, last_bar) -> Optional[EntrySignal]:
        e = indicators["ema"]
        if len(e) < 1 or e[-1] is None:
            return None
        O = indicators["open"]; C = indicators["close"]
        if len(O) < 2:
            return None
        prev_open, prev_close = O[-2], C[-2]
        cur_open, cur_close = O[-1], C[-1]
        c = last_bar["close"]
        bull_engulf = (prev_close < prev_open) and (cur_close > cur_open) \
            and (cur_open <= prev_close) and (cur_close >= prev_open)
        bear_engulf = (prev_close > prev_open) and (cur_close < cur_open) \
            and (cur_open >= prev_close) and (cur_close <= prev_open)
        if bull_engulf and c > e[-1]:
            return EntrySignal(direction="long", confidence=64.0,
                               reasons=["bullish engulfing above EMA-200"],
                               tags=["candlestick", "trend_filter"])
        if bear_engulf and c < e[-1]:
            return EntrySignal(direction="short", confidence=64.0,
                               reasons=["bearish engulfing below EMA-200"],
                               tags=["candlestick", "trend_filter"])
        return None
