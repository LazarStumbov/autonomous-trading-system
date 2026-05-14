"""brain_pm_sanity_check — LLM veto layer between risk_gate_pm and execute_bet.

Reads `data/signals/<date>/pm_approved_bets.json`, runs each PASS bet through
the Polymarket Specialist persona, and emits `pm_brain_approved.json` with only
the bets that survived the brain veto.

This is the layer that would have killed the Aston Villa bet: 99.999%
implied probability with no wallet evidence → rule 1, extreme tail no wallet,
VETO `extreme_probability_no_wallet_evidence`.

Cost: ~$0.003 per bet (Sonnet 4.6 + prompt cache hit on the persona). With
the gates upstream (heuristic confluence ≥ 80, wallet evidence), expected
1-5 calls per cron tick — negligible.

When ANTHROPIC_API_KEY is missing or the monthly cap is hit, this script
falls back to a deterministic rule check that mirrors the persona's rules 1-3
(the most load-bearing ones), so the safety floor is preserved either way.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import pm_api  # noqa: E402

ROOT = pm_api.project_root()
sys.path.insert(0, str(ROOT))

from lib import llm_brain  # noqa: E402
from lib import agent_tools  # noqa: E402


SIGNALS_DIR = ROOT / "data" / "signals"


def _today_dir() -> Path:
    return SIGNALS_DIR / datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def _deterministic_fallback(bet: dict) -> dict:
    """Mirror persona rules 1-3 in pure Python.

    Runs when the LLM can't be called. Strict by design: when in doubt, veto.
    """
    method = (bet.get("discovery_method") or "").lower()
    price = float(bet.get("market_price") or 0)
    liquidity = float(bet.get("checks", {}).get("liquidity_usd")
                      or bet.get("liquidity_usd") or 0)
    hours = float(bet.get("hours_to_resolution") or 999)

    # Rule 1: extreme tail no wallet
    if method == "heuristic_paper" and (price < 0.05 or price > 0.95):
        return {"verdict": "VETO", "reason": "extreme_probability_no_wallet_evidence",
                "rule_hit": 1, "confidence": 1.0, "notes": "deterministic_fallback"}
    # Rule 2: heuristic thin liquidity
    if method == "heuristic_paper" and 0 < liquidity < 5000:
        return {"verdict": "VETO", "reason": "heuristic_thin_liquidity",
                "rule_hit": 2, "confidence": 0.9, "notes": "deterministic_fallback"}
    # Rule 3: near resolution thin book
    if hours < 48 and 0 < liquidity < 5000:
        return {"verdict": "VETO", "reason": "near_resolution_thin_book",
                "rule_hit": 3, "confidence": 0.9, "notes": "deterministic_fallback"}
    return {"verdict": "APPROVE", "reason": None, "rule_hit": None,
            "confidence": 0.6, "notes": "deterministic_fallback (no LLM)"}


def _build_user_payload(bet: dict) -> str:
    """Compact JSON payload for the persona — single market under review."""
    pm_history = agent_tools.get_pm_history(
        market_question_substr=(bet.get("market_question") or "").split()[0] if bet.get("market_question") else None,
        days=30,
    )
    tracked = agent_tools.get_tracked_wallets_summary()
    candidate = {
        "market_question": bet.get("market_question"),
        "outcome": bet.get("outcome"),
        "market_price": bet.get("market_price"),
        "estimated_probability": bet.get("estimated_probability"),
        "edge_pct": bet.get("edge_pct"),
        "confluence_score": bet.get("confluence_score"),
        "category": bet.get("category"),
        "hours_to_resolution": bet.get("hours_to_resolution") or bet.get("checks", {}).get("hours_to_resolution"),
        "liquidity_usd": bet.get("liquidity_usd") or bet.get("checks", {}).get("liquidity_usd"),
        "discovery_method": bet.get("discovery_method"),
        "discovery_evidence": _safe_json_load(bet.get("discovery_evidence")),
        "sized_bet_usd": bet.get("sized_bet_usd"),
    }
    return json.dumps({
        "candidate": candidate,
        "pm_history": pm_history,
        "tracked_wallets_summary": tracked,
    }, default=str)


def _safe_json_load(s):
    if not s:
        return None
    if isinstance(s, (dict, list)):
        return s
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return s


def _veto_via_brain(bet: dict) -> dict:
    system = llm_brain.load_prompt("_preamble") + "\n\n" + llm_brain.load_prompt("polymarket_specialist")
    user = _build_user_payload(bet)
    resp = llm_brain.call(
        job="brain_pm_sanity_check",
        tier="routine",
        system=system,
        user=user,
        max_tokens=400,
        temperature=0.1,
    )
    if resp.ok and resp.parsed:
        return resp.parsed
    # LLM unavailable / cap hit / parse failed → fall back, but tag the path
    fallback = _deterministic_fallback(bet)
    fallback["notes"] = f"{fallback.get('notes','')} (llm_unavailable: {resp.error or 'parse_failed'})"
    return fallback


def main() -> int:
    today = _today_dir()
    approved_path = today / "pm_approved_bets.json"
    if not approved_path.exists():
        print("[brain_pm_sanity_check] no approved bets — skip")
        return 0
    payload = _load(approved_path) or {}
    approved = payload.get("approved", [])
    if not approved:
        print("[brain_pm_sanity_check] zero approved — skip")
        # Still write empty downstream artifact so execute_bet doesn't double-process the upstream file
        (today / "pm_brain_approved.json").write_text(json.dumps({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "approved_count": 0,
            "vetoed_count": 0,
            "approved": [],
            "vetoed": [],
        }, indent=2))
        return 0

    brain_approved: list[dict] = []
    brain_vetoed: list[dict] = []
    for bet in approved:
        verdict = _veto_via_brain(bet)
        if str(verdict.get("verdict", "")).upper() == "APPROVE":
            bet["brain_verdict"] = verdict
            brain_approved.append(bet)
        else:
            brain_vetoed.append({
                "market_id": bet.get("market_id"),
                "market_question": bet.get("market_question"),
                "verdict": verdict,
                "discovery_method": bet.get("discovery_method"),
                "market_price": bet.get("market_price"),
            })
            print(f"[brain_pm_sanity_check] VETO {bet.get('market_id')}: "
                  f"{verdict.get('reason')} (rule {verdict.get('rule_hit')})")

    out = today / "pm_brain_approved.json"
    out.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "approved_count": len(brain_approved),
        "vetoed_count": len(brain_vetoed),
        "approved": brain_approved,
        "vetoed": brain_vetoed,
    }, indent=2))
    print(f"[brain_pm_sanity_check] approved={len(brain_approved)} vetoed={len(brain_vetoed)} → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())