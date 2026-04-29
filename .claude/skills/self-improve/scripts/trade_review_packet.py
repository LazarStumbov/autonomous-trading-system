"""Emit per-trade review packets for manual paste into Claude UI (Opus subscription).

Why this exists:
  We want Opus 4.7 reasoning on every closed trade — the strongest model
  reviewing the work. Doing this via the API for hundreds of trades is
  expensive. The user prefers to use their Claude subscription instead.

Workflow:
  1. This script (run nightly inside the daily-report skill, or on-demand)
     finds every closed trade that has NOT yet been reviewed and emits a
     self-contained markdown packet to:
         reviews/pending/trade_<id>_<symbol>_<date>.md
  2. User opens the folder on their machine, pastes one packet at a time
     into the Claude UI app, gets a response from Opus.
  3. User saves the response (the WHOLE response, including the JSON tail
     described below) into:
         reviews/completed/trade_<id>_<symbol>_<date>.md
  4. `ingest_trade_review.py` parses every completed file, logs the
     proposals into the `strategy_hypotheses` table, and marks the trade
     reviewed (in `trades.reasoning` via a `---HUMAN-OPUS-REVIEW---` marker
     so the same trade isn't re-emitted).

Why a JSON tail in the response:
  Free-form Opus prose is great for humans. Machines need structure. Each
  packet asks Opus to end its response with a fenced ```json``` block whose
  shape matches the `strategy_hypotheses` row (parent_strategy_id, new_params
  within safe_bounds, rationale). `ingest_trade_review.py` extracts only
  hypotheses that fit those bounds — same gate as auto-generated proposals.

Idempotency:
  - Skips trades already reviewed (have `---HUMAN-OPUS-REVIEW---` in reasoning).
  - Skips trades that already have a packet emitted (file exists in
    reviews/pending/).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from lib.db import get_connection

REVIEW_MARKER = "---HUMAN-OPUS-REVIEW---"
REVIEWS_DIR = Path(PROJECT_ROOT) / "reviews"
PENDING_DIR = REVIEWS_DIR / "pending"
COMPLETED_DIR = REVIEWS_DIR / "completed"


def _packet_filename(trade: dict) -> str:
    closed = (trade.get("closed_at") or "").split("T")[0] or "unknown"
    sym = (trade.get("symbol") or "?").replace("/", "_").replace(":", "_")
    return f"trade_{trade['id']}_{sym}_{closed}.md"


def _safe_bounds_for(conn, strategy_id: str | None) -> dict | None:
    if not strategy_id:
        return None
    row = conn.execute(
        "SELECT safe_bounds_json FROM strategy_registry WHERE id=?",
        (strategy_id,),
    ).fetchone()
    if not row:
        return None
    try:
        return json.loads(row["safe_bounds_json"]) if row["safe_bounds_json"] else None
    except (json.JSONDecodeError, TypeError):
        return None


def _strategy_perf_snapshot(conn, strategy_id: str | None) -> dict | None:
    if not strategy_id:
        return None
    row = conn.execute(
        "SELECT * FROM strategy_performance WHERE strategy_id=?",
        (strategy_id,),
    ).fetchone()
    return dict(row) if row else None


def _build_packet(conn, trade: dict) -> str:
    sym = trade.get("symbol", "?")
    direction = (trade.get("direction") or "?").upper()
    pnl_pct = trade.get("pnl_pct")
    pnl_usd = trade.get("pnl_usd")
    verdict = "WIN" if (pnl_pct or 0) > 0 else "LOSS" if (pnl_pct or 0) < 0 else "SCRATCH"
    strategy_id = trade.get("strategy")
    perf = _strategy_perf_snapshot(conn, strategy_id)
    bounds = _safe_bounds_for(conn, strategy_id)
    reasoning = (trade.get("reasoning") or "").strip()

    body = f"""# Trade #{trade['id']} · {sym} {direction} · {verdict}

**Paste this entire file into Claude (Opus 4.7) for a post-mortem.**

---

## Trade facts

