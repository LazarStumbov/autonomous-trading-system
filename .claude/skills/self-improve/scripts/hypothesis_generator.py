"""Weekly hypothesis generator.

Reviews the past week's trades + strategy-performance table and proposes
three kinds of hypotheses:

  1. `param_tweak`     — a parameter nudge on an existing live strategy that
                         looks like it has room to improve.
  2. `new_variant`     — a clone of an existing strategy with a different set
                         of params (must stay inside `safe_bounds`).
  3. `new_strategy`    — a synthesised idea inspired by patterns in winners
                         (low-volume seed; mostly param_tweak / new_variant
                         will dominate).

Every accepted hypothesis:
  * Is logged in the `strategy_hypotheses` table with rationale and params.
  * If it's a variant / new strategy, registers a NEW row in
    `strategy_registry` with `mode = backtest` — it **cannot** skip the gate.
  * Is picked up by the nightly `lib/backtester.py --promote-all` pass, which
    then decides whether to promote it to paper.

Respects the loop-level circuit breaker: if
`system_state['hypothesis_loop_paused_until']` is in the future, this script
no-ops and logs the pause.

Uses Anthropic API (Claude) if ANTHROPIC_API_KEY is set. Otherwise falls back
to a deterministic heuristic proposer so the pipeline keeps functioning
offline. Either way the *gates* are what keep bad ideas out of live capital —
no human-in-the-loop is required here.

Run weekly (Sunday 12:00 UTC) from Modal after the weekly review.
"""

from __future__ import annotations

import argparse
import copy
import importlib
import json
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from lib.db import (
    get_connection,
    list_strategies,
    get_strategy,
    get_system_state,
    log_hypothesis,
    upsert_strategy,
)

OUT_DIR = Path(PROJECT_ROOT) / "data" / "hypotheses"


# ── Circuit-breaker gate ─────────────────────────────────────────────────────
def _loop_paused(conn) -> str | None:
    until = get_system_state(conn, "hypothesis_loop_paused_until")
    if not until:
        return None
    try:
        dt = datetime.fromisoformat(until.replace("Z", "+00:00"))
    except Exception:
        return None
    if dt > datetime.now(timezone.utc):
        return until
    return None


# ── Strategy-class introspection (for safe_bounds access) ────────────────────
def _load_class(class_path: str):
    if not class_path or "." not in class_path:
        return None
    try:
        mod_path, cls_name = class_path.rsplit(".", 1)
        mod = importlib.import_module(mod_path)
        return getattr(mod, cls_name, None)
    except Exception:
        return None


def _current_params(strategy_row: dict) -> dict:
    raw = strategy_row.get("params_json")
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            pass
    cls = _load_class(strategy_row.get("class_path", ""))
    return dict(getattr(cls, "params", {}) or {}) if cls else {}


def _safe_bounds(strategy_row: dict) -> dict:
    raw = strategy_row.get("safe_bounds_json")
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            pass
    cls = _load_class(strategy_row.get("class_path", ""))
    return dict(getattr(cls, "safe_bounds", {}) or {}) if cls else {}


def _within_bounds(params: dict, bounds: dict) -> bool:
    for k, v in params.items():
        if k in bounds:
            lo, hi = bounds[k]
            if not (lo <= v <= hi):
                return False
    return True


# ── Performance snapshot for the prompt + heuristic ──────────────────────────
def _performance_snapshot(conn) -> list[dict]:
    rows = conn.execute(
        """SELECT sr.id, sr.name, sr.mode, sr.source,
                  sp.total_trades, sp.win_rate, sp.profit_factor,
                  sp.last_20_win_rate, sp.sharpe_30d, sp.consecutive_losses
           FROM strategy_registry sr
           LEFT JOIN strategy_performance sp ON sp.strategy_id = sr.id
           WHERE sr.mode IN ('live', 'paper')
           ORDER BY COALESCE(sp.total_trades, 0) DESC"""
    ).fetchall()
    return [dict(r) for r in rows]


