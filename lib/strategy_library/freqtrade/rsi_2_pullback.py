"""RSI(2) Pullback — Connors RSI(2) buy-the-dip in established uptrend.

Pattern origin: Larry Connors, "Short Term Trading Strategies That Work".
Source URL:     https://github.com/freqtrade/freqtrade-strategies (Connors-style)
License:        GPLv3 (preserved from upstream freqtrade-strategies repo).
                This file MUST NOT import from non-GPL parts of our codebase
                beyond lib.strategy_engine + lib.technical_indicators (both MIT,
                mere-aggregation OK).
"""

from __future__ import annotations
from typing import Optional
from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import rsi, sma, atr


class Rsi2Pullback(Strategy):
    metadata = StrategyMetadata(
        id="freqtrade.rsi_2_pullback",
        name="RSI(2) Pullback",
        description="Long when price > SMA200 and RSI(2) < 10. Connors-style mean-reversion.",
        source="freqtrade",
        source_url="https://github.com/freqtrade/freqtrade-strategies",
        license="GPLv3",
        version="1.0.0",
        timeframes=["1h", "4h", "1d"],
        asset_classes=["crypto_perp", "stock_equity"],
        risk_notes="Long-only. Don't use without trend filter.",
    )
    params = {
        "rsi_period": 2,
        "rsi_buy": 10.0,
        "trend_period": 200,
        "stop_loss_atr_multiplier": 2.5,
        "take_profit_rr_ratio": 1.5,
        "default_leverage": 2.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "rsi_period": [2, 4],
        "rsi_buy": [5.0, 20.0],
        "trend_period": [100, 300],
        "stop_loss_atr_multiplier": [1.5, 4.0],
        "take_profit_rr_ratio": [1.0, 3.0],
        "default_leverage": [1.0, 4.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        c = ohlcv["close"]
        return {
            "rsi": rsi(c, int(p["rsi_period"])),
            "trend": sma(c, int(p["trend_period"])),
            "atr_14": atr(ohlcv["high"], ohlcv["low"], c, 14),
        }

    def entry_signal(self, indicators: dict, last_bar: dict) -> Optional[EntrySignal]:
        p = self._effective_params
        r = indicators["rsi"]
        t = indicators["trend"]
        if not r or r[-1] is None or t[-1] is None:
            return None
        price = last_bar["close"]
        if price > t[-1] and r[-1] < p["rsi_buy"]:
            return EntrySignal(direction="long", confidence=70.0,
                               reasons=[f"RSI(2) {r[-1]:.1f} < {p['rsi_buy']}", "above SMA200"],
                               tags=["mean_reversion", "connors"])
        return None
