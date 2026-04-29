"""TradingView — QQE Signal (Quantitative Qualitative Estimation).

Pattern origin:  QQE indicator (Igor Livshin); popularised on TV in many open-source
                 ports. We use a simplified RSI-Wilder-smoothing variant.
Source URL:      https://www.tradingview.com/script/IYfA9R2k-QQE-MOD/
License:         MIT.
Notes:           QQE = RSI smoothed by EMA + ATR-of-RSI bands. Long when smoothed
                 RSI crosses above its trailing line; short when crosses below.
"""

from __future__ import annotations
from typing import Optional

from lib.strategy_engine import Strategy, StrategyMetadata, EntrySignal
from lib.technical_indicators import rsi, ema, cross_above, cross_below


class TVQQESignal(Strategy):
    metadata = StrategyMetadata(
        id="tradingview.qqe_signal",
        name="TradingView QQE Signal",
        description="Smoothed-RSI cross of its trailing line (QQE-style).",
        source="tradingview",
        source_url="https://www.tradingview.com/script/IYfA9R2k-QQE-MOD/",
        license="MIT",
        version="1.0.0",
        timeframes=["15m", "1h"],
        asset_classes=["crypto_perp"],
        risk_notes="Cross-style signal; many in chop. Use HTF filter.",
    )
    params = {
        "rsi_period": 14,
        "rsi_smooth": 5,
        "trailing_smooth": 9,
        "stop_loss_atr_multiplier": 2.0,
        "take_profit_rr_ratio": 2.0,
        "default_leverage": 3.0,
        "risk_pct": 1.0,
    }
    safe_bounds = {
        "rsi_period": [7, 30],
        "rsi_smooth": [2, 10],
        "trailing_smooth": [5, 20],
        "stop_loss_atr_multiplier": [1.5, 3.5],
        "take_profit_rr_ratio": [1.5, 4.0],
        "default_leverage": [1.0, 5.0],
        "risk_pct": [0.5, 1.5],
    }

    def populate_indicators(self, ohlcv: dict) -> dict:
        p = self._effective_params
        r = rsi(ohlcv["close"], int(p["rsi_period"]))
        valid_r = [x for x in r if x is not None]
        rsi_smooth = ema(valid_r, int(p["rsi_smooth"])) if valid_r else []
        # re-pad to len(r)
        rsi_smooth = [None] * (len(r) - len(rsi_smooth)) + rsi_smooth
        valid_s = [x for x in rsi_smooth if x is not None]
        trail = ema(valid_s, int(p["trailing_smooth"])) if valid_s else []
        trail = [None] * (len(rsi_smooth) - len(trail)) + trail
        return {"rsi_smooth": rsi_smooth, "trail": trail}

    def entry_signal(self, indicators, last_bar) -> Optional[EntrySignal]:
        rs = indicators["rsi_smooth"]; tr = indicators["trail"]
        if len(rs) < 3 or rs[-1] is None or tr[-1] is None:
            return None
        if cross_above(rs, tr) and rs[-1] > 50:
            return EntrySignal(direction="long", confidence=66.0,
                               reasons=["smoothed RSI crossed above trail line, > 50"],
                               tags=["momentum", "qqe"])
        if cross_below(rs, tr) and rs[-1] < 50:
            return EntrySignal(direction="short", confidence=66.0,
                               reasons=["smoothed RSI crossed below trail line, < 50"],
                               tags=["momentum", "qqe"])
        return None