# ── Heuristic proposer (offline / no LLM fallback) ───────────────────────────
def _heuristic_tweak(strategy_row: dict, perf: dict) -> dict | None:
    """Nudge the single param that looks most 'adjustable' for this strategy."""
    params = _current_params(strategy_row)
    bounds = _safe_bounds(strategy_row)
    if not params or not bounds:
        return None

    tunable = [k for k in params if k in bounds]
    if not tunable:
        return None

    # Prefer SL / leverage tweaks when strategy is losing; RR tweaks when winning
    wr = (perf.get("last_20_win_rate") or perf.get("win_rate") or 0.5)
    if wr < 0.45:
        priority = ["stop_loss_atr_multiplier", "default_leverage", "risk_pct"]
    else:
        priority = ["take_profit_rr_ratio", "stop_loss_atr_multiplier"]
    target = next((k for k in priority if k in tunable), tunable[0])

    lo, hi = bounds[target]
    current = params[target]
    direction = 1 if wr >= 0.45 else -1        # winners → widen TP; losers → tighten SL
    step = (hi - lo) * 0.1
    proposed_val = max(lo, min(hi, current + direction * step))
    if abs(proposed_val - current) < 1e-6:
        return None

    new_params = dict(params)
    new_params[target] = round(proposed_val, 4)

    rationale = (
        f"Heuristic tweak: last_20 win-rate={wr:.2f} — "
        f"adjust {target} from {current} to {new_params[target]} "
        f"(bounds {lo}..{hi})."
    )
    return {
        "hypothesis_type": "param_tweak",
        "parent_strategy_id": strategy_row["id"],
        "new_params": new_params,
        "changed_param": target,
        "rationale": rationale,
    }


# ── Optional LLM proposer (Anthropic) ────────────────────────────────────────
def _llm_propose(perf_rows: list[dict], bounds_by_id: dict) -> list[dict]:
    """Ask Claude to propose hypotheses. Returns [] if API unavailable."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return []
    try:
        import anthropic  # type: ignore
    except ImportError:
        return []

    client = anthropic.Anthropic(api_key=api_key)
    prompt = (
        "You are a quantitative trading strategy tuner. Propose 1-3 parameter "
        "tweaks for underperforming strategies and 0-1 new_variant ideas. "
        "Each tweak must stay within safe_bounds. Respond with STRICT JSON: "
        '{"hypotheses": [{"hypothesis_type":"param_tweak","parent_strategy_id":'
        '"<id>","new_params":{...},"changed_param":"<name>","rationale":"..."}]}'
    )
    user_block = json.dumps(
        {"strategies": perf_rows, "safe_bounds": bounds_by_id},
        default=str,
    )
    try:
        resp = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=2000,
            system=prompt,
            messages=[{"role": "user", "content": user_block}],
        )
        text = "".join(getattr(b, "text", "") for b in resp.content)
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            return []
        data = json.loads(text[start : end + 1])
        out = data.get("hypotheses", [])
        return out if isinstance(out, list) else []
    except Exception as e:
        print(f"[hypothesis_generator] LLM call failed: {e}")
        return []


# ── Applying a hypothesis: register + log ────────────────────────────────────
def _register_variant(conn, parent: dict, proposal: dict) -> str:
    """Create a new strategy_registry row (mode=backtest) cloned from parent."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    new_id = f"{parent['id']}__v_{stamp}_{random.randint(100, 999)}"
    upsert_strategy(
        conn,
        new_id,
        name=f"{parent['name']} (variant {stamp})",
        description=f"Auto-generated variant. Rationale: {proposal.get('rationale','')}",
        source=parent.get("source", "auto"),
        source_url=parent.get("source_url"),
        license=parent.get("license"),
        version="0.1.0",
        class_path=parent.get("class_path"),
        timeframes_json=parent.get("timeframes_json"),
        asset_classes_json=parent.get("asset_classes_json"),
        mode="backtest",
        params_json=json.dumps(proposal["new_params"]),
        safe_bounds_json=parent.get("safe_bounds_json"),
        risk_notes=parent.get("risk_notes"),
    )
    return new_id


