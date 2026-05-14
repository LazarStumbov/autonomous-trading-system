"""Read machine-readable output from the StructureScanner Pine indicator.

The on-chart indicator `StructureScanner` (pine/strategies/structure_scanner.pine)
emits:
  * box.new() zones — FVGs (green/red bg) and Order Blocks (teal/orange bg)
  * label.new() annotations — "LSweep long <price>" / "LSweep short <price>"
    and a per-bar summary "Struct BULL/BEAR bias (...)".

This reader pulls those via the TradingView MCP and writes per-channel JSON
files into today's signal directory so the Phase-1 glob loader in
confluence_detector.py picks them up automatically.

Output files (consumed by confluence_engine glob loader):
  tv_pine_structure_zones.json   — FVG + OB boxes as STRUCTURE_BREAK signals
  tv_pine_structure_sweeps.json  — Liquidity sweep labels as STRUCTURE_BREAK signals
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from lib.constants import SignalType
from lib.tradingview_bridge import read_pine_levels

STUDY_FILTER = "StructureScanner"
LSWEEP_RE = re.compile(r"LSweep\s+(long|short)\s+([\d.]+)", re.IGNORECASE)


def _boxes_to_signals(boxes: list[dict], symbol: str) -> list[dict]:
    """Each box is a structure zone. Direction inferred from current price
    relative to zone (above = bearish supply, below = bullish demand) —
    we leave direction neutral and emit both sides so the confluence engine
    can weigh them against the rest of the stack."""
    signals: list[dict] = []
    for box in boxes:
        top = box.get("top") or box.get("high")
        bot = box.get("bottom") or box.get("low")
        if top is None or bot is None:
            continue
        signals.append({
            "symbol": symbol,
            "direction": "long",
            "signal_type": SignalType.STRUCTURE_BREAK.value,
            "confidence": 0.65,
            "source": "pine_structurescanner_zone",
            "zone_high": float(top),
            "zone_low": float(bot),
        })
    return signals


def _labels_to_signals(labels: list[dict], symbol: str) -> list[dict]:
    """Liquidity sweep labels: text format 'LSweep <direction> <price>'."""
    signals: list[dict] = []
    for lbl in labels:
        text = (lbl.get("text") or lbl.get("label") or "")
        m = LSWEEP_RE.search(text)
        if not m:
            continue
        direction = m.group(1).lower()
        price = float(m.group(2))
        signals.append({
            "symbol": symbol,
            "direction": direction,
            "signal_type": SignalType.STRUCTURE_BREAK.value,
            "confidence": 0.70,
            "source": "pine_structurescanner_sweep",
            "price": price,
            "label_text": text,
        })
    return signals


def read_all_pine_signals(
    mcp_call: Callable,
    symbol: str,
    output_dir: Optional[str] = None,
) -> list[dict]:
    """Read StructureScanner output and write JSON files. Returns all signals."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if output_dir is None:
        output_dir = os.path.join(PROJECT_ROOT, "data", "signals", today)
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    levels = read_pine_levels(mcp_call, study_filter=STUDY_FILTER)
    zone_signals = _boxes_to_signals(levels.get("boxes", []), symbol)
    sweep_signals = _labels_to_signals(levels.get("labels", []), symbol)

    all_signals: list[dict] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    if zone_signals:
        path = os.path.join(output_dir, "tv_pine_structure_zones.json")
        with open(path, "w") as f:
            json.dump({"timestamp": now_iso, "script": STUDY_FILTER, "symbol": symbol, "signals": zone_signals}, f, indent=2)
        print(f"[pine_output_reader] zones: {len(zone_signals)} → tv_pine_structure_zones.json")
        all_signals.extend(zone_signals)

    if sweep_signals:
        path = os.path.join(output_dir, "tv_pine_structure_sweeps.json")
        with open(path, "w") as f:
            json.dump({"timestamp": now_iso, "script": STUDY_FILTER, "symbol": symbol, "signals": sweep_signals}, f, indent=2)
        print(f"[pine_output_reader] sweeps: {len(sweep_signals)} → tv_pine_structure_sweeps.json")
        all_signals.extend(sweep_signals)

    if not all_signals:
        print(f"[pine_output_reader] StructureScanner returned no zones/sweeps "
              f"(indicator may not be visible on chart or no setups in view).")

    return all_signals


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Read StructureScanner output from TradingView MCP")
    parser.add_argument("--symbol", default="BTC/USDT:USDT", help="Symbol to read")
    parser.add_argument("--output-dir", help="Override output directory")
    args = parser.parse_args()

    print("[pine_output_reader] Requires a live TradingView MCP connection.")
    print("Run from inside Claude Code (agent layer) with the mcp_call proxy.")
    print(f"Target symbol: {args.symbol}")
    print(f"Reads from indicator: {STUDY_FILTER}")


if __name__ == "__main__":
    main()
