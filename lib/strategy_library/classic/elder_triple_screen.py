"""Elder Triple Screen — Dr. Alexander Elder's HTF-trend / LTF-entry system.

Pattern origin:  Alexander Elder, "Trading for a Living" (1993). Triple-screen
                 reduces single-timeframe trades. Approximated here on a single
                 timeframe by using EMA-26 slope as proxy for HTF trend, MACD
                 histogram for momentum, and stochastic-style %K for entry.
License:         MIT.
Notes:           Without true multi-TF data we fold all three screens into a
                 single-TF gating filter. Real Elder logic on monthly+weekly+
                 daily would slot in via D5.3 multi-TF helper.
"""

from __future__ import annotations
from typing import Optional

from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import ema, macd


class ElderTripleScreen(Strategy):
    metadata = StrategyMetadata(
        id="classic.elder_triple_screen",
        name="Elder Triple Screen (single-TF approx)",
        description="EMA-26 slope (HTF) + MACD histogram (mid) + low-RSI entry trigger.",
        source="classic",
        source_url="https://en.wikipedia.org/wiki/Triple_screen_trading_system",
        license="MIT",
        version="1.0.0",
        timeframes=["1h", "4h"],
        asset_classes=["crypto_perp"],
        risk_notes="True multi-TF version is preferable; revisit once D5 ships.",
    )
    params = {
        "ema_long": 26,
        "rsi_threshold_long": 35.0,
        "rsi_threshold_short": 65.0,
        "stop_loss_atr_multiplier": 2.0,
        "take_profit_rr_ratio": 2.5,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "ema_long": [20, 60],
        "rsi_threshold_long": [25.0, 45.0],
        "rsi_threshold_short": [55.0, 75.0],
        "stop_loss_atr_multiplier": [1.5, 3.5],
        "take_profit_rr_ratio": [1.5, 4.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        from lib.technical_indicators import rsi
        p = self._effective_params
        e = ema(ohlcv["close"], int(p["ema_long"]))
        m = macd(ohlcv["close"], 12, 26, 9)
        r = rsi(ohlcv["close"], 14)
        return {"ema": e, "hist": m["histogram"], "rsi": r}

    def entry_signal(self, indicators, last_bar) -> Optional[EntrySignal]:
        p = self._effective_params
        e = indicators["ema"]; h = indicators["hist"]; r = indicators["rsi"]
        if (len(e) < 3 or e[-1] is None or e[-2] is None
                or h[-1] is None or r[-1] is None):
            return None
        # HTF screen: EMA slope
        rising = e[-1] > e[-2]
        falling = e[-1] < e[-2]
        # mid screen: histogram sign
        hist_pos = h[-1] > 0
        hist_neg = h[-1] < 0
        # entry: pullback to oversold/overbought in trend direction
        if rising and hist_pos and r[-1] < p["rsi_threshold_long"]:
            return EntrySignal(direction="long", confidence=70.0,
                               reasons=["EMA up, MACD hist +, RSI oversold"],
                               tags=["elder", "triple_screen", "pullback"])
        if falling and hist_neg and r[-1] > p["rsi_threshold_short"]:
            return EntrySignal(direction="short", confidence=70.0,
                               reasons=["EMA down, MACD hist -, RSI overbought"],
                               tags=["elder", "triple_screen", "pullback"])
        return None
