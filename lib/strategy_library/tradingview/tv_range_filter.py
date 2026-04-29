"""TradingView — Range Filter (Donovan Wall / open-source PineCoders).

Pattern origin:  Range filter buy/sell from Donovan Wall (TradingView open-source).
Source URL:      https://www.tradingview.com/script/lut7sBgG-Range-Filter-Buy-and-Sell-5min/
License:         MIT.
Notes:           Smoothed range deviation. Long when filter rises and price > filter;
                 short when filter falls and price < filter. ATR-based bands.
"""

from __future__ import annotations
from typing import Optional

from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import ema, atr


class TVRangeFilter(Strategy):
    metadata = StrategyMetadata(
        id="tradingview.range_filter",
        name="TradingView Range Filter",
        description="Smoothed range filter (Donovan Wall): trend follow with ATR bands.",
        source="tradingview",
        source_url="https://www.tradingview.com/script/lut7sBgG/",
        license="MIT",
        version="1.0.0",
        timeframes=["15m", "1h"],
        asset_classes=["crypto_perp"],
        risk_notes="Sensitive to range_size_mult; backtest before live.",
    )
    params = {
        "smooth_period": 20,
        "range_size_mult": 2.618,
        "stop_loss_atr_multiplier": 2.0,
        "take_profit_rr_ratio": 2.0,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "smooth_period": [10, 50],
        "range_size_mult": [1.5, 4.0],
        "stop_loss_atr_multiplier": [1.5, 3.5],
        "take_profit_rr_ratio": [1.5, 4.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        period = int(p["smooth_period"])
        a = atr(ohlcv["high"], ohlcv["low"], ohlcv["close"], period)
        # filter = EMA(close, period); upper/lower = filter ± mult*ATR
        f = ema(ohlcv["close"], period)
        upper = [None] * len(f); lower = [None] * len(f)
        for i in range(len(f)):
            if f[i] is not None and a[i] is not None:
                upper[i] = f[i] + p["range_size_mult"] * a[i]
                lower[i] = f[i] - p["range_size_mult"] * a[i]
        return {"filter": f, "upper": upper, "lower": lower}

    def entry_signal(self, indicators, last_bar) -> Optional[EntrySignal]:
        f = indicators["filter"]; up = indicators["upper"]; dn = indicators["lower"]
        if len(f) < 2 or f[-1] is None or f[-2] is None or up[-1] is None or dn[-1] is None:
            return None
        c = last_bar["close"]
        # rising filter + close above upper = long
        if f[-1] > f[-2] and c > up[-1]:
            return EntrySignal(direction="long", confidence=66.0,
                               reasons=["range filter rising; close > upper band"],
                               tags=["trend_follow", "range_filter"])
        if f[-1] < f[-2] and c < dn[-1]:
            return EntrySignal(direction="short", confidence=66.0,
                               reasons=["range filter falling; close < lower band"],
                               tags=["trend_follow", "range_filter"])
        return None