def _apply(conn, proposal: dict, *, auto_apply: bool) -> dict:
    hypo_type = proposal.get("hypothesis_type", "param_tweak")
    parent_id = proposal.get("parent_strategy_id")
    parent = get_strategy(conn, parent_id) if parent_id else None
    if parent is None:
        return {"skipped": True, "reason": f"unknown parent {parent_id}"}

    bounds = _safe_bounds(parent)
    new_params = proposal.get("new_params") or {}
    if not _within_bounds(new_params, bounds):
        return {"skipped": True, "reason": f"out-of-bounds params for {parent_id}"}

    new_strategy_id = None
    if auto_apply and hypo_type in ("new_variant", "new_strategy", "param_tweak"):
        # For param_tweak we ALSO clone — we never in-place mutate a live strategy's
        # params. The variant races through backtest → paper → live on its own merit.
        new_strategy_id = _register_variant(conn, parent, proposal)

    hypo_id = log_hypothesis(
        conn,
        hypothesis_type=hypo_type,
        parent_strategy_id=parent_id,
        new_strategy_id=new_strategy_id,
        rationale=proposal.get("rationale", ""),
        proposed_params_json=json.dumps(new_params),
        status="pending_backtest",
    )
    return {
        "hypothesis_id": hypo_id,
        "new_strategy_id": new_strategy_id,
        "type": hypo_type,
        "parent": parent_id,
    }


# ── Orchestration ────────────────────────────────────────────────────────────
def run(*, auto_apply: bool = True, max_proposals: int = 4) -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    conn = get_connection()
    try:
        paused_until = _loop_paused(conn)
        if paused_until:
            msg = f"hypothesis loop paused until {paused_until} — no-op"
            print(f"[hypothesis_generator] {msg}")
            return {"paused_until": paused_until, "proposals": 0}

        perf_rows = _performance_snapshot(conn)
        bounds_by_id = {}
        for row in perf_rows:
            s = get_strategy(conn, row["id"])
            if s:
                bounds_by_id[row["id"]] = _safe_bounds(s)

        # Try LLM first, fall back to heuristic
        proposals = _llm_propose(perf_rows, bounds_by_id)
        if not proposals:
            # Focus heuristic on the 3 worst last_20 win rates
            sorted_perf = sorted(
                perf_rows,
                key=lambda r: (r.get("last_20_win_rate") or r.get("win_rate") or 1.0),
            )[:3]
            for row in sorted_perf:
                s = get_strategy(conn, row["id"])
                if not s:
                    continue
                prop = _heuristic_tweak(s, row)
                if prop:
                    proposals.append(prop)

        proposals = proposals[:max_proposals]

        applied = []
        for prop in proposals:
            result = _apply(conn, prop, auto_apply=auto_apply)
            applied.append({"proposal": prop, "result": result})

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        with open(OUT_DIR / f"hypotheses_{stamp}.json", "w") as f:
            json.dump({"generated_at": stamp, "applied": applied}, f, indent=2, default=str)

        print(
            f"[hypothesis_generator] proposals={len(proposals)} "
            f"auto_apply={auto_apply} "
            f"registered={sum(1 for a in applied if a['result'].get('new_strategy_id'))}"
        )
        return {"proposals": len(proposals), "applied": applied}
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--auto-apply", action="store_true", help="Register variants immediately (default on)")
    ap.add_argument("--dry-run", action="store_true", help="Propose but do not register variants")
    ap.add_argument("--max", type=int, default=4, help="Max proposals this run")
    args = ap.parse_args()
    auto = not args.dry_run  # auto by default
    run(auto_apply=auto, max_proposals=args.max)


if __name__ == "__main__":
    main()
