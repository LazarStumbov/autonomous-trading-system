"""Layer 5: Polymarket bet execution.

Reads pm_approved_bets.json and persists each approved bet:
  - Always writes to DB (trades + polymarket_bets) with status='paper' by default.
  - Sends a Telegram alert with key context.
  - Mirrors the bet to memory/POLYMARKET-LOG.md for human audit.
  - Live execution path (--live) is gated behind the PM_LIVE_TRADING env var
    AND requires py-clob-client signing — not yet wired (Phase 2).

Usage:
  python execute_bet.py            # paper mode (default)
  python execute_bet.py --live     # only honored if PM_LIVE_TRADING=true env

Idempotency: dedupes on (market_id, today) to prevent double-posting if the
cron runs twice within a cycle.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import pm_api  # noqa: E402

ROOT = pm_api.project_root()
sys.path.insert(0, str(ROOT))

from lib import db as dblib  # noqa: E402
from lib import notifier  # noqa: E402
from lib import markdown_memory as mm  # noqa: E402

SIGNALS_DIR = ROOT / "data" / "signals"


def _today_dir() -> Path:
    return SIGNALS_DIR / datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _already_persisted(conn, market_id: str) -> bool:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    row = conn.execute(
        """SELECT t.id FROM trades t
             JOIN polymarket_bets pb ON pb.trade_id = t.id
            WHERE pb.market_id = ? AND date(t.timestamp) = ?
            LIMIT 1""",
        (market_id, today),
    ).fetchone()
    return row is not None


def _strategy_for(discovery_method: str | None) -> str:
    """Map a discovery_method tag to the strategy_registry slug that owns the bet.

    Heuristic bets don't deserve the polymarket-smart-money label. Routing them
    to polymarket-heuristic keeps post-mortem analytics honest.
    """
    if not discovery_method or discovery_method == "heuristic_paper":
        return "polymarket-heuristic"
    return "polymarket-smart-money"


def _persist(conn, bet: dict, mode: str) -> int:
    """Insert trades + polymarket_bets rows. Returns trade_id."""
    qty = round(bet["sized_bet_usd"] / max(bet["market_price"], 0.001), 4)
    reasoning = json.dumps({
        "key_factors": bet.get("key_factors", []),
        "citations": bet.get("citations", []),
        "fails": bet.get("fails", []),
        "discovery_method": bet.get("discovery_method"),
    })
    strategy = _strategy_for(bet.get("discovery_method"))
    trade_id = dblib.log_trade(
        conn,
        pillar="polymarket",
        asset=bet.get("market_question", bet["market_id"])[:120],
        direction=bet["outcome"],
        entry_price=bet["market_price"],
        quantity=qty,
        leverage=1.0,
        # Schema CHECK constraint allows {open, closed, cancelled}; we tag
        # paper-vs-live via the `broker` field instead of inventing a status.
        status="open",
        strategy=strategy,
        confluence_score=bet.get("confluence_score"),
        reasoning=reasoning,
        risk_check_result="PASS",
        opened_at=datetime.now(timezone.utc).isoformat(),
        broker="paper" if mode == "paper" else "polymarket-clob",
    )
    conn.execute(
        """INSERT INTO polymarket_bets
            (trade_id, market_id, market_question, market_category,
             estimated_probability, market_odds, edge_pct, kelly_bet_size,
             discovery_method, discovery_evidence)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            trade_id,
            bet["market_id"],
            bet.get("market_question"),
            bet.get("category"),
            bet.get("estimated_probability"),
            bet.get("market_price"),
            bet.get("edge_pct"),
            bet["sized_bet_usd"],
            bet.get("discovery_method") or "heuristic_paper",
            bet.get("discovery_evidence"),
        ),
    )
    conn.commit()
    return trade_id


def _telegram_alert(bet: dict, mode: str) -> None:
    icon = "🧪" if mode == "paper" else "💰"
    edge = bet.get("edge_pct")
    edge_str = f"{edge:+.1f}%" if isinstance(edge, (int, float)) else "n/a"
    factors = "\n".join(f"  • {f}" for f in (bet.get("key_factors") or [])[:3]) or "  (no factors)"
    msg = (
        f"{icon} <b>POLYMARKET BET ({mode.upper()})</b>\n"
        f"<i>{bet.get('market_question','?')[:160]}</i>\n\n"
        f"Side: <b>{bet['outcome'].upper()}</b> @ {bet['market_price']:.3f}\n"
        f"Est. P: {bet.get('estimated_probability', 0):.3f} · Edge: {edge_str}\n"
        f"Size: ${bet['sized_bet_usd']:.2f} · Confluence: {bet.get('confluence_score', '?')}\n"
        f"Category: {bet.get('category', '?')}\n\n"
        f"<b>Why:</b>\n{factors}"
    )
    notifier.notify("trade_executed", msg)


