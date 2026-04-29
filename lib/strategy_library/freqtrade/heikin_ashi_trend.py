"""Heikin Ashi Trend — synthetic HA candle smooth trend follower.

Pattern origin: Dan Valcu, "Heikin-Ashi: How to Trade Without Candlestick Patterns".
Source URL:     https://github.com/freqtrade/freqtrade-strategies (HA strategies)
License:        GPLv3 (preserved from upstream freqtrade-strategies repo).
                This file MUST NOT import from non-GPL parts of our codebase
                beyond lib.strategy_engine + lib.technical_indicators (both MIT,
                mere-aggregation OK).
Notes:          We compute HA closes inline since no helper exists.
"""

from __future__ import annotations
from typing import Optional
from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import ema, atr


class HeikinAshiTrend(Strategy):
    metadata = StrategyMetadata(
        id="freqtrade.heikin_ashi_trend",
        name="Heikin Ashi Trend",
        description="Enter on 3 consecutive same-color HA candles with EMA50 alignment.",
        source="freqtrade",
        source_url="https://github.com/freqtrade/freqtrade-strategies",
        license="GPLv3",
        version="1.0.0",
        timeframes=["1h", "4h"],
        asset_classes=["crypto_perp"],
        risk_notes="HA smooths but lags. Avoid in chop.",
    )
    params = {
        "consecutive": 3,
        "ema_trend": 50,
        "stop_loss_atr_multiplier": 2.2,
        "take_profit_rr_ratio": 2.5,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "consecutive": [2, 5],
        "ema_trend": [20, 100],
        "stop_loss_atr_multiplier": [1.5, 4.0],
        "take_profit_rr_ratio": [1.5, 4.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        opens, highs, lows, closes = ohlcv["open"], ohlcv["high"], ohlcv["low"], ohlcv["close"]
        ha_close = []
        ha_open = []
        for i in range(len(closes)):
            ha_close.append((opens[i] + highs[i] + lows[i] + closes[i]) / 4)
            if i == 0:
                ha_open.append((opens[i] + closes[i]) / 2)
            else:
                ha_open.append((ha_open[-1] + ha_close[-2]) / 2)
        return {
            "ha_open": ha_open,
            "ha_close": ha_close,
            "ema_trend": ema(closes, int(p["ema_trend"])),
            "atr_14": atr(highs, lows, closes, 14),
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        p = self._effective_params
        ho = indicators["ha_open"]
        hc = indicators["ha_close"]
        et = indicators["ema_trend"]
        n = int(p["consecutive"])
        if len(hc) < n + 1 or et[-1] is None:
            return None
        bullish = all(hc[-i] > ho[-i] for i in range(1, n + 1))
        bearish = all(hc[-i] < ho[-i] for i in range(1, n + 1))
        price = last_bar["close"]
        if bullish and price > et[-1]:
            return EntrySignal(direction="long", confidence=68.0,
                               reasons=[f"{n} bull HA candles", "above EMA trend"],
                               tags=["trend_follow", "heikin_ashi"])
        if bearish and price < et[-1]:
            return EntrySignal(direction="short", confidence=66.0,
                               reasons=[f"{n} bear HA candles", "below EMA trend"],
                               tags=["trend_follow", "heikin_ashi"])
        return None
