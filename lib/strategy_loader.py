"""Strategy loader: discovers strategies, syncs them into the DB registry, respects overrides.

Discovery sources:
  1. lib/strategy_library/**/*.py  — Python class files inheriting Strategy
  2. config/strategies/*.json      — legacy JSON configs (adapted via JSONStrategy)

Every discovered strategy is upserted into the strategy_registry table. The
loader returns a subset based on caller intent:
  - scanner wants live + paper strategies
  - backtester wants anything that's not disabled
  - tuner wants the full registry

Manual overrides in config/strategy_overrides.json always win:
  {
    "force_enable": ["internal.momentum_breakout"],
    "force_disable": ["freqtrade.foo_v3"],
    "pin_params":   {"internal.momentum_breakout": {"rsi_range": [55, 75]}}
  }
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import json
import os
import pkgutil
import sys
from pathlib import Path
from typing import Optional

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from lib.strategy_engine import Strategy, StrategyMetadata, MODE_BACKTEST, MODE_DISABLED, VALID_MODES
from lib.db import get_connection, upsert_strategy, list_strategies, get_strategy

STRATEGY_LIBRARY_DIR = os.path.join(PROJECT_ROOT, "lib", "strategy_library")
JSON_STRATEGY_DIR = os.path.join(PROJECT_ROOT, "config", "strategies")
OVERRIDES_PATH = os.path.join(PROJECT_ROOT, "config", "strategy_overrides.json")


# ── Override handling ────────────────────────────────────────────────────────
def load_overrides() -> dict:
    if not os.path.exists(OVERRIDES_PATH):
        return {"force_enable": [], "force_disable": [], "pin_params": {}}
    with open(OVERRIDES_PATH) as f:
        return json.load(f)


# ── JSON strategy adapter ────────────────────────────────────────────────────
class JSONStrategy(Strategy):
    """Wraps a legacy JSON-defined strategy so the old screener logic keeps working.

    JSON strategies get a minimal implementation — populate_indicators returns nothing,
    entry_signal returns None. They're actually evaluated by legacy screener.check_*
    functions. The adapter exists so they appear in the registry with the same
    mode/performance tracking as class strategies.
    """

    def __init__(self, config: dict):
        name = config["name"]
        slug = "internal." + name.lower().replace(" ", "_")
        self.metadata = StrategyMetadata(
            id=slug,
            name=name,
            description=config.get("description", ""),
            source="internal",
            version="json-v1",
            timeframes=config.get("preferred_timeframes", ["1h", "4h"]),
            preferred_assets=config.get("preferred_assets", []),
        )
        self.params = {**config.get("entry_conditions", {}),
                       **config.get("exit_conditions", {}),
                       **config.get("position_management", {})}
        self.safe_bounds = {}
        self._config = config
        super().__init__()

    @property
    def legacy_config(self) -> dict:
        return self._config

    def populate_indicators(self, ohlcv: dict) -> dict:
        return {}

    def entry_signal(self, indicators: dict, last_bar: dict):
        return None  # handled by legacy screener.check_* functions


# ── Class-based strategy discovery ───────────────────────────────────────────
def _import_from_path(path: str, module_name: str):
    """Import a single .py file as a module. Returns the module object."""
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def discover_class_strategies(library_dir: str = STRATEGY_LIBRARY_DIR) -> list[Strategy]:
    """Walk the strategy_library directory, import each .py, instantiate Strategy subclasses."""
    strategies: list[Strategy] = []
    root = Path(library_dir)
    if not root.exists():
        return strategies

    for py_file in root.rglob("*.py"):
        if py_file.name.startswith("_"):
            continue
        rel = py_file.relative_to(Path(PROJECT_ROOT))
        module_name = str(rel).replace(os.sep, ".").removesuffix(".py")
        try:
            module = _import_from_path(str(py_file), module_name)
        except Exception as e:
            print(f"[loader] Failed to import {py_file}: {e}")
            continue

        for _, obj in inspect.getmembers(module, inspect.isclass):
            if obj is Strategy or obj is JSONStrategy:
                continue
            if not issubclass(obj, Strategy):
                continue
            if obj.__module__ != module_name:
                continue  # skip re-exported imports
            if obj.metadata is None:
                continue  # abstract / not fully defined
            try:
                strategies.append(obj())
            except Exception as e:
                print(f"[loader] Failed to instantiate {obj.__name__}: {e}")
    return strategies


def discover_json_strategies(json_dir: str = JSON_STRATEGY_DIR) -> list[JSONStrategy]:
    """Load legacy JSON strategies as JSONStrategy adapters."""
    strategies: list[JSONStrategy] = []
    if not os.path.isdir(json_dir):
        return strategies
    for fname in sorted(os.listdir(json_dir)):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(json_dir, fname)
        try:
            with open(path) as f:
                cfg = json.load(f)
            if cfg.get("enabled", True):
                strategies.append(JSONStrategy(cfg))
        except Exception as e:
            print(f"[loader] Failed to load JSON strategy {path}: {e}")
    return strategies


# ── Registry sync ────────────────────────────────────────────────────────────
def sync_registry(strategies: list[Strategy]) -> None:
    """Upsert every discovered strategy into strategy_registry. New strategies start in backtest mode."""
    conn = get_connection()
    try:
        for s in strategies:
            m = s.metadata
            existing = get_strategy(conn, m.id)
            fields = {
                "name": m.name,
                "description": m.description,
                "source": m.source,
                "source_url": m.source_url,
                "source_commit": m.source_commit,
                "license": m.license,
                "version": m.version,
                "class_path": f"{type(s).__module__}.{type(s).__name__}",
                "timeframes_json": json.dumps(m.timeframes),
                "asset_classes_json": json.dumps(m.asset_classes),
                "params_json": json.dumps(s.effective_params),
                "safe_bounds_json": json.dumps(s.safe_bounds),
                "risk_notes": m.risk_notes,
            }
            if existing is None:
                fields["mode"] = MODE_BACKTEST
            upsert_strategy(conn, m.id, **fields)
    finally:
        conn.close()


# ── Main API ─────────────────────────────────────────────────────────────────
def load_all(include_disabled: bool = False, modes: Optional[set[str]] = None) -> list[Strategy]:
    """Discover, sync to registry, apply overrides, return filtered strategies.

    Args:
        include_disabled: include MODE_DISABLED strategies
        modes: if set, only return strategies currently in one of these modes

    Returns:
        List of instantiated Strategy objects with attribute `_registry_mode` set.
    """
    class_strategies = discover_class_strategies()
    class_ids = {s.metadata.id for s in class_strategies}
    json_strategies = [s for s in discover_json_strategies() if s.metadata.id not in class_ids]
    discovered = class_strategies + json_strategies
    sync_registry(discovered)

    overrides = load_overrides()
    force_disable = set(overrides.get("force_disable", []))
    force_enable = set(overrides.get("force_enable", []))
    pin_params = overrides.get("pin_params", {})

    conn = get_connection()
    try:
        registry = {r["id"]: r for r in list_strategies(conn)}
    finally:
        conn.close()

    result: list[Strategy] = []
    for s in discovered:
        sid = s.metadata.id
        reg = registry.get(sid, {})
        mode = reg.get("mode", MODE_BACKTEST)

        if sid in force_disable:
            mode = MODE_DISABLED
        elif sid in force_enable and mode == MODE_DISABLED:
            mode = MODE_BACKTEST

        if not include_disabled and mode in (MODE_DISABLED, "archived"):
            continue
        if modes is not None and mode not in modes:
            continue

        # Apply pinned params (won't raise — pin overrides safe_bounds)
        if sid in pin_params:
            try:
                for k, v in pin_params[sid].items():
                    s._effective_params[k] = v
            except Exception:
                pass

        s._registry_mode = mode
        result.append(s)
    return result


def load_active() -> list[Strategy]:
    """Shortcut: strategies currently in live or paper mode (used by the live scanner)."""
    return load_all(modes={"live", "paper"})


# ── CLI ──────────────────────────────────────────────────────────────────────
def main():
    import argparse
    parser = argparse.ArgumentParser(description="Discover and register strategies")
    parser.add_argument("--self-test", action="store_true", help="Discover, sync, and print summary")
    parser.add_argument("--list", action="store_true", help="List registered strategies")
    parser.add_argument("--mode", help="Filter by mode")
    args = parser.parse_args()

    if args.self_test:
        strategies = load_all(include_disabled=True)
        print(f"Discovered {len(strategies)} strategies:")
        by_source: dict = {}
        by_mode: dict = {}
        for s in strategies:
            by_source.setdefault(s.metadata.source, []).append(s.metadata.id)
            mode = getattr(s, "_registry_mode", "?")
            by_mode[mode] = by_mode.get(mode, 0) + 1
        for src, ids in sorted(by_source.items()):
            print(f"  [{src}] {len(ids)} strategies")
            for sid in ids:
                print(f"    - {sid}")
        print(f"\nBy mode: {by_mode}")
        return

    if args.list:
        conn = get_connection()
        try:
            rows = list_strategies(conn, mode=args.mode)
        finally:
            conn.close()
        print(f"{len(rows)} strategies in registry:")
        for r in rows:
            print(f"  [{r['mode']}] {r['id']:40s} v{r['version']} ({r['source']})")


if __name__ == "__main__":
    main()
