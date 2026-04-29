"""Generate weekly summary text + PDF, with optional Opus 4.7 narrative.

The 7-day numeric summary (P&L, Sharpe, win rate, top strategies) is always
written deterministically. On top of that, when ANTHROPIC_API_KEY is set, we
ask Opus 4.7 to write a structured narrative review:

  - What worked
  - What didn't work
  - Key lessons
  - Adjustments for next week
  - Overall letter grade A–F

The grade is extracted from a fenced JSON tail (same pattern as the manual
trade-review packets) so the value can be logged into system_state for
trend tracking.

Idempotency: re-running the script the same day overwrites the txt and PDF
but APPENDS a new section to memory/WEEKLY-REVIEW.md (audit trail).
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from lib.db import get_connection, set_system_state
from lib.markdown_memory import append_weekly_review

OPUS_MODEL = os.environ.get("OPUS_MODEL", "claude-opus-4-7")
WEEKLY_OUTPUT_TOKENS = int(os.environ.get("OPUS_WEEKLY_MAX_OUTPUT_TOKENS", "2000"))
JSON_TAIL_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


SYSTEM_PROMPT = """You are the head of strategy reviewing this week's trades \
for an aggressive crypto day-trading bot ($100-500 bankroll). You are tough \
but fair: you reward good process even on losing trades, and you punish bad \
process even on winning trades.

Output structure (markdown):

## What worked
3-5 bullets, specific. Reference strategies and trades by name when possible.

## What didn't work
3-5 bullets. Be direct.

## Key lessons
3 bullets. The crystallized takeaways.

## Adjustments for next week
3 bullets. Concrete, testable. These should be the kind of changes the \
hypothesis_generator could pick up. Stay within strategy safe_bounds; do NOT \
suggest changes to hardcoded risk rules (max 2% per trade, 6% daily DD, etc.) \
— those are off-limits.

## Grade
One paragraph justifying the letter grade. Be honest:
  A = exceptional week (>5% portfolio gain, clean process, no rule violations)
  B = solid week (positive PnL or flat with good process)
  C = mediocre week (small loss, some process issues)
  D = bad week (significant loss or repeated process violations)
  F = blow-up week (>5% drawdown, circuit breaker tripped, risk-rule violation)

End with a fenced JSON block containing the grade and one-line summary:

```json
{
  "grade": "A" | "A-" | "B+" | "B" | "B-" | "C+" | "C" | "C-" | "D+" | "D" | "D-" | "F",
  "summary": "<one-sentence summary>"
}
```

Total length under 700 words."""


def _build_inputs(today: str) -> tuple[dict, list[dict], list[dict]]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    conn = get_connection()
    try:
        trades = [dict(r) for r in conn.execute(
            "SELECT * FROM trades WHERE status='closed' AND closed_at >= ?", (cutoff,)
        ).fetchall()]
        strategies = [dict(r) for r in conn.execute("SELECT * FROM strategy_registry").fetchall()]
    finally:
        conn.close()

    reports_dir = Path(PROJECT_ROOT) / "data" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = reports_dir / f"metrics_weekly_{today}.json"
    metrics = {}
    if metrics_path.exists():
        with open(metrics_path) as f:
            metrics = json.load(f)
    return metrics, trades, strategies


def _numeric_summary(metrics: dict, trades: list[dict], strategies: list[dict]) -> tuple[str, dict]:
    overall = metrics.get("overall") or {}
    total = overall.get("n", len(trades))
    wr = overall.get("win_rate", 0) * 100
    pnl = overall.get("total_pnl", sum((t.get("pnl_usd") or 0) for t in trades))
    sharpe = overall.get("sharpe", 0)
    sortino = overall.get("sortino", 0)
    dd = overall.get("max_dd_pct", 0)

    by_mode: dict[str, int] = {}
    for s in strategies:
        by_mode[s["mode"]] = by_mode.get(s["mode"], 0) + 1

    lines = [
        f"7-day trades: {total}  WR: {wr:.0f}%  P&L: ${pnl:.2f}",
        f"Sharpe: {sharpe:.2f}  Sortino: {sortino:.2f}  Max DD: {dd:.1f}%",
        f"Strategies by mode: " + ", ".join(f"{m}:{c}" for m, c in sorted(by_mode.items())),
    ]
    by_strat = metrics.get("by_strategy") or {}
    if by_strat:
        top = sorted(by_strat.items(), key=lambda kv: -kv[1].get("total_pnl", 0))[:5]
        lines.append("")
        lines.append("Top strategies (by P&L):")
        for sid, m in top:
            lines.append(f"  {sid}: pnl=${m['total_pnl']:.2f} n={m['n']} wr={m['win_rate']*100:.0f}%")

    metrics_dict = {
        "trades": total,
        "win_rate_pct": round(wr, 1),
        "total_pnl_usd": round(pnl, 2),
        "sharpe": round(sharpe, 2),
        "sortino": round(sortino, 2),
        "max_dd_pct": round(dd, 1),
    }
    return "\n".join(lines), metrics_dict


def _opus_narrative(metrics: dict, trades: list[dict], by_strat: dict) -> tuple[str, dict]:
    """Returns (markdown_text, parsed_json_tail)."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return "", {}
    try:
        import anthropic  # type: ignore
    except ImportError:
        return "", {}

    # Compact trades to keep prompt small.
    compact_trades = [
        {
            "id": t.get("id"),
            "asset": t.get("asset"),
            "strategy": t.get("strategy"),
            "direction": t.get("direction"),
            "pnl_usd": t.get("pnl_usd"),
            "pnl_pct": t.get("pnl_pct"),
            "confluence": t.get("confluence_score"),
            "closed_at": t.get("closed_at"),
        }
        for t in trades
    ]

    user_block = (
        "Here is the data for the past 7 days. Produce the weekly review.\n\n"
        f"```json\n{json.dumps({'overall': metrics.get('overall', {}), 'by_strategy': by_strat, 'trades': compact_trades}, default=str, indent=2)[:50000]}\n```"
    )

    client = anthropic.Anthropic(api_key=api_key)
    try:
        resp = client.messages.create(
            model=OPUS_MODEL,
            max_tokens=WEEKLY_OUTPUT_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_block}],
        )
    except Exception as e:
        print(f"[weekly] Opus narrative call failed: {e}")
        return "", {}

    text = "".join(getattr(b, "text", "") for b in resp.content).strip()

    parsed = {}
    matches = JSON_TAIL_RE.findall(text)
    if matches:
        try:
            parsed = json.loads(matches[-1])
        except json.JSONDecodeError as e:
            print(f"[weekly] failed to parse Opus JSON tail: {e}")

    return text, parsed


