"""Heikin-Ashi pullback in trend (community pattern, no single attribution).

Pattern origin:  Heikin Ashi candles smooth out noise; common community pattern
                 is to wait for a counter-coloured HA candle inside an established
                 HA trend, then enter on resumption. Many open-source TradingView
                 scripts implement variants.
License:         MIT (our impl).
"""

from __future__ import annotations
from typing import Optional

from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import ema


class HeikinAshiPullback(Strategy):
    metadata = StrategyMetadata(
        id="community.heikin_ashi_pullback",
        name="Heikin Ashi Pullback in Trend",
        description="Counter-HA candle in established HA trend = pullback long/short.",
        source="community",
        source_url="https://en.wikipedia.org/wiki/Candlestick_chart#Heikin-Ashi",
        license="MIT",
        version="1.0.0",
        timeframes=["1h", "4h"],
        asset_classes=["crypto_perp"],
        risk_notes="HA smooths but lags real OHLC; never use HA closes for execution.",
    )
    params = {
        "trend_lookback": 5,
        "ema_filter": 50,
        "stop_loss_atr_multiplier": 2.0,
        "take_profit_rr_ratio": 2.0,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "trend_lookback": [3, 15],
        "ema_filter": [20, 200],
        "stop_loss_atr_multiplier": [1.5, 3.5],
        "take_profit_rr_ratio": [1.5, 4.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def _heikin_ashi(self, ohlcv):
        O = ohlcv["open"]; H = ohlcv["high"]; L = ohlcv["low"]; C = ohlcv["close"]
        ha_open = [O[0]]; ha_close = [(O[0] + H[0] + L[0] + C[0]) / 4.0]
        ha_high = [H[0]]; ha_low = [L[0]]
        for i in range(1, len(C)):
            hc = (O[i] + H[i] + L[i] + C[i]) / 4.0
            ho = (ha_open[-1] + ha_close[-1]) / 2.0
            ha_open.append(ho); ha_close.append(hc)
            ha_high.append(max(H[i], ho, hc))
            ha_low.append(min(L[i], ho, hc))
        return ha_open, ha_high, ha_low, ha_close

    def populate_indicators(self, ohlcv: dict) -> dict:
        ho, hh, hl, hc = self._heikin_ashi(ohlcv)
        e = ema(ohlcv["close"], int(self._effective_params["ema_filter"]))
        return {"ha_open": ho, "ha_close": hc, "ema": e}

    def entry_signal(self, indicators, last_bar) -> Optional[EntrySignal]:
        p = self._effective_params
        n = int(p["trend_lookback"])
        ho = indicators["ha_open"]; hc = indicators["ha_close"]; e = indicators["ema"]
        if len(ho) < n + 1 or e[-1] is None:
            return None
        # prior n-1 bars trend (excluding current)
        prior = list(zip(ho[-n - 1:-1], hc[-n - 1:-1]))
        bull_count = sum(1 for o, c in prior if c > o)
        bear_count = len(prior) - bull_count
        cur_o, cur_c = ho[-1], hc[-1]
        c = last_bar["close"]
        # Long: bull HA trend + this bar is counter (red HA) but real close > EMA
        if bull_count >= n - 1 and cur_c < cur_o and c > e[-1]:
            return EntrySignal(direction="long", confidence=64.0,
                               reasons=[f"HA bull trend {bull_count}/{n}; counter HA candle"],
                               tags=["heikin_ashi", "pullback"])
        if bear_count >= n - 1 and cur_c > cur_o and c < e[-1]:
            return EntrySignal(direction="short", confidence=64.0,
                               reasons=[f"HA bear trend {bear_count}/{n}; counter HA candle"],
                               tags=["heikin_ashi", "pullback"])
        return None
