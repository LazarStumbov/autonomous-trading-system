"""Ingest manual Opus 4.7 trade reviews from reviews/completed/.

Counterpart to `trade_review_packet.py`. The user pastes a packet into the
Claude UI app, gets back an Opus 4.7 review, saves the response into
`reviews/completed/<same_filename>.md`, and this script:

  1. Parses each completed file for the trailing fenced ```json``` block
     containing the structured hypotheses + verdict.
  2. Validates each hypothesis against the parent strategy's safe_bounds —
     proposals outside bounds are dropped (logged, not crashed).
  3. Inserts surviving hypotheses into the `strategy_hypotheses` table at
     status='pending_backtest' so the same backtest → paper → live gate
     applies. Human review does NOT shortcut the gate.
  4. Marks the trade reviewed by appending `---HUMAN-OPUS-REVIEW---` plus a
     compact summary to `trades.reasoning`. This is what
     trade_review_packet.py uses to skip the trade on subsequent runs.
  5. Optionally moves the file to `reviews/archive/YYYY-MM/`.

Idempotent: each completed file is processed once. We track this by adding
the `---HUMAN-OPUS-REVIEW---` marker to the trade's reasoning and by
moving the file out of `completed/`. If neither archive nor marker is
present, we re-process — safe because hypothesis insertion is dedup-able by
(parent_strategy_id, rationale) inspection but for now we just trust the
markers.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from lib.db import get_connection, log_hypothesis

REVIEW_MARKER = "---HUMAN-OPUS-REVIEW---"
REVIEWS_DIR = Path(PROJECT_ROOT) / "reviews"
COMPLETED_DIR = REVIEWS_DIR / "completed"
ARCHIVE_DIR = REVIEWS_DIR / "archive"

# trade_<id>_<symbol>_<date>.md
PACKET_FILENAME_RE = re.compile(r"^trade_(\d+)_.*\.md$")
# Match the LAST fenced ```json ... ``` block in the file.
JSON_BLOCK_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


def _extract_trailing_json(text: str) -> dict | None:
    matches = JSON_BLOCK_RE.findall(text)
    if not matches:
        return None
    raw = matches[-1]
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[ingest_trade_review] JSON parse error: {e}")
        return None


def _trade_id_from_filename(name: str) -> int | None:
    m = PACKET_FILENAME_RE.match(name)
    return int(m.group(1)) if m else None


def _safe_bounds_for(conn, strategy_id: str) -> dict | None:
    row = conn.execute(
        "SELECT safe_bounds_json FROM strategy_registry WHERE id=?",
        (strategy_id,),
    ).fetchone()
    if not row or not row["safe_bounds_json"]:
        return None
    try:
        return json.loads(row["safe_bounds_json"])
    except json.JSONDecodeError:
        return None


def _validate_proposal(proposal: dict, bounds: dict | None) -> tuple[bool, str]:
    """Return (ok, reason). A proposal is rejected if any new_param is outside bounds
    or if hypothesis_type is not whitelisted."""
    htype = proposal.get("hypothesis_type")
    if htype not in {"param_tweak", "new_variant", "new_strategy"}:
        return False, f"bad hypothesis_type={htype!r}"
    new_params = proposal.get("new_params") or {}
    if not isinstance(new_params, dict):
        return False, "new_params must be an object"
    if htype == "param_tweak":
        if not bounds:
            return False, "no safe_bounds declared for parent strategy"
        for k, v in new_params.items():
            if k not in bounds:
                return False, f"param {k!r} not in safe_bounds"
            try:
                lo, hi = bounds[k]
            except (TypeError, ValueError):
                return False, f"safe_bounds[{k!r}] malformed"
            if not (lo <= v <= hi):
                return False, f"{k}={v} outside bounds [{lo}, {hi}]"
    return True, "ok"


def _mark_trade_reviewed(conn, trade_id: int, parsed: dict, n_hypotheses_logged: int) -> None:
    row = conn.execute("SELECT reasoning FROM trades WHERE id=?", (trade_id,)).fetchone()
    if not row:
        return
    existing = (row["reasoning"] or "").rstrip()
    block = {
        "verdict": parsed.get("verdict"),
        "summary": parsed.get("summary"),
        "hypotheses_logged": n_hypotheses_logged,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }
    appended = f"{existing}\n\n{REVIEW_MARKER}\n{json.dumps(block, indent=2)}\n"
    conn.execute("UPDATE trades SET reasoning=? WHERE id=?", (appended, trade_id))
    conn.commit()


def _archive_file(path: Path) -> Path:
    bucket = datetime.now(timezone.utc).strftime("%Y-%m")
    dest_dir = ARCHIVE_DIR / bucket
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / path.name
    shutil.move(str(path), str(dest))
    return dest


def process_file(conn, path: Path) -> dict:
    name = path.name
    trade_id = _trade_id_from_filename(name)
    result = {"file": name, "trade_id": trade_id, "logged": 0, "rejected": 0, "errors": []}

    if trade_id is None:
        result["errors"].append("filename does not match trade_<id>_*.md")
        return result

    text = path.read_text()
    parsed = _extract_trailing_json(text)
    if parsed is None:
        result["errors"].append("no trailing ```json``` block found")
        return result

    hypotheses = parsed.get("hypotheses") or []
    if not isinstance(hypotheses, list):
        result["errors"].append("hypotheses field is not a list")
        hypotheses = []

    logged = 0
    rejected = 0
    for h in hypotheses[:3]:  # cap at 3 per packet
        parent = h.get("parent_strategy_id")
        bounds = _safe_bounds_for(conn, parent) if parent else None
        ok, reason = _validate_proposal(h, bounds)
        if not ok:
            rejected += 1
            result["errors"].append(f"rejected: {reason}")
            continue
        try:
            log_hypothesis(
                conn,
                hypothesis_type=h["hypothesis_type"],
                parent_strategy_id=parent,
                rationale=h.get("rationale", "(human Opus review)"),
                proposed_params_json=json.dumps(h.get("new_params", {})),
                status="pending_backtest",
            )
            logged += 1
        except Exception as e:
            result["errors"].append(f"DB insert failed: {e}")
            rejected += 1

    _mark_trade_reviewed(conn, trade_id, parsed, logged)
    result["logged"] = logged
    result["rejected"] = rejected
    return result


def run(archive: bool = True) -> dict:
    if not COMPLETED_DIR.exists():
        print(f"[ingest_trade_review] no {COMPLETED_DIR} — nothing to ingest")
        return {"processed": 0}

    conn = get_connection()
    try:
        processed = 0
        total_logged = 0
        total_rejected = 0
        all_results = []
        for path in sorted(COMPLETED_DIR.glob("trade_*.md")):
            r = process_file(conn, path)
            all_results.append(r)
            processed += 1
            total_logged += r["logged"]
            total_rejected += r["rejected"]
            if archive and not r["errors"]:
                _archive_file(path)

        summary = {
            "processed": processed,
            "hypotheses_logged": total_logged,
            "hypotheses_rejected": total_rejected,
            "results": all_results,
        }
        print(f"[ingest_trade_review] {processed} files · {total_logged} logged · {total_rejected} rejected")
        return summary
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-archive", action="store_true", help="Leave processed files in completed/")
    args = ap.parse_args()
    run(archive=not args.no_archive)


if __name__ == "__main__":
    main()
