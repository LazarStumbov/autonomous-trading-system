"""Confluence detector. Groups signals by asset and direction, counts independent signal sources."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from lib.constants import SignalType


def _load_json_safe(path: str) -> dict | list | None:
    """Read JSON tolerating empty/corrupt files. Returns None if unusable.

    Modal-synced volumes sometimes leave 0-byte placeholder files when a writer
    fails mid-run; without this, a single bad file crashes the entire scoring
    pipeline and the day's trades fall back to technicals-only.
    """
    try:
        with open(path) as f:
            text = f.read().strip()
        if not text:
            return None
        return json.loads(text)
    except (OSError, json.JSONDecodeError) as e:
        print(f"[confluence_detector] skipping {os.path.basename(path)}: {e}")
        return None


def _build_symbol_normalizer() -> dict[str, str]:
    """Map bare symbols (e.g. 'BTC', 'DOGE') to canonical perp form ('BTC/USDT:USDT').

    News and trader signals reference assets by their base symbol, while every
    other layer of the system uses the canonical broker symbol. Without this
    map, news/trader signals never group with the technical signals for the
    same asset.
    """
    norm: dict[str, str] = {}
    try:
        with open(os.path.join(PROJECT_ROOT, "config", "watchlist.json")) as f:
            wl = json.load(f).get("watchlist", {})
        for symbols in wl.values():
            if not isinstance(symbols, list):
                continue
            for s in symbols:
                norm[s.upper()] = s
                base = s.split("/")[0].upper()
                # First canonical perp form wins (avoid forex_via_crypto stealing BTC)
                if base and base not in norm and ":" in s:
                    norm[base] = s
    except Exception as e:
        print(f"[confluence_detector] watchlist normalization unavailable: {e}")
    return norm


def _normalize_symbol(raw: str, norm: dict[str, str]) -> str:
    """Resolve a bare symbol to its canonical form, or pass through unchanged."""
    if not raw:
        return ""
    return norm.get(raw.upper(), raw)


def load_signals_from_files(signals_dir: str = None) -> list[dict]:
    """Load all signals from today's signal files."""
    if signals_dir is None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        signals_dir = os.path.join(PROJECT_ROOT, "data", "signals", today)

    all_signals = []
    norm = _build_symbol_normalizer()

    # Load from technicals
    technicals = _load_json_safe(os.path.join(signals_dir, "technicals.json")) or {}
    for symbol, analysis in (technicals.get("analysis", {}) or {}).items():
        for sig in analysis.get("signals", []):
            all_signals.append({
                "symbol": _normalize_symbol(symbol, norm),
                "type": _classify_signal_type(sig.get("type", "")),
                "direction": "long" if sig.get("bias") == "bullish" else "short" if sig.get("bias") == "bearish" else None,
                "strength": 1.0,
                "source": "technical_analysis",
                "timeframe": sig.get("timeframe", ""),
                "detail": sig,
            })

    # Load from setups (screener output)
    setups_data = _load_json_safe(os.path.join(signals_dir, "setups.json")) or {}
    for setup in setups_data.get("setups", []) if isinstance(setups_data, dict) else []:
        all_signals.append({
            "symbol": _normalize_symbol(setup["symbol"], norm),
            "type": SignalType.TECHNICAL_BREAKOUT,
            "direction": setup["direction"],
            "strength": setup.get("confidence", 50) / 100,
            "source": f"screener_{setup['strategy']}",
            "timeframe": setup.get("timeframe", ""),
            "detail": setup,
        })

    # News signals — urgency_classifier writes `asset` (bare e.g. "BTC"),
    # not `symbol`. Accept both, and normalize bare symbols to canonical perps.
    news_data = _load_json_safe(os.path.join(signals_dir, "news_signals.json"))
    if news_data is not None:
        news_iter = news_data if isinstance(news_data, list) else news_data.get("signals", [])
        for sig in news_iter:
            raw = sig.get("asset") or sig.get("symbol") or ""
            all_signals.append({
                "symbol": _normalize_symbol(raw, norm),
                "type": SignalType.NEWS_CATALYST,
                "direction": sig.get("direction"),
                # urgency is 0-10; normalize to 0-1 so it composes with other strengths
                "strength": min(1.0, float(sig.get("urgency", 5)) / 10.0),
                "source": "news_monitor",
                "detail": sig,
            })

    # Trader signals — position_tracker also writes `asset`.
    trader_data = _load_json_safe(os.path.join(signals_dir, "trader_signals.json"))
    if trader_data is not None:
        trader_iter = trader_data if isinstance(trader_data, list) else trader_data.get("signals", [])
        for sig in trader_iter:
            raw = sig.get("asset") or sig.get("symbol") or ""
            all_signals.append({
                "symbol": _normalize_symbol(raw, norm),
                "type": SignalType.TRADER_ACCUMULATION,
                "direction": sig.get("direction"),
                "strength": min(1.0, float(sig.get("skill_score", 0.5))),
                "source": "signal_follow",
                "detail": sig,
            })

    # TradingView signals — alert_parser writes tv_setup.json; indicator_mapper
    # enriches it with signal_type. Glob tv_*.json so Phase 2 pull-scanner output
    # (tv_pull.json) lands in the same channel automatically.
    import glob as _glob
    for tv_path in sorted(_glob.glob(os.path.join(signals_dir, "tv_*.json"))):
        tv_data = _load_json_safe(tv_path)
        if tv_data is None:
            continue
        # Support three shapes: bare dict, list, or {signals: [...]} wrapper
        if isinstance(tv_data, list):
            setups = tv_data
        elif isinstance(tv_data, dict) and "signals" in tv_data:
            setups = tv_data["signals"]
        else:
            setups = [tv_data]
        for s in setups:
            raw = s.get("symbol") or s.get("asset") or ""
            direction = s.get("direction") or s.get("bias")
            if direction in ("bullish", "up"):
                direction = "long"
            elif direction in ("bearish", "down"):
                direction = "short"
            raw_type = s.get("signal_type") or s.get("type") or ""
            sig_type = _classify_tv_signal_type(raw_type)
            confidence = s.get("confidence") or s.get("strength") or 0.6
            all_signals.append({
                "symbol": _normalize_symbol(raw, norm),
                "type": sig_type,
                "direction": direction,
                "strength": min(1.0, float(confidence) if float(confidence) <= 1.0 else float(confidence) / 100.0),
                "source": "tradingview",
                "detail": s,
            })

    return all_signals


