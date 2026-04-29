"""Wilder ADX Trend Filter — long when ADX > 25 and +DI > -DI (and reverse).

Pattern origin:  J. Welles Wilder Jr., "New Concepts in Technical Trading Systems"
                 (1978). ADX measures trend strength regardless of direction;
                 +DI/-DI gives direction. Classic combo.
License:         MIT (our impl).
"""

from __future__ import annotations
from typing import Optional

from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import atr


class WilderADXTrend(Strategy):
    metadata = StrategyMetadata(
        id="classic.wilder_adx_trend",
        name="Wilder ADX Trend (DI cross + ADX > threshold)",
        description="ADX>25 confirms trend; +DI > -DI = long, reverse for short.",
        source="classic",
        source_url="https://en.wikipedia.org/wiki/Average_directional_movement_index",
        license="MIT",
        version="1.0.0",
        timeframes=["1h", "4h"],
        asset_classes=["crypto_perp"],
        risk_notes="Lags new trends; misses choppy moves entirely (good thing).",
    )
    params = {
        "di_period": 14,
        "adx_threshold": 25.0,
        "stop_loss_atr_multiplier": 2.0,
        "take_profit_rr_ratio": 2.0,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "di_period": [7, 30],
        "adx_threshold": [15.0, 40.0],
        "stop_loss_atr_multiplier": [1.5, 3.5],
        "take_profit_rr_ratio": [1.5, 4.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def _wilder_smooth(self, values, period):
        out = [None] * len(values)
        if len(values) < period:
            return out
        s = sum(values[:period])
        out[period - 1] = s
        for i in range(period, len(values)):
            s = s - (s / period) + values[i]
            out[i] = s
        return out

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        period = int(p["di_period"])
        H = ohlcv["high"]; L = ohlcv["low"]; C = ohlcv["close"]
        plus_dm = [0.0]; minus_dm = [0.0]; tr = [0.0]
        for i in range(1, len(H)):
            up = H[i] - H[i - 1]
            dn = L[i - 1] - L[i]
            plus_dm.append(up if (up > dn and up > 0) else 0.0)
            minus_dm.append(dn if (dn > up and dn > 0) else 0.0)
            tr.append(max(H[i] - L[i], abs(H[i] - C[i - 1]), abs(L[i] - C[i - 1])))
        sm_plus = self._wilder_smooth(plus_dm, period)
        sm_minus = self._wilder_smooth(minus_dm, period)
        sm_tr = self._wilder_smooth(tr, period)
        plus_di = [None] * len(H); minus_di = [None] * len(H); dx = [None] * len(H)
        for i in range(len(H)):
            if sm_tr[i] and sm_tr[i] > 0 and sm_plus[i] is not None and sm_minus[i] is not None:
                plus_di[i] = 100 * sm_plus[i] / sm_tr[i]
                minus_di[i] = 100 * sm_minus[i] / sm_tr[i]
                s = plus_di[i] + minus_di[i]
                if s > 0:
                    dx[i] = 100 * abs(plus_di[i] - minus_di[i]) / s
        valid_dx = [v for v in dx if v is not None]
        adx = self._wilder_smooth(valid_dx, period) if len(valid_dx) >= period else []
        adx = [None] * (len(dx) - len(adx)) + [None if v is None else v / period for v in adx]
        return {"plus_di": plus_di, "minus_di": minus_di, "adx": adx}

    def entry_signal(self, indicators, last_bar) -> Optional[EntrySignal]:
        p = self._effective_params
        pd = indicators["plus_di"]; md = indicators["minus_di"]; adx = indicators["adx"]
        if pd[-1] is None or md[-1] is None or adx[-1] is None:
            return None
        if adx[-1] < p["adx_threshold"]:
            return None
        if pd[-1] > md[-1]:
            return EntrySignal(direction="long", confidence=68.0,
                               reasons=[f"+DI > -DI, ADX={adx[-1]:.1f}"],
                               tags=["adx", "trend_follow"])
        if md[-1] > pd[-1]:
            return EntrySignal(direction="short", confidence=68.0,
                               reasons=[f"-DI > +DI, ADX={adx[-1]:.1f}"],
                               tags=["adx", "trend_follow"])
        return None
