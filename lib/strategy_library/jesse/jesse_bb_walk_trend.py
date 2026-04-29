"""BB Walk Trend — multiple closes above upper BB indicates trend, not reversal.

Pattern origin: John Bollinger's "walking the bands" concept.
Source URL:     https://github.com/jesse-ai/jesse
License:        MIT
"""

from __future__ import annotations
from typing import Optional
from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import bollinger_bands, atr, ema


class JesseBbWalkTrend(Strategy):
    metadata = StrategyMetadata(
        id="jesse.bb_walk_trend",
        name="BB Walk-the-Band Trend",
        description="3+ closes above upper BB with EMA50 rising = trend follow long.",
        source="jesse",
        source_url="https://github.com/jesse-ai/jesse",
        license="MIT",
        version="1.0.0",
        timeframes=["1h", "4h"],
        asset_classes=["crypto_perp"],
        risk_notes="Counter-intuitive vs mean-reversion; requires strong trend.",
    )
    params = {
        "consecutive": 3,
        "bb_period": 20,
        "bb_std": 2.0,
        "stop_loss_atr_multiplier": 2.5,
        "take_profit_rr_ratio": 2.0,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "consecutive": [2, 5],
        "bb_period": [10, 30],
        "bb_std": [1.5, 3.0],
        "stop_loss_atr_multiplier": [1.5, 4.0],
        "take_profit_rr_ratio": [1.5, 3.5],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        c = ohlcv["close"]
        return {
            "bb": bollinger_bands(c, int(p["bb_period"]), p["bb_std"]),
            "ema_trend": ema(c, 50),
            "atr_14": atr(ohlcv["high"], ohlcv["low"], c, 14),
            "closes": c,
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        p = self._effective_params
        n = int(p["consecutive"])
        c = indicators["closes"]
        u = indicators["bb"]["upper"]
        l = indicators["bb"]["lower"]
        et = indicators["ema_trend"]
        if len(c) < n + 5 or et[-5] is None or et[-1] is None:
            return None
        long_walk = all(u[-i] is not None and c[-i] > u[-i] for i in range(1, n + 1))
        short_walk = all(l[-i] is not None and c[-i] < l[-i] for i in range(1, n + 1))
        if long_walk and et[-1] > et[-5]:
            return EntrySignal(direction="long", confidence=70.0,
                               reasons=[f"{n} closes above upper BB"],
                               tags=["trend_follow", "bb_walk"])
        if short_walk and et[-1] < et[-5]:
            return EntrySignal(direction="short", confidence=68.0,
                               reasons=[f"{n} closes below lower BB"],
                               tags=["trend_follow", "bb_walk"])
        return None
