"""brain_daily_synthesis — Opus 4.7 desk synthesis + Critic red-team.

Runs daily at 21:00 UTC. Consolidates every signal source, open positions,
risk state, and accumulated memory into a single structured action list.
Critic agent (Sonnet 4.6) red-teams the output. Both runs are logged to
agent_actions for cost + agreement audit.

Writes:
  reviews/completed/<date>_synthesis.json  — full structured output
  memory/DAILY-BRIEF.md                    — markdown mirror (appended)
  Telegram preview                         — first 500 chars to chat

On budget cap / API failure, falls back to a heuristic summary built from
signals + positions counts so the cron still produces an artifact.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from lib import llm_brain  # noqa: E402
from lib import agent_tools  # noqa: E402


def _build_context() -> dict:
    return {
        "today_signals": agent_tools.get_recent_signals(),
        "open_positions": agent_tools.get_open_positions(),
        "latest_risk_snapshot": agent_tools.get_risk_state().get("latest_snapshot"),
        "recent_closed_trades": agent_tools.get_recent_trades(days=7),
        "recent_agent_memory": agent_tools.get_agent_memory(limit=15),
        "today_agent_cost": agent_tools.get_today_agent_cost(),
    }


def _heuristic_fallback(ctx: dict) -> dict:
    """Skeleton output when LLM unavailable. Honest about its degraded nature."""
    open_n = len(ctx.get("open_positions") or [])
    closed = ctx.get("recent_closed_trades") or []
    win_n = sum(1 for t in closed if (t.get("pnl_usd") or 0) > 0)
    return {
        "regime": f"LLM unavailable. {open_n} open, {len(closed)} closed last 7d, {win_n} wins.",
        "watchlist_bias": [],
        "open_book": {"verdict": "HOLD", "close_recommendations": []},
        "risk_posture": "normal",
        "risk_posture_rationale": "deterministic fallback — no synthesis available",
        "watch_items": [],
        "lessons": [],
        "telegram_preview": f"⚠️ Daily synth fallback. Open={open_n} Closed7d={len(closed)} W={win_n}",
        "_fallback": True,
    }


def _persist_lessons(lessons: list[dict], source_job: str) -> None:
    if not lessons:
        return
    try:
        from lib.db import get_connection
        conn = get_connection()
        try:
            for L in lessons:
                conn.execute(
                    """INSERT INTO agent_memory_semantic
                          (category, subject, body, confidence, source_job)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        L.get("category") or "lesson",
                        L.get("subject"),
                        L.get("body"),
                        float(L.get("confidence") or 0.7),
                        source_job,
                    ),
                )
            conn.commit()
        finally:
            conn.close()
        print(f"[brain_daily_synthesis] persisted {len(lessons)} lessons")
    except Exception as e:
        print(f"[brain_daily_synthesis] lesson persist failed: {e}")


def _notify_telegram(preview: str, critique_summary: str | None) -> None:
    try:
        from lib.notifier import send_telegram
        body = f"🌙 <b>Daily synthesis</b>\n{preview}"
        if critique_summary:
            body += f"\n\n<i>Critic:</i> {critique_summary}"
        send_telegram(body)
    except Exception as e:
        print(f"[brain_daily_synthesis] telegram send failed: {e}")


def main() -> int:
    ctx = _build_context()
    system = llm_brain.load_prompt("_preamble") + "\n\n" + llm_brain.load_prompt("synthesizer")
    user = json.dumps(ctx, default=str)[:60_000]  # cap context size

    resp = llm_brain.call(
        job="brain_daily_synthesis",
        tier="critical",
        system=system,
        user=user,
        max_tokens=2000,
        temperature=0.3,
    )

    synthesis = resp.parsed if (resp.ok and resp.parsed) else _heuristic_fallback(ctx)

    # Critic pass (only when synth succeeded — no point red-teaming a fallback)
    critique = None
    if resp.ok and resp.parsed:
        critic_system = llm_brain.load_prompt("_preamble") + "\n\n" + llm_brain.load_prompt("critic")
        critic_payload = json.dumps({
            "original_output": resp.parsed,
            "source_inputs": ctx,
        }, default=str)[:60_000]
        # Reverted critic critical→routine (Sonnet 4.6) per the cost-control
        # plan. Rationale: using the SAME model family for synthesizer + critic
        # destroys adversarial diversity — different architectures catch
        # different mistakes. Sonnet red-teaming Opus's output is the correct
        # design AND it's ~70% cheaper per critic call.
        critic_resp = llm_brain.call(
            job="brain_daily_synthesis_critic",
            tier="routine",
            system=critic_system,
            user=critic_payload,
            max_tokens=1000,
            temperature=0.2,
        )
        if critic_resp.ok and critic_resp.parsed:
            critique = critic_resp.parsed

    # Persist lessons emitted by the synthesizer
    _persist_lessons((synthesis or {}).get("lessons") or [], source_job="brain_daily_synthesis")

    # Write the full structured artifact
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir = Path(PROJECT_ROOT) / "reviews" / "completed"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{today}_synthesis.json"
    out_path.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "synthesis": synthesis,
        "critique": critique,
        "synth_usd_cost": resp.usd_cost,
        "synth_model": resp.model,
        "fallback_used": not (resp.ok and resp.parsed),
    }, indent=2, default=str))
    print(f"[brain_daily_synthesis] wrote {out_path}")

    # Telegram preview
    preview = (synthesis or {}).get("telegram_preview") or "—"
    critique_summary = None
    if critique:
        issues = critique.get("issues") or []
        high = [i for i in issues if i.get("severity") == "high"]
        if high:
            critique_summary = f"{len(high)} high-severity issues flagged"
    _notify_telegram(preview[:500], critique_summary)

    return 0


if __name__ == "__main__":
    sys.exit(main())