def _markdown_log(bet: dict, mode: str, trade_id: int) -> None:
    body = (
        f"- **Mode:** {mode}\n"
        f"- **Side:** {bet['outcome'].upper()} @ {bet['market_price']:.3f}\n"
        f"- **Estimated probability:** {bet.get('estimated_probability', 'n/a')}\n"
        f"- **Edge:** {bet.get('edge_pct', 'n/a')}%\n"
        f"- **Size:** ${bet['sized_bet_usd']:.2f}\n"
        f"- **Category:** {bet.get('category', 'n/a')}\n"
        f"- **Confluence:** {bet.get('confluence_score', 'n/a')}\n"
        f"- **Trade ID:** {trade_id}\n"
    )
    factors = bet.get("key_factors") or []
    if factors:
        body += "\n**Key factors:**\n" + "\n".join(f"- {f}" for f in factors[:5]) + "\n"
    cites = bet.get("citations") or []
    if cites:
        body += "\n**Sources:**\n" + "\n".join(f"- {c}" for c in cites[:5]) + "\n"
    title = f"Bet #{trade_id} · {bet['outcome'].upper()} · {bet.get('market_question','?')[:80]}"
    mm.append_section("POLYMARKET-LOG.md", title, body)


def _live_place_order(bet: dict) -> dict:
    """Phase 2 entry point. Today: returns a refusal stub."""
    if not pm_api.is_live_enabled():
        return {"ok": False, "reason": "PM_LIVE_TRADING != true"}
    token_ids = bet.get("clob_token_ids") or []
    if not token_ids:
        return {"ok": False, "reason": "no clob_token_ids on candidate"}
    # Phase 2 will resolve YES vs NO token from outcome and call CLOB.
    return pm_api.place_limit_order(token_ids[0], bet["outcome"], bet["market_price"], bet["sized_bet_usd"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="attempt live CLOB placement (requires PM_LIVE_TRADING=true)")
    parser.add_argument("--mode", choices=["paper", "live"], default=None, help="explicit mode override")
    args = parser.parse_args()

    today = _today_dir()
    # Prefer the brain-vetoed output when present. brain_pm_sanity_check writes
    # pm_brain_approved.json with only the bets that survived the Polymarket
    # Specialist veto (kills Aston Villa pattern). Fall back to the upstream
    # gate output when the brain check didn't run.
    brain_path = today / "pm_brain_approved.json"
    fallback_path = today / "pm_approved_bets.json"
    if brain_path.exists():
        approved_path = brain_path
        print("[execute_bet] using brain-approved bets (pm_brain_approved.json)")
    elif fallback_path.exists():
        approved_path = fallback_path
        print("[execute_bet] brain check missing — falling back to pm_approved_bets.json")
    else:
        print("[execute_bet] no approved bets file — skip")
        return 0
    payload = json.loads(approved_path.read_text())
    approved = payload.get("approved", [])
    if not approved:
        print("[execute_bet] zero approved bets — skip")
        return 0

    requested_mode = args.mode or ("live" if args.live else "paper")
    if requested_mode == "live" and not pm_api.is_live_enabled():
        print("[execute_bet] --live requested but PM_LIVE_TRADING != true; falling back to paper")
        mode = "paper"
    else:
        mode = requested_mode

    conn = dblib.get_connection()
    placed = []
    skipped = []

    try:
        for bet in approved:
            mid = bet.get("market_id")
            if not mid:
                continue
            if _already_persisted(conn, mid):
                skipped.append({"market_id": mid, "reason": "already persisted today"})
                continue

            live_result = None
            if mode == "live":
                live_result = _live_place_order(bet)
                if not live_result.get("ok"):
                    print(f"[execute_bet] live order failed for {mid}: {live_result.get('reason')}")
                    skipped.append({"market_id": mid, "reason": f"live failure: {live_result.get('reason')}"})
                    continue

            trade_id = _persist(conn, bet, mode)
            _telegram_alert(bet, mode)
            try:
                _markdown_log(bet, mode, trade_id)
            except Exception as e:
                print(f"[execute_bet] markdown log failed (non-fatal): {e}")
            placed.append({"trade_id": trade_id, "market_id": mid, "mode": mode, "live_result": live_result})
    finally:
        conn.close()

    out_path = today / "pm_bets_paper.json" if mode == "paper" else today / "pm_bets_live.json"
    out_path.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "placed_count": len(placed),
        "skipped_count": len(skipped),
        "placed": placed,
        "skipped": skipped,
    }, indent=2))
    print(f"[execute_bet] mode={mode} placed={len(placed)} skipped={len(skipped)} → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())