def _classify_tv_signal_type(raw_type: str) -> SignalType:
    """Map indicator_mapper output (or raw TV strings) to SignalType enum values."""
    t = (raw_type or "").lower()
    if t in ("mean_reversion", "mean reversion") or SignalType.MEAN_REVERSION.value == t:
        return SignalType.MEAN_REVERSION
    if t in ("structure", "structure_break") or SignalType.STRUCTURE_BREAK.value == t:
        return SignalType.STRUCTURE_BREAK
    if "volume" in t:
        return SignalType.VOLUME_ANOMALY
    if "sentiment" in t:
        return SignalType.SENTIMENT_SHIFT
    if any(k in t for k in ["momentum", "breakout", "trend_follow", "tv_generic"]):
        return SignalType.TECHNICAL_BREAKOUT
    # Fall through to the shared classifier for anything else
    return _classify_signal_type(t)


def _classify_signal_type(signal_name: str) -> str:
    """Map specific signal names to broad SignalType categories.

    Order matters: check volume/sentiment/cross-asset BEFORE the generic
    technical bucket so a strategy named e.g. "volume_breakout_v2" doesn't
    silently fall into TECHNICAL_BREAKOUT (which kept confluences at
    unique_types=1 for every paper trade in the May 7-11 baseline).
    """
    name = signal_name.lower()
    if "volume" in name or "vol_spike" in name or "vwap" in name:
        return SignalType.VOLUME_ANOMALY
    if "sentiment" in name:
        return SignalType.SENTIMENT_SHIFT
    if any(k in name for k in ["correlation", "cross_asset", "btc_dominance"]):
        return SignalType.CROSS_ASSET_CORRELATION
    if any(k in name for k in ["funding", "oi_", "open_interest", "accumulation"]):
        return SignalType.TRADER_ACCUMULATION
    if "news" in name or "catalyst" in name:
        return SignalType.NEWS_CATALYST
    if any(k in name for k in ["breakout", "ema", "macd", "rsi", "bb", "ichimoku", "donchian"]):
        return SignalType.TECHNICAL_BREAKOUT
    return SignalType.TECHNICAL_BREAKOUT


def detect_confluence(signals: list[dict]) -> list[dict]:
    """Group signals by symbol+direction and detect confluence.

    Returns:
        List of confluence groups, each with symbol, direction, signal count, and signal details.
    """
    # Group by (symbol, direction)
    groups = defaultdict(list)
    for sig in signals:
        if sig["direction"] is None:
            continue
        key = (sig["symbol"], sig["direction"])
        groups[key].append(sig)

    confluences = []
    for (symbol, direction), group_signals in groups.items():
        # Count unique signal types
        unique_types = set()
        for s in group_signals:
            unique_types.add(s["type"])

        confluences.append({
            "symbol": symbol,
            "direction": direction,
            "total_signals": len(group_signals),
            "unique_signal_types": len(unique_types),
            "signal_types": list(unique_types),
            "signals": group_signals,
            "avg_strength": sum(s["strength"] for s in group_signals) / len(group_signals),
        })

    # Sort by unique signal types (more types = stronger confluence)
    confluences.sort(key=lambda c: (c["unique_signal_types"], c["total_signals"]), reverse=True)

    return confluences


def save_confluences(confluences: list[dict], output_dir: str = None) -> str:
    """Save confluence detection results."""
    if output_dir is None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        output_dir = os.path.join(PROJECT_ROOT, "data", "signals", today)

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    filepath = os.path.join(output_dir, "confluences.json")

    # Serialize enums
    serializable = json.loads(json.dumps(confluences, default=str))

    with open(filepath, "w") as f:
        json.dump({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "confluences": serializable,
            "count": len(confluences),
        }, f, indent=2)

    return filepath


def main():
    parser = argparse.ArgumentParser(description="Detect signal confluence")
    parser.add_argument("--signals-dir", help="Directory with signal files")
    parser.add_argument("--no-save", action="store_true")
    args = parser.parse_args()

    signals = load_signals_from_files(args.signals_dir)
    print(f"Loaded {len(signals)} signals")

    confluences = detect_confluence(signals)

    if not args.no_save:
        path = save_confluences(confluences)
        print(f"Saved to: {path}")

    print(f"\n{len(confluences)} confluence groups:")
    for c in confluences:
        print(f"  {c['symbol']} {c['direction'].upper()}: "
              f"{c['unique_signal_types']} types, {c['total_signals']} signals, "
              f"avg strength {c['avg_strength']:.2f}")


if __name__ == "__main__":
    main()
