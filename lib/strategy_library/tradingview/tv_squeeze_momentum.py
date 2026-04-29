"""TradingView — Squeeze Momentum (LazyBear's TTM Squeeze open-source port).

Pattern origin:  John Carter's TTM Squeeze; popular open-source PineCoders port
                 by LazyBear.
Source URL:      https://www.tradingview.com/script/4IneGo7-Squeeze-Momentum-Indicator-LazyBear/
License:         MIT (our reimplementation; concept public).
Notes:           Long when BB is inside KC (squeeze) AND momentum (close vs midline)
                 turns positive on the bar squeeze releases. ATR proxies KC range.
"""

from __future__ import annotations
from typing import Optional

from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import bollinger_bands, atr, ema


class TVSqueezeMomentum(Strategy):
    metadata = StrategyMetadata(
        id="tradingview.squeeze_momentum",
        name="TradingView Squeeze Momentum (LazyBear)",
        description="BB-inside-KC squeeze release with momentum sign.",
        source="tradingview",
        source_url="https://www.tradingview.com/script/4IneGo7/",
        license="MIT",
        version="1.0.0",
        timeframes=["1h", "4h"],
        asset_classes=["crypto_perp"],
        risk_notes="Sometimes fires on already-extended moves; pair with HTF filter.",
    )
    params = {
        "bb_period": 20,
        "bb_std": 2.0,
        "kc_atr_mult": 1.5,
        "stop_loss_atr_multiplier": 2.0,
        "take_profit_rr_ratio": 2.5,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "bb_period": [10, 30],
        "bb_std": [1.5, 3.0],
        "kc_atr_mult": [1.0, 2.5],
        "stop_loss_atr_multiplier": [1.5, 3.5],
        "take_profit_rr_ratio": [1.5, 4.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        bb = bollinger_bands(ohlcv["close"], int(p["bb_period"]), p["bb_std"])
        a = atr(ohlcv["high"], ohlcv["low"], ohlcv["close"], int(p["bb_period"]))
        mid = ema(ohlcv["close"], int(p["bb_period"]))
        return {"bb_upper": bb["upper"], "bb_lower": bb["lower"],
                "atr": a, "mid": mid, "kc_mult": p["kc_atr_mult"]}

    def entry_signal(self, indicators, last_bar) -> Optional[EntrySignal]:
        bbu = indicators["bb_upper"]; bbl = indicators["bb_lower"]
        a = indicators["atr"]; mid = indicators["mid"]
        if (len(bbu) < 2 or bbu[-1] is None or bbu[-2] is None
                or a[-1] is None or mid[-1] is None):
            return None
        kc_mult = indicators["kc_mult"]
        # squeeze on prior bar: BB inside KC
        kc_upper_prev = mid[-2] + kc_mult * a[-2] if mid[-2] and a[-2] else None
        kc_lower_prev = mid[-2] - kc_mult * a[-2] if mid[-2] and a[-2] else None
        if kc_upper_prev is None or kc_lower_prev is None:
            return None
        was_squeezed = bbu[-2] < kc_upper_prev and bbl[-2] > kc_lower_prev
        if not was_squeezed:
            return None
        # release this bar
        kc_upper = mid[-1] + kc_mult * a[-1]
        kc_lower = mid[-1] - kc_mult * a[-1]
        released = bbu[-1] >= kc_upper or bbl[-1] <= kc_lower
        if not released:
            return None
        c = last_bar["close"]
        if c > mid[-1]:
            return EntrySignal(direction="long", confidence=72.0,
                               reasons=["squeeze release; close > midline"],
                               tags=["squeeze", "breakout"])
        if c < mid[-1]:
            return EntrySignal(direction="short", confidence=72.0,
                               reasons=["squeeze release; close < midline"],
                               tags=["squeeze", "breakout"])
        return None
