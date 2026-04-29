"""OBV Trend — On-Balance Volume slope confirms price trend.

Pattern origin: Joseph Granville, "Granville's New Key to Stock Market Profits" (1963).
Source URL:     https://github.com/jesse-ai/jesse
License:        MIT
"""

from __future__ import annotations
from typing import Optional
from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import ema, atr, sma


class JesseObvTrend(Strategy):
    metadata = StrategyMetadata(
        id="jesse.obv_trend",
        name="OBV Trend Confirmation",
        description="Price > EMA50 AND OBV > OBV-SMA20 = institutional accumulation.",
        source="jesse",
        source_url="https://github.com/jesse-ai/jesse",
        license="MIT",
        version="1.0.0",
        timeframes=["1h", "4h"],
        asset_classes=["crypto_perp"],
        risk_notes="OBV resets on missing data; only run with continuous candles.",
    )
    params = {
        "ema_period": 50,
        "obv_sma": 20,
        "stop_loss_atr_multiplier": 2.0,
        "take_profit_rr_ratio": 2.5,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "ema_period": [20, 100],
        "obv_sma": [10, 50],
        "stop_loss_atr_multiplier": [1.0, 3.5],
        "take_profit_rr_ratio": [1.5, 4.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        c = ohlcv["close"]
        v = ohlcv["volume"]
        obv = [0.0]
        for i in range(1, len(c)):
            if c[i] > c[i - 1]:
                obv.append(obv[-1] + v[i])
            elif c[i] < c[i - 1]:
                obv.append(obv[-1] - v[i])
            else:
                obv.append(obv[-1])
        return {
            "obv": obv,
            "obv_sma": sma(obv, int(p["obv_sma"])),
            "ema_trend": ema(c, int(p["ema_period"])),
            "atr_14": atr(ohlcv["high"], ohlcv["low"], c, 14),
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        obv = indicators["obv"][-1]
        obvs = indicators["obv_sma"][-1]
        et = indicators["ema_trend"][-1]
        if obvs is None or et is None:
            return None
        price = last_bar["close"]
        if price > et and obv > obvs:
            return EntrySignal(direction="long", confidence=66.0,
                               reasons=["above EMA trend", "OBV above its SMA"],
                               tags=["trend_follow", "volume"])
        if price < et and obv < obvs:
            return EntrySignal(direction="short", confidence=64.0,
                               reasons=["below EMA trend", "OBV below its SMA"],
                               tags=["trend_follow", "volume"])
        return None