| Field | Value |
|---|---|
| Strategy | `{strategy_id or 'n/a'}` |
| Symbol | {sym} |
| Direction | {direction} |
| Entry price | {trade.get('entry_price', 'n/a')} |
| Exit price | {trade.get('exit_price', 'n/a')} |
| Stop loss | {trade.get('stop_loss', 'n/a')} |
| Take profit | {trade.get('take_profit', 'n/a')} |
| Leverage | {trade.get('leverage', 'n/a')}x |
| Confluence score | {trade.get('confluence_score', 'n/a')} |
| Opened | {trade.get('opened_at', 'n/a')} |
| Closed | {trade.get('closed_at', 'n/a')} |
| P&L (USD) | {pnl_usd} |
| P&L (%) | {pnl_pct} |

## Pre-trade reasoning + automated post-mortem

```
{reasoning if reasoning else '(no reasoning recorded)'}
```

## Strategy performance snapshot
"""
    if perf:
        body += "\n```json\n" + json.dumps(perf, indent=2, default=str) + "\n```\n"
    else:
        body += "\n_(no rolling perf snapshot for this strategy)_\n"

    body += "\n## Strategy safe_bounds (any proposed param tweaks MUST stay inside)\n"
    if bounds:
        body += "\n```json\n" + json.dumps(bounds, indent=2) + "\n```\n"
    else:
        body += "\n_(no safe_bounds declared)_\n"

    body += """
---

## Your task (Opus 4.7)

Read the trade above. Then produce:

1. **Verdict** — one paragraph: was this a good or bad trade *given the information available at entry*? (P&L is outcome, not process. A losing trade can be a good trade.)
2. **What worked** — bullets.
3. **What didn't** — bullets.
4. **Hypotheses** — concrete, testable changes that could improve future trades on this strategy. Stay strictly inside `safe_bounds`. Up to 3 hypotheses.
5. **Confluence audit** — was the confluence score appropriate for the outcome? (high-score loss = signal weighting may be off; low-score win = over-filtered.)

**End your response with a fenced JSON block in this EXACT shape so the system can ingest it:**

```json
{
  "verdict": "good_trade" | "bad_trade" | "neutral",
  "summary": "<one-sentence summary>",
  "hypotheses": [
    {
      "hypothesis_type": "param_tweak",
      "parent_strategy_id": "<strategy id from above>",
      "changed_param": "<param name from safe_bounds>",
      "new_params": { "<param name>": <value within bounds> },
      "rationale": "<why this should help>"
    }
  ]
}
```

If you have no hypotheses, return `"hypotheses": []`. Do not invent param names not in `safe_bounds`. Do not exceed 3 hypotheses.
"""
    return body


def _trade_already_packeted(trade: dict) -> bool:
    fname = _packet_filename(trade)
    return (PENDING_DIR / fname).exists() or (COMPLETED_DIR / fname).exists()


def _trade_already_reviewed(trade: dict) -> bool:
    return REVIEW_MARKER in (trade.get("reasoning") or "")


def run(limit: int | None = None) -> dict:
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    COMPLETED_DIR.mkdir(parents=True, exist_ok=True)

    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM trades WHERE status='closed' ORDER BY closed_at DESC"
        ).fetchall()
        emitted = 0
        skipped_reviewed = 0
        skipped_pending = 0
        for r in rows:
            trade = dict(r)
            if _trade_already_reviewed(trade):
                skipped_reviewed += 1
                continue
            if _trade_already_packeted(trade):
                skipped_pending += 1
                continue
            content = _build_packet(conn, trade)
            (PENDING_DIR / _packet_filename(trade)).write_text(content)
            emitted += 1
            if limit and emitted >= limit:
                break

        summary = {
            "emitted": emitted,
            "skipped_already_reviewed": skipped_reviewed,
            "skipped_already_pending": skipped_pending,
            "pending_dir": str(PENDING_DIR),
        }
        print(f"[trade_review_packet] {summary}")
        return summary
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="Cap packets emitted this run")
    args = ap.parse_args()
    run(limit=args.limit)


if __name__ == "__main__":
    main()
