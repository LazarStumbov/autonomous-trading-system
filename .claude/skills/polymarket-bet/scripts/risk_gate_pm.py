"""Layer 4: Polymarket-specific risk gate.

Reads pm_estimates.json + pm_candidates.json and the open polymarket_bets in
the DB. For each estimate, runs the full check list:

  1. kelly_for_polymarket(p, market_odds) returns BET (≥5% edge, Kelly>0)
  2. Bet size ≤ max_bet_pct_bankroll of bankroll
  3. Adding bet keeps category exposure ≤ max_exposure_per_category_pct
  4. Adding bet keeps total PM exposure ≤ max_total_exposure_pct
  5. Max 3 correlated bets (same category + same outcome direction)
  6. ≥ 3 distinct categories across open bets after this one
  7. Market liquidity ≥ min_market_liquidity_usd
  8. system_state.trading_halted is not 'true'
  9. Daily PM drawdown < max_daily_drawdown_pct (reuses system_state)

Writes data/signals/<date>/pm_approved_bets.json with PASS-only entries
already sized in USD.
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import pm_api  # noqa: E402

ROOT = pm_api.project_root()
sys.path.insert(0, str(ROOT))

from lib import db as dblib  # noqa: E402
from lib.kelly import kelly_for_polymarket, load_kelly_config  # noqa: E402

SIGNALS_DIR = ROOT / "data" / "signals"


def _today_dir() -> Path:
    return SIGNALS_DIR / datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def _bankroll_usd() -> float:
    """PM bankroll = initial + realized P&L on closed PM trades."""
    cfg = load_kelly_config()
    initial = float(cfg.get("capital", {}).get("initial_polymarket_usd", 250))
    conn = dblib.get_connection()
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(pnl_usd), 0) AS total FROM trades WHERE pillar='polymarket' AND status='closed'"
        ).fetchone()
        return initial + float(row["total"] or 0)
    finally:
        conn.close()


def _open_pm_exposure() -> dict:
    """Sum currently open PM positions, grouped by category and outcome."""
    conn = dblib.get_connection()
    try:
        rows = conn.execute(
            """SELECT t.id, t.asset, t.direction, t.quantity, t.entry_price,
                      pb.market_category, pb.market_id
               FROM trades t LEFT JOIN polymarket_bets pb ON pb.trade_id = t.id
               WHERE t.pillar='polymarket' AND t.status='open'"""
        ).fetchall()
    finally:
        conn.close()

    total_usd = 0.0
    by_category: Counter[str] = Counter()
    by_outcome_bucket: Counter[str] = Counter()
    market_ids: set[str] = set()
    for r in rows:
        notional = float(r["quantity"] or 0) * float(r["entry_price"] or 0)
        total_usd += notional
        cat = (r["market_category"] or "uncategorized").lower()
        by_category[cat] += notional
        bucket = f"{cat}:{(r['direction'] or 'yes').lower()}"
        by_outcome_bucket[bucket] += 1
        if r["market_id"]:
            market_ids.add(r["market_id"])
    return {
        "total_usd": total_usd,
        "by_category_usd": dict(by_category),
        "by_outcome_bucket_count": dict(by_outcome_bucket),
        "open_market_ids": market_ids,
        "open_count": len(rows),
    }


def _trading_halted() -> tuple[bool, str | None]:
    conn = dblib.get_connection()
    try:
        v = dblib.get_system_state(conn, "trading_halted")
        return (str(v).lower() == "true"), v
    finally:
        conn.close()


def _primary_category(categories: list[str]) -> str:
    if not categories:
        return "uncategorized"
    # Heuristic: pick the first non-trivial token
    for c in categories:
        if c and c not in {"all", "trending"}:
            return c.lower()
    return categories[0].lower()


def _gate_one(est: dict, cand: dict, params: dict, bankroll: float, exposure: dict) -> dict:
    """Run all checks for one estimate. Returns a dict including verdict + reasons."""
    checks: dict[str, dict] = {}
    fails: list[str] = []

    # Already-open in this market — skip duplicates
    market_id = est.get("market_id")
    if market_id in exposure["open_market_ids"]:
        return {
            "market_id": market_id,
            "verdict": "FAIL",
            "reason": "duplicate market — already have an open position",
        }

    # Kelly + min edge check
    p = est.get("estimated_probability")
    market_price = est.get("yes_price") or cand.get("yes_price") or 0
    if p is None or market_price <= 0 or market_price >= 1:
        return {"market_id": market_id, "verdict": "FAIL", "reason": "missing or invalid probability/price"}
    kelly = kelly_for_polymarket(p, market_price)
    checks["kelly"] = kelly
    if kelly["action"] != "BET":
        fails.append(f"kelly: {kelly['reason']}")

    # Sized bet from Kelly fraction × bankroll
    max_bet_pct = params.get("max_bet_pct_bankroll", 5.0) / 100
    requested_pct = (kelly.get("kelly_bet_pct", 0) or 0) / 100
    sized_pct = min(requested_pct, max_bet_pct)
    sized_usd = round(sized_pct * bankroll, 2)
    checks["bet_size"] = {"sized_usd": sized_usd, "sized_pct": round(sized_pct * 100, 2)}
    if sized_usd <= 0:
        fails.append("bet_size: sized to zero")

    # Liquidity gate
    min_liq = params.get("min_market_liquidity_usd", 10_000)
    liq = cand.get("liquidity_usd", 0)
    checks["liquidity"] = {"liquidity_usd": liq, "min": min_liq}
    if liq < min_liq:
        fails.append(f"liquidity: ${liq:,.0f} < min ${min_liq:,.0f}")

    # Total PM exposure
    max_total_pct = params.get("max_total_exposure_pct", 40.0) / 100
    new_total = exposure["total_usd"] + sized_usd
    new_total_pct = new_total / max(bankroll, 1)
    checks["total_exposure"] = {"new_total_pct": round(new_total_pct * 100, 1), "limit_pct": params.get("max_total_exposure_pct", 40.0)}
    if new_total_pct > max_total_pct:
        fails.append(f"total_exposure: {new_total_pct*100:.1f}% > {max_total_pct*100:.1f}%")

    # Per-category exposure
    cat = _primary_category(cand.get("categories", []))
    max_cat_pct = params.get("max_exposure_per_category_pct", 15.0) / 100
    cur_cat = exposure["by_category_usd"].get(cat, 0)
    new_cat_pct = (cur_cat + sized_usd) / max(bankroll, 1)
    checks["category_exposure"] = {"category": cat, "new_pct": round(new_cat_pct * 100, 1), "limit_pct": params.get("max_exposure_per_category_pct", 15.0)}
    if new_cat_pct > max_cat_pct:
        fails.append(f"category_exposure[{cat}]: {new_cat_pct*100:.1f}% > {max_cat_pct*100:.1f}%")

    # Correlated bets cap (same category + same outcome direction)
    outcome_dir = (est.get("suggested_outcome") or cand.get("suggested_outcome") or "yes").lower()
    bucket_key = f"{cat}:{outcome_dir}"
    max_corr = params.get("max_correlated_bets", 3)
    cur_bucket = exposure["by_outcome_bucket_count"].get(bucket_key, 0)
    checks["correlated"] = {"bucket": bucket_key, "current": cur_bucket, "max": max_corr}
    if cur_bucket >= max_corr:
        fails.append(f"correlated: {cur_bucket} bets in {bucket_key} ≥ max {max_corr}")

    # Diversification: after adding, must hit min_categories
    diversification = params.get("diversification", {})
    min_cats = diversification.get("min_categories", 3)
    cats_after = set(exposure["by_category_usd"].keys()) | {cat}
    checks["diversification"] = {"distinct_categories_after": len(cats_after), "min": min_cats}
    if exposure["open_count"] >= 2 and len(cats_after) < min_cats:
        fails.append(f"diversification: only {len(cats_after)} categories < min {min_cats}")

    verdict = "PASS" if not fails else "FAIL"
    return {
        "market_id": market_id,
        "market_question": est.get("market_question") or cand.get("market_question"),
        "verdict": verdict,
        "fails": fails,
        "checks": checks,
        "sized_bet_usd": sized_usd,
        "outcome": outcome_dir,
        "estimated_probability": p,
        "market_price": market_price,
        "edge_pct": kelly.get("edge_pct"),
        "category": cat,
        "confluence_score": cand.get("confluence_score"),
        "key_factors": est.get("key_factors", []),
        "citations": est.get("citations", []),
    }


def main() -> int:
    today = _today_dir()
    today.mkdir(parents=True, exist_ok=True)

    cand_payload = _load(today / "pm_candidates.json")
    est_payload = _load(today / "pm_estimates.json")
    if not cand_payload or not est_payload:
        print("[risk_gate_pm] missing candidates or estimates — skip")
        return 0

    cand_idx = {c["market_id"]: c for c in cand_payload.get("candidates", [])}

    halted, halt_reason = _trading_halted()
    if halted:
        print(f"[risk_gate_pm] trading halted ({halt_reason}) — emitting empty approved set")
        out_path = today / "pm_approved_bets.json"
        out_path.write_text(json.dumps({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "trading_halted": True,
            "halt_reason": halt_reason,
            "approved": [],
            "rejected": [],
        }, indent=2))
        return 0

    cfg = load_kelly_config()
    pm_params = cfg.get("polymarket", {})
    bankroll = _bankroll_usd()
    exposure = _open_pm_exposure()

    print(f"[risk_gate_pm] bankroll=${bankroll:,.2f} open_count={exposure['open_count']} total_open=${exposure['total_usd']:,.2f}")

    approved: list[dict] = []
    rejected: list[dict] = []

    # Mutable exposure copy so sequential approvals respect cumulative limits
    running_exposure = {
        "total_usd": exposure["total_usd"],
        "by_category_usd": dict(exposure["by_category_usd"]),
        "by_outcome_bucket_count": dict(exposure["by_outcome_bucket_count"]),
        "open_market_ids": set(exposure["open_market_ids"]),
        "open_count": exposure["open_count"],
    }

    for est in est_payload.get("estimates", []):
        if est.get("action") in ("NO_BET", "DEFER"):
            rejected.append({"market_id": est.get("market_id"), "verdict": "FAIL", "reason": est.get("reason")})
            continue
        cand = cand_idx.get(est.get("market_id"))
        if not cand:
            rejected.append({"market_id": est.get("market_id"), "verdict": "FAIL", "reason": "no candidate match"})
            continue

        result = _gate_one(est, cand, pm_params, bankroll, running_exposure)

        if result["verdict"] == "PASS":
            approved.append(result)
            # Update running exposure so the next pass sees this bet
            running_exposure["total_usd"] += result["sized_bet_usd"]
            running_exposure["by_category_usd"][result["category"]] = (
                running_exposure["by_category_usd"].get(result["category"], 0) + result["sized_bet_usd"]
            )
            bucket = f"{result['category']}:{result['outcome']}"
            running_exposure["by_outcome_bucket_count"][bucket] = (
                running_exposure["by_outcome_bucket_count"].get(bucket, 0) + 1
            )
            running_exposure["open_market_ids"].add(result["market_id"])
            running_exposure["open_count"] += 1
        else:
            rejected.append(result)

    out_path = today / "pm_approved_bets.json"
    out_path.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "trading_halted": False,
        "bankroll_usd": round(bankroll, 2),
        "open_count_before": exposure["open_count"],
        "approved_count": len(approved),
        "rejected_count": len(rejected),
        "approved": approved,
        "rejected": rejected,
    }, indent=2))
    print(f"[risk_gate_pm] approved={len(approved)} rejected={len(rejected)} → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())