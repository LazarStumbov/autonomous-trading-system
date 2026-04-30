"""Final risk gate. Runs ALL risk checks and returns consolidated PASS/FAIL verdict.

This is the single entry point before any trade execution.
Takes a trade proposal (from confluence alert) and validates everything.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from lib.risk_engine import check_trade, load_risk_config
from lib.db import get_connection, init_db, log_signal
from lib.category_cooldown import is_category_in_cooldown, asset_to_category


def run_risk_gate(trade_proposal: dict) -> dict:
    """Run full risk validation on a trade proposal.

    Args:
        trade_proposal: Dict with keys:
            - asset: str (e.g. "BTC/USDT:USDT")
            - direction: str ("long" or "short")
            - entry: float (entry price)
            - sl: float (stop loss price)
            - tp: float (take profit price)
            - leverage: float (requested leverage)
            - confluence: float (confluence score 0-100)
            - capital: float (optional, defaults to config)

    Returns:
        Dict with verdict, position sizing, and all check details.
    """
    config = load_risk_config()
    # In paper-mode, use the dynamic virtual balance so position sizing
    # tracks real wins/losses (compounding works as it would on a real account).
    try:
        from lib.paper_engine import is_paper_mode, get_paper_balance
        if is_paper_mode():
            default_capital = get_paper_balance()["total"]
        else:
            default_capital = config["capital"]["initial_market_usd"]
    except Exception:
        default_capital = config["capital"]["initial_market_usd"]
    capital = trade_proposal.get("capital", default_capital)

    # ── Category-cooldown gate (runs BEFORE the heavyweight risk engine) ────
    # If this asset's category is on cooldown after consecutive losses, fail
    # fast with a clear reason. The category cooldown is set by
    # `lib.category_cooldown.register_trade_close()` on trade close.
    asset = trade_proposal["asset"]
    category = asset_to_category(asset)
    try:
        init_db()
        cd_conn = get_connection()
        in_cd, until = is_category_in_cooldown(cd_conn, category)
        cd_conn.close()
    except Exception as e:
        # Cooldown lookup must NEVER block a trade due to infra error — we'd
        # rather fall through to the main risk engine.
        in_cd, until = False, None
        print(f"[risk_gate] category cooldown lookup failed: {e}")

    if in_cd:
        result = {
            "verdict": "FAIL",
            "failures": [f"category_cooldown_active:{category}_until_{until}"],
            "checks": {
                "category_cooldown": {
                    "verdict": "FAIL",
                    "reason": f"{category} is in cooldown until {until} after consecutive losses.",
                }
            },
            "recommended_position": {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trade_proposal": trade_proposal,
            "capital": capital,
        }
        _log_risk_check(trade_proposal, result)
        return result

    # Run the consolidated check from risk_engine
    result = check_trade(
        capital=capital,
        asset=trade_proposal["asset"],
        direction=trade_proposal["direction"],
        entry_price=trade_proposal["entry"],
        stop_loss_price=trade_proposal["sl"],
        take_profit_price=trade_proposal["tp"],
        requested_leverage=trade_proposal.get("leverage", 3),
        confluence_score=trade_proposal.get("confluence", 0),
    )

    # Enhance with metadata
    result["timestamp"] = datetime.now(timezone.utc).isoformat()
    result["trade_proposal"] = trade_proposal
    result["capital"] = capital

    # Log the risk check result
    _log_risk_check(trade_proposal, result)

    return result


def _log_risk_check(proposal: dict, result: dict):
    """Log risk check to database."""
    try:
        init_db()
        conn = get_connection()
        log_signal(
            conn,
            signal_type="risk_check",
            asset=proposal["asset"],
            direction=proposal["direction"],
            strength=proposal.get("confluence", 0),
            source="risk_gate",
            details_json=json.dumps({
                "verdict": result["verdict"],
                "failures": result["failures"],
                "position": result.get("recommended_position", {}),
            }, default=str),
            acted_on=1 if result["verdict"] == "PASS" else 0,
        )
        conn.close()
    except Exception as e:
        print(f"Warning: DB logging failed: {e}")


def format_result(result: dict) -> str:
    """Format risk gate result for display."""
    verdict = result["verdict"]
    lines = [
        f"{'=' * 50}",
        f"  RISK GATE: {verdict}",
        f"{'=' * 50}",
    ]

    proposal = result.get("trade_proposal", {})
    lines.append(f"  Asset: {proposal.get('asset', '?')}")
    lines.append(f"  Direction: {proposal.get('direction', '?').upper()}")
    lines.append(f"  Entry: {proposal.get('entry', '?')}")
    lines.append(f"  Stop Loss: {proposal.get('sl', '?')}")
    lines.append(f"  Take Profit: {proposal.get('tp', '?')}")
    lines.append(f"  Confluence: {proposal.get('confluence', '?')}")
    lines.append("")

    if result["failures"]:
        lines.append("  FAILURES:")
        for f in result["failures"]:
            lines.append(f"    [X] {f}")
        lines.append("")

    checks = result.get("checks", {})
    lines.append("  CHECK RESULTS:")
    for name, check in checks.items():
        v = check.get("verdict", "?")
        icon = "OK" if v == "PASS" else "XX"
        reason = check.get("reason", "")
        lines.append(f"    [{icon}] {name}: {reason}")

    if verdict == "PASS":
        pos = result.get("recommended_position", {})
        lines.append("")
        lines.append("  APPROVED POSITION:")
        lines.append(f"    Size: {pos.get('size', '?')}")
        lines.append(f"    Leverage: {pos.get('leverage', '?')}x")
        lines.append(f"    Risk: ${pos.get('risk_usd', '?')}")
        lines.append(f"    SL: {pos.get('stop_loss', '?')}")
        lines.append(f"    TP: {pos.get('take_profit', '?')}")

    lines.append(f"{'=' * 50}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Run risk gate on a trade proposal")
    parser.add_argument("--trade-json", help="JSON string of trade proposal")
    parser.add_argument("--asset", help="Asset symbol")
    parser.add_argument("--direction", choices=["long", "short"])
    parser.add_argument("--entry", type=float)
    parser.add_argument("--sl", type=float)
    parser.add_argument("--tp", type=float)
    parser.add_argument("--leverage", type=float, default=3)
    parser.add_argument("--confluence", type=float, default=0)
    parser.add_argument("--capital", type=float)
    parser.add_argument("--json-output", action="store_true", help="Output raw JSON")

    args = parser.parse_args()

    if args.trade_json:
        proposal = json.loads(args.trade_json)
    elif args.asset and args.direction and args.entry and args.sl and args.tp:
        proposal = {
            "asset": args.asset,
            "direction": args.direction,
            "entry": args.entry,
            "sl": args.sl,
            "tp": args.tp,
            "leverage": args.leverage,
            "confluence": args.confluence,
        }
        if args.capital:
            proposal["capital"] = args.capital
    else:
        parser.error("Provide either --trade-json or individual parameters (--asset, --direction, --entry, --sl, --tp)")

    result = run_risk_gate(proposal)

    if args.json_output:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(format_result(result))


if __name__ == "__main__":
    main()
