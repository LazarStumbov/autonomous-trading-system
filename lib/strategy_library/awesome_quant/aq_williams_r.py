"""Williams %R Reversal — fade %R extremes.

Pattern origin: Larry Williams, Williams %R indicator (1973).
Source URL:     https://github.com/wilsonfreitas/awesome-quant
License:        MIT (our implementation)
"""

from __future__ import annotations
from typing import Optional
from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import atr, ema


class AqWilliamsR(Strategy):
    metadata = StrategyMetadata(
        id="awesome_quant.williams_r",
        name="Williams %R Reversal",
        description="Long when %R < -90 (oversold) in uptrend; short when %R > -10 in downtrend.",
        source="awesome_quant",
        source_url="https://github.com/wilsonfreitas/awesome-quant",
        license="MIT",
        version="1.0.0",
        timeframes=["1h", "4h"],
        asset_classes=["crypto_perp"],
        risk_notes="Use trend filter to avoid catching falling knives.",
    )
    params = {
        "wr_period": 14,
        "trend_period": 100,
        "oversold": -90.0,
        "overbought": -10.0,
        "stop_loss_atr_multiplier": 1.5,
        "take_profit_rr_ratio": 2.0,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "wr_period": [7, 21],
        "trend_period": [50, 200],
        "oversold": [-100.0, -75.0],
        "overbought": [-25.0, 0.0],
        "stop_loss_atr_multiplier": [1.0, 3.0],
        "take_profit_rr_ratio": [1.2, 3.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        c = ohlcv["close"]
        h = ohlcv["high"]
        l = ohlcv["low"]
        n = int(p["wr_period"])
        wr = []
        for i in range(len(c)):
            if i < n - 1:
                wr.append(None)
            else:
                hh = max(h[i - n + 1:i + 1])
                ll = min(l[i - n + 1:i + 1])
                if hh == ll:
                    wr.append(None)
                else:
                    wr.append((hh - c[i]) / (hh - ll) * -100)
        return {
            "wr": wr,
            "ema_trend": ema(c, int(p["trend_period"])),
            "atr_14": atr(h, l, c, 14),
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        p = self._effective_params
        w = indicators["wr"][-1]
        et = indicators["ema_trend"][-1]
        if w is None or et is None:
            return None
        price = last_bar["close"]
        if w <= p["oversold"] and price > et:
            return EntrySignal(direction="long", confidence=66.0,
                               reasons=[f"%R {w:.1f} <= {p['oversold']}", "uptrend"],
                               tags=["mean_reversion", "williams_r"])
        if w >= p["overbought"] and price < et:
            return EntrySignal(direction="short", confidence=64.0,
                               reasons=[f"%R {w:.1f} >= {p['overbought']}", "downtrend"],
                               tags=["mean_reversion", "williams_r"])
        return None
