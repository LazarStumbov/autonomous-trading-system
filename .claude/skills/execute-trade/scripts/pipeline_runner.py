"""Pipeline runner — the missing glue between alert_generator → risk_gate → order_builder → execute.

Reads today's alerts.json, loops each alert through the full chain:
  1. Risk gate (PASS/FAIL)
  2. Order builder (position sizing + leverage)
  3. Execution engine (paper fill or live order)

Called by the Modal cron after alert_generator.py writes alerts.json.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

def _find_project_root() -> Path:
    """Walk up from this file until we find the dir holding both lib/ and config/.
    Works locally (.../.claude/skills/execute-trade/scripts/) and in Modal (/app/skills/...).
    """
    p = Path(__file__).resolve()
    for candidate in [p, *p.parents]:
        if (candidate / "lib").is_dir() and (candidate / "config").is_dir():
            return candidate
    raise RuntimeError(f"project root not found from {__file__}")


PROJECT_ROOT = _find_project_root()
sys.path.insert(0, str(PROJECT_ROOT))


def _import_from_path(module_name: str, path: Path):
    """Import a Python module from an arbitrary filesystem path."""
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    mod = importlib.util.module_from_spec(spec)
    # Ensure the module can import its own siblings
    sys.path.insert(0, str(path.parent))
    spec.loader.exec_module(mod)
    return mod


def _find_risk_gate() -> Path:
    """Resolve risk_gate.py path for both Modal (/app/skills/) and local (.claude/skills/)."""
    for candidate in [
        PROJECT_ROOT / "skills" / "risk-check" / "scripts" / "risk_gate.py",
        PROJECT_ROOT / ".claude" / "skills" / "risk-check" / "scripts" / "risk_gate.py",
    ]:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("risk_gate.py not found — checked Modal and local paths")


def _load_alerts(alerts_path: Path | None) -> list[dict]:
    if alerts_path is None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        alerts_path = PROJECT_ROOT / "data" / "signals" / today / "alerts.json"
    if not alerts_path.exists():
        print(f"[pipeline_runner] no alerts file: {alerts_path}")
        return []
    return json.loads(alerts_path.read_text()).get("alerts", [])


def _get_capital() -> float:
    """Return current paper balance or configured starting capital."""
    try:
        from lib.paper_engine import is_paper_mode, get_paper_balance
        if is_paper_mode():
            return get_paper_balance()["total"]
    except Exception:
        pass
    try:
        from lib.risk_engine import load_risk_config
        return load_risk_config()["capital"]["initial_market_usd"]
    except Exception:
        return 250.0


def run(alerts_path: Path | None = None, dry_run: bool = False) -> dict:
    """Run the full pipeline for every alert with a complete entry/SL/TP set."""
    scripts_dir = Path(__file__).parent
    risk_gate_mod = _import_from_path("risk_gate", _find_risk_gate())
    order_builder_mod = _import_from_path("order_builder", scripts_dir / "order_builder.py")
    execution_engine_mod = _import_from_path("execution_engine", scripts_dir / "execution_engine.py")

    from lib.constants import get_effective_min_score
    effective_min = get_effective_min_score()

    alerts = _load_alerts(alerts_path)
    if not alerts:
        print("[pipeline_runner] no alerts — nothing to do")
        return {"attempted": 0, "passed": 0, "executed": 0, "failed_risk": 0, "errors": 0, "failed_tier": 0}

    capital = _get_capital()
    stats = {"attempted": 0, "passed": 0, "executed": 0, "failed_risk": 0, "errors": 0, "failed_tier": 0}

    for alert in alerts:
        entry = alert.get("entry_price")
        sl = alert.get("stop_loss")
        tp = alert.get("take_profit")

        if not all([entry, sl, tp]):
            print(f"[pipeline_runner] skip {alert.get('symbol')} — no entry/SL/TP from screener")
            continue

        stats["attempted"] += 1
        symbol = alert["symbol"]
        direction = alert["direction"]
        confluence = alert.get("confluence_score", 0)
        leverage = alert.get("suggested_leverage", 3)
        strategy = alert.get("strategy", "confluence")
        tier = alert.get("tier")

        # ── 0. Confluence gate (defense-in-depth) ─────────────────────────────
        # alert_generator should already filter; we reject again here so a stale
        # alerts.json or a future regression upstream can never silently execute
        # a NO_TRADE setup.
        if tier == "NO_TRADE" or confluence < effective_min:
            print(
                f"[pipeline_runner] TIER_FAIL {symbol} {direction} "
                f"tier={tier} score={confluence} threshold={effective_min}"
            )
            stats["failed_tier"] += 1
            continue

        # ── 1. Risk gate ──────────────────────────────────────────────────────
        try:
            proposal = {
                "asset": symbol,
                "direction": direction,
                "entry": entry,
                "sl": sl,
                "tp": tp,
                "leverage": leverage,
                "confluence": confluence,
                "capital": capital,
            }
            risk_result = risk_gate_mod.run_risk_gate(proposal)
        except Exception as e:
            print(f"[pipeline_runner] risk gate error {symbol}: {e}")
            stats["errors"] += 1
            continue

        if risk_result["verdict"] != "PASS":
            fails = "; ".join(risk_result.get("failures", []))
            print(f"[pipeline_runner] RISK_FAIL {symbol} {direction}: {fails}")
            stats["failed_risk"] += 1
            continue

        stats["passed"] += 1
        pos = risk_result.get("recommended_position", {})
        approved_leverage = pos.get("leverage", leverage)

        # ── 2. Build order ────────────────────────────────────────────────────
        try:
            order = order_builder_mod.build_order(
                asset=symbol,
                direction=direction,
                capital=capital,
                entry_price=entry,
                stop_loss_price=sl,
                take_profit_price=tp,
                leverage=approved_leverage,
                confluence_score=confluence,
                strategy=strategy,
            )
            if "error" in order:
                print(f"[pipeline_runner] order build error {symbol}: {order['error']}")
                stats["errors"] += 1
                continue
        except Exception as e:
            print(f"[pipeline_runner] order builder exception {symbol}: {e}")
            stats["errors"] += 1
            continue

        order["signals"] = alert.get("signal_summary", {})
        order["reasoning"] = json.dumps({
            "tier": alert.get("tier"),
            "conditions_met": alert.get("conditions_met", []),
            "signal_summary": alert.get("signal_summary", {}),
        }, default=str)

        # ── 3. Execute ────────────────────────────────────────────────────────
        if dry_run:
            rr = order.get("rr_ratio", "?")
            print(
                f"[pipeline_runner] DRY_RUN {symbol} {direction.upper()} "
                f"entry={entry} sl={sl} tp={tp} lev={approved_leverage}x "
                f"R:R={rr} confluence={confluence}"
            )
            stats["executed"] += 1
            continue

        try:
            exec_result = execution_engine_mod.execute_order(order, dry_run=False)
            status = exec_result.get("status", "UNKNOWN")
            print(
                f"[pipeline_runner] {status} {symbol} {direction.upper()} "
                f"trade_id={exec_result.get('trade_id', '?')} "
                f"fill={exec_result.get('fill_price', '?')}"
            )
            if status in ("EXECUTED", "DRY_RUN"):
                stats["executed"] += 1
            else:
                errs = exec_result.get("errors", [])
                print(f"[pipeline_runner] exec errors: {errs}")
                stats["errors"] += 1
        except Exception as e:
            print(f"[pipeline_runner] execution exception {symbol}: {e}")
            stats["errors"] += 1

    print(f"[pipeline_runner] done — {stats}")
    return stats


def main():
    parser = argparse.ArgumentParser(description="Run trade pipeline from alerts.json")
    parser.add_argument("--alerts-json", help="Path to alerts.json (default: today's file)")
    parser.add_argument("--dry-run", action="store_true", help="Validate and size without executing")
    args = parser.parse_args()

    alerts_path = Path(args.alerts_json) if args.alerts_json else None
    result = run(alerts_path=alerts_path, dry_run=args.dry_run)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
