"""DMI/ADX — Directional Movement Index trend follower.

Pattern origin: J. Welles Wilder, Directional Movement Index (1978).
Source URL:     https://github.com/wilsonfreitas/awesome-quant
License:        MIT (our implementation)
"""

from __future__ import annotations
from typing import Optional
from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import ema, atr


class AqDmiAdx(Strategy):
    metadata = StrategyMetadata(
        id="awesome_quant.dmi_adx",
        name="DMI/ADX Trend",
        description="ADX > 25 + +DI > -DI = long; mirror for short.",
        source="awesome_quant",
        source_url="https://github.com/wilsonfreitas/awesome-quant",
        license="MIT",
        version="1.0.0",
        timeframes=["1h", "4h"],
        asset_classes=["crypto_perp"],
        risk_notes="ADX filter helps avoid range chop.",
    )
    params = {
        "period": 14,
        "min_adx": 25.0,
        "stop_loss_atr_multiplier": 2.0,
        "take_profit_rr_ratio": 2.5,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "period": [7, 28],
        "min_adx": [15.0, 40.0],
        "stop_loss_atr_multiplier": [1.0, 3.5],
        "take_profit_rr_ratio": [1.5, 4.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        h = ohlcv["high"]
        l = ohlcv["low"]
        c = ohlcv["close"]
        n = int(p["period"])
        plus_dm = [0.0]
        minus_dm = [0.0]
        for i in range(1, len(h)):
            up = h[i] - h[i - 1]
            dn = l[i - 1] - l[i]
            plus_dm.append(up if up > dn and up > 0 else 0.0)
            minus_dm.append(dn if dn > up and dn > 0 else 0.0)
        atr_n = atr(h, l, c, n)
        # Smooth DM
        plus_di = []
        minus_di = []
        for i in range(len(c)):
            if atr_n[i] is None or atr_n[i] == 0:
                plus_di.append(None)
                minus_di.append(None)
            else:
                # Use rolling sum approximation via ema
                pass
        plus_dm_smooth = ema(plus_dm, n)
        minus_dm_smooth = ema(minus_dm, n)
        for i in range(len(c)):
            if atr_n[i] is None or atr_n[i] == 0 or plus_dm_smooth[i] is None or minus_dm_smooth[i] is None:
                plus_di.append(None) if i >= len(plus_di) else None
                minus_di.append(None) if i >= len(minus_di) else None
            else:
                pdi = 100 * plus_dm_smooth[i] / atr_n[i]
                mdi = 100 * minus_dm_smooth[i] / atr_n[i]
                if i >= len(plus_di):
                    plus_di.append(pdi)
                    minus_di.append(mdi)
                else:
                    plus_di[i] = pdi
                    minus_di[i] = mdi
        # Build clean DI lists
        plus_di_clean = [None] * len(c)
        minus_di_clean = [None] * len(c)
        for i in range(len(c)):
            if (atr_n[i] is not None and atr_n[i] > 0
                    and plus_dm_smooth[i] is not None and minus_dm_smooth[i] is not None):
                plus_di_clean[i] = 100 * plus_dm_smooth[i] / atr_n[i]
                minus_di_clean[i] = 100 * minus_dm_smooth[i] / atr_n[i]
        # ADX = ema of |+DI - -DI| / (+DI + -DI) * 100
        dx = []
        for i in range(len(c)):
            if plus_di_clean[i] is None or minus_di_clean[i] is None:
                dx.append(None)
            else:
                tot = plus_di_clean[i] + minus_di_clean[i]
                dx.append(abs(plus_di_clean[i] - minus_di_clean[i]) / tot * 100 if tot > 0 else 0)
        dx_clean = [v for v in dx if v is not None]
        adx_smooth = ema(dx_clean, n) if len(dx_clean) >= n else [None] * len(dx_clean)
        pad = len(dx) - len(adx_smooth)
        adx = [None] * pad + adx_smooth
        return {
            "plus_di": plus_di_clean,
            "minus_di": minus_di_clean,
            "adx": adx,
            "atr_14": atr(h, l, c, 14),
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        p = self._effective_params
        pdi = indicators["plus_di"][-1]
        mdi = indicators["minus_di"][-1]
        a = indicators["adx"][-1]
        if pdi is None or mdi is None or a is None:
            return None
        if a < p["min_adx"]:
            return None
        if pdi > mdi:
            return EntrySignal(direction="long", confidence=68.0,
                               reasons=[f"+DI {pdi:.1f} > -DI {mdi:.1f}", f"ADX {a:.1f}"],
                               tags=["trend_follow", "adx"])
        if mdi > pdi:
            return EntrySignal(direction="short", confidence=66.0,
                               reasons=[f"-DI {mdi:.1f} > +DI {pdi:.1f}", f"ADX {a:.1f}"],
                               tags=["trend_follow", "adx"])
        return None
