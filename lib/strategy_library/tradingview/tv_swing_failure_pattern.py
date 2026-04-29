"""TradingView — Swing Failure Pattern (CryptoCred curriculum).

Pattern origin:  CryptoCred's Swing Failure Pattern (SFP). New high/low followed
                 by failure to hold beyond the prior swing = exhaustion entry.
Source URL:      https://www.youtube.com/c/CryptoCred  (educational series)
License:         MIT (our impl).
Notes:           Treat as 1h+ setup; on 15m too noisy. Enter on close BACK INSIDE
                 prior range; stop just beyond the rejected wick.
"""

from __future__ import annotations
from typing import Optional

from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import atr


class TVSwingFailurePattern(Strategy):
    metadata = StrategyMetadata(
        id="tradingview.swing_failure_pattern",
        name="TradingView Swing Failure Pattern (CryptoCred)",
        description="Failed break of N-bar swing; reclaim = reversal entry.",
        source="tradingview",
        source_url="https://www.youtube.com/c/CryptoCred",
        license="MIT",
        version="1.0.0",
        timeframes=["1h", "4h"],
        asset_classes=["crypto_perp"],
        risk_notes="Best when sentiment is one-sided; combine with funding/OI when available.",
    )
    params = {
        "swing_lookback": 10,
        "wick_atr_min": 0.5,
        "stop_loss_atr_multiplier": 1.5,
        "take_profit_rr_ratio": 2.5,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "swing_lookback": [5, 30],
        "wick_atr_min": [0.2, 2.0],
        "stop_loss_atr_multiplier": [1.0, 3.0],
        "take_profit_rr_ratio": [1.5, 4.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        return {"atr": atr(ohlcv["high"], ohlcv["low"], ohlcv["close"], 14),
                "highs": ohlcv["high"], "lows": ohlcv["low"],
                "opens": ohlcv["open"], "closes": ohlcv["close"]}

    def entry_signal(self, indicators, last_bar) -> Optional[EntrySignal]:
        p = self._effective_params
        n = int(p["swing_lookback"])
        H = indicators["highs"]; L = indicators["lows"]
        O = indicators["opens"]; C = indicators["closes"]; A = indicators["atr"]
        if len(H) < n + 2 or A[-1] is None:
            return None
        prior_high = max(H[-n - 1:-1])
        prior_low = min(L[-n - 1:-1])
        cur_h = H[-1]; cur_l = L[-1]; cur_c = C[-1]; cur_o = O[-1]
        body = abs(cur_c - cur_o)
        upper_wick = cur_h - max(cur_o, cur_c)
        lower_wick = min(cur_o, cur_c) - cur_l
        wick_floor = p["wick_atr_min"] * A[-1]
        # Bearish SFP: new high, close back inside, large upper wick
        if cur_h > prior_high and cur_c < prior_high and upper_wick >= wick_floor and upper_wick > body:
            return EntrySignal(direction="short", confidence=70.0,
                               reasons=["bearish SFP — failed break of swing high"],
                               tags=["sfp", "reversal", "cryptocred"])
        # Bullish SFP: new low, close back inside, large lower wick
        if cur_l < prior_low and cur_c > prior_low and lower_wick >= wick_floor and lower_wick > body:
            return EntrySignal(direction="long", confidence=70.0,
                               reasons=["bullish SFP — failed break of swing low"],
                               tags=["sfp", "reversal", "cryptocred"])
        return None