def _section_text(narrative_md: str, section: str) -> list[str]:
    """Return bullet lines under a "## <section>" markdown heading."""
    if not narrative_md:
        return []
    pattern = re.compile(
        rf"##\s+{re.escape(section)}\s*\n(.*?)(?=\n##\s+|\Z)",
        re.DOTALL | re.IGNORECASE,
    )
    m = pattern.search(narrative_md)
    if not m:
        return []
    body = m.group(1).strip()
    bullets = [
        line.lstrip("-* ").strip()
        for line in body.splitlines()
        if line.strip().startswith(("-", "*"))
    ]
    return [b for b in bullets if b]


def main():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    metrics, trades, strategies = _build_inputs(today)

    summary_text, metrics_dict = _numeric_summary(metrics, trades, strategies)

    # Opus narrative + grade (best-effort)
    narrative_md, parsed = _opus_narrative(metrics, trades, metrics.get("by_strategy") or {})
    grade = parsed.get("grade", "n/a")
    one_line = parsed.get("summary", "")

    reports_dir = Path(PROJECT_ROOT) / "data" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    full_text = summary_text
    if narrative_md:
        full_text += "\n\n---\n\n" + narrative_md
    if grade and grade != "n/a":
        full_text += f"\n\nGRADE: {grade}\n"

    with open(reports_dir / "latest_weekly_summary.txt", "w") as f:
        f.write(full_text)

    # Markdown memory mirror
    structured = {
        "worked": _section_text(narrative_md, "What worked"),
        "didnt_work": _section_text(narrative_md, "What didn't work"),
        "key_lessons": _section_text(narrative_md, "Key lessons"),
        "adjustments": _section_text(narrative_md, "Adjustments for next week"),
        "overall": one_line,
    }
    try:
        append_weekly_review(structured, grade=grade or "n/a", metrics=metrics_dict, date=today)
    except Exception as e:
        print(f"[weekly] markdown append skipped: {e}")

    # Persist the latest grade in system_state so dashboards / circuit-breakers
    # can react to grade trends.
    if grade and grade != "n/a":
        try:
            conn = get_connection()
            try:
                set_system_state(conn, "last_weekly_grade", grade)
                set_system_state(conn, "last_weekly_grade_at", today)
            finally:
                conn.close()
        except Exception as e:
            print(f"[weekly] failed to persist grade: {e}")

    # PDF (best-effort, unchanged)
    try:
        from lib.pdf_generator import generate_weekly_pdf  # type: ignore
        pdf_path = reports_dir / f"weekly_{today}.pdf"
        generate_weekly_pdf(str(pdf_path), today, metrics.get("overall") or {}, metrics.get("by_strategy") or {}, strategies)
    except Exception as e:
        print(f"[weekly] PDF skipped ({e})")

    print(full_text)


if __name__ == "__main__":
    main()
