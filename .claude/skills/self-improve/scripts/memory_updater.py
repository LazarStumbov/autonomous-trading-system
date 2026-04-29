"""Refresh the rolling memory JSONs that the confluence engine and screener read.

Two files get rewritten each run:

  * data/memory/strategy_memory.json — per-strategy rolling snapshot
    (mode, recent win-rate, 30d Sharpe, last_20_win_rate, consecutive_losses,
    last trade timestamp). Used by confluence_detector to weight strategies.

  * data/memory/market_regime.json — heuristic regime label ("bull_trend",
    "bear_trend", "range", "high_vol", "low_vol") based on recent BTC
    closes + ATR. Cheap to compute, consumed by confluence_detector to bias
    strategy weighting (e.g. mean-reversion down-weighted in strong trends).

Idempotent. Safe to re-run. Writes absolute timestamps.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from lib.db import get_connection, list_strategies, set_system_state

MEMORY_DIR = Path(PROJECT_ROOT) / "data" / "memory"


def build_strategy_memory(conn) -> dict:
    strategies = list_strategies(conn)
    perf_rows = {
        r["strategy_id"]: dict(r)
        for r in conn.execute("SELECT * FROM strategy_performance").fetchall()
    }
    entries = {}
    for s in strategies:
        sid = s["id"]
        p = perf_rows.get(sid, {})
        entries[sid] = {
            "mode": s.get("mode"),
            "source": s.get("source"),
            "name": s.get("name"),
            "total_trades": p.get("total_trades", 0),
            "win_rate": p.get("win_rate"),
            "last_20_win_rate": p.get("last_20_win_rate"),
            "profit_factor": p.get("profit_factor"),
            "sharpe_30d": p.get("sharpe_30d"),
            "consecutive_losses": p.get("consecutive_losses", 0),
            "total_pnl_usd": p.get("total_pnl_usd", 0),
            "last_trade_at": p.get("last_trade_at"),
            "mode_changed_at": s.get("mode_changed_at"),
            "demotion_reason": s.get("demotion_reason"),
        }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "strategies": entries,
    }


def _load_btc_closes() -> list[float]:
    """Try the cached OHLCV first; fall back to empty list (regime = unknown)."""
    cache_dir = Path(PROJECT_ROOT) / "data" / "cache" / "ohlcv"
    if not cache_dir.exists():
        return []
    # Prefer Bybit / BTC perp 1h if present
    candidates = list(cache_dir.rglob("*BTC*USDT*/1h.json")) + list(cache_dir.rglob("*BTC*USDT*/4h.json"))
    for path in candidates:
        try:
            with open(path) as f:
                data = json.load(f)
            bars = data.get("ohlcv") or data.get("bars") or data
            if isinstance(bars, list) and bars and isinstance(bars[0], (list, tuple)):
                return [float(b[4]) for b in bars[-200:]]
            if isinstance(bars, list) and bars and isinstance(bars[0], dict):
                return [float(b["close"]) for b in bars[-200:]]
        except Exception:
            continue
    return []


def classify_regime(closes: list[float]) -> dict:
    """Very cheap regime heuristic — NOT a model, just a label for weighting."""
    if len(closes) < 50:
        return {"regime": "unknown", "confidence": 0, "reason": "insufficient data"}
    recent = closes[-50:]
    long_ma = sum(closes[-50:]) / 50
    short_ma = sum(closes[-20:]) / 20
    # Realized vol proxy: mean abs % change of last 30 bars
    pct = [abs((recent[i] - recent[i - 1]) / recent[i - 1]) for i in range(1, len(recent))]
    vol = (sum(pct) / len(pct)) * 100 if pct else 0
    trend_strength = (short_ma - long_ma) / long_ma * 100

    if trend_strength > 3:
        regime = "bull_trend"
    elif trend_strength < -3:
        regime = "bear_trend"
    elif vol > 3:
        regime = "high_vol"
    elif vol < 0.8:
        regime = "low_vol"
    else:
        regime = "range"

    return {
        "regime": regime,
        "short_ma": round(short_ma, 2),
        "long_ma": round(long_ma, 2),
        "trend_strength_pct": round(trend_strength, 2),
        "realized_vol_pct": round(vol, 2),
        "samples": len(closes),
    }


def run() -> dict:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)

    conn = get_connection()
    try:
        strat_mem = build_strategy_memory(conn)
        with open(MEMORY_DIR / "strategy_memory.json", "w") as f:
            json.dump(strat_mem, f, indent=2)

        closes = _load_btc_closes()
        regime = classify_regime(closes)
        regime["generated_at"] = datetime.now(timezone.utc).isoformat()
        with open(MEMORY_DIR / "market_regime.json", "w") as f:
            json.dump(regime, f, indent=2)

        set_system_state(conn, "market_regime", regime["regime"])
    finally:
        conn.close()

    summary = {
        "strategies_memorised": len(strat_mem.get("strategies", {})),
        "regime": regime["regime"],
    }
    print(f"[memory_updater] {summary}")
    return summary


def main():
    argparse.ArgumentParser().parse_args()
    run()


if __name__ == "__main__":
    main()
