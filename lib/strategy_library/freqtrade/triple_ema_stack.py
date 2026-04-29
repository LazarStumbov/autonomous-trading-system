"""Triple EMA Stack — strict EMA8/21/55 alignment for trend trades.

Pattern origin: Stanley Druckenmiller-style EMA ribbon, also Daryl Guppy GMMA.
Source URL:     https://github.com/freqtrade/freqtrade-strategies
License:        GPLv3 (preserved from upstream freqtrade-strategies repo).
                This file MUST NOT import from non-GPL parts of our codebase
                beyond lib.strategy_engine + lib.technical_indicators (both MIT,
                mere-aggregation OK).
"""

from __future__ import annotations
from typing import Optional
from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import ema, atr


class TripleEmaStack(Strategy):
    metadata = StrategyMetadata(
        id="freqtrade.triple_ema_stack",
        name="Triple EMA Stack 8/21/55",
        description="Long when EMA8 > EMA21 > EMA55 and price > EMA8. Mirror for short.",
        source="freqtrade",
        source_url="https://github.com/freqtrade/freqtrade-strategies",
        license="GPLv3",
        version="1.0.0",
        timeframes=["1h", "4h"],
        asset_classes=["crypto_perp"],
        risk_notes="Strict alignment misses early reversals but improves win rate.",
    )
    params = {
        "fast": 8,
        "mid": 21,
        "slow": 55,
        "stop_loss_atr_multiplier": 2.2,
        "take_profit_rr_ratio": 3.0,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "fast": [5, 13],
        "mid": [13, 34],
        "slow": [34, 100],
        "stop_loss_atr_multiplier": [1.5, 4.0],
        "take_profit_rr_ratio": [2.0, 5.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        c = ohlcv["close"]
        return {
            "ema_f": ema(c, int(p["fast"])),
            "ema_m": ema(c, int(p["mid"])),
            "ema_s": ema(c, int(p["slow"])),
            "atr_14": atr(ohlcv["high"], ohlcv["low"], c, 14),
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        f = indicators["ema_f"][-1]
        m = indicators["ema_m"][-1]
        s = indicators["ema_s"][-1]
        if None in (f, m, s):
            return None
        f2 = indicators["ema_f"][-2] if len(indicators["ema_f"]) >= 2 else None
        m2 = indicators["ema_m"][-2] if len(indicators["ema_m"]) >= 2 else None
        s2 = indicators["ema_s"][-2] if len(indicators["ema_s"]) >= 2 else None
        if None in (f2, m2, s2):
            return None
        price = last_bar["close"]
        # Stack just formed (was not aligned previous bar but is now)
        prev_long = f2 > m2 > s2
        now_long = f > m > s
        prev_short = f2 < m2 < s2
        now_short = f < m < s
        if now_long and not prev_long and price > f:
            return EntrySignal(direction="long", confidence=72.0,
                               reasons=["new bullish EMA stack"],
                               tags=["trend_follow", "ema_stack"])
        if now_short and not prev_short and price < f:
            return EntrySignal(direction="short", confidence=70.0,
                               reasons=["new bearish EMA stack"],
                               tags=["trend_follow", "ema_stack"])
        return None
