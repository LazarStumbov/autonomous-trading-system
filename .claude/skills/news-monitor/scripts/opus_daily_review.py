"""Opus 4.7 daily market review — runs 08:00 UTC via Modal cron.

The user wants the strongest model producing the clearest analysis once per
day. This is the only hot-path LLM call in the system (every other LLM call
is weekly or post-trade).

Inputs gathered:
  * Last 24h of closed trades (summary)
  * Current open positions (from DB)
  * Today's research_log.json (Perplexity output)
  * Strategy performance snapshot (data/memory/strategy_memory.json)
  * Current market regime (data/memory/market_regime.json)
  * Last 3 days of news signals if present

Output:
  * data/signals/YYYY-MM-DD/opus_daily_brief.json  (structured — consumed
    by confluence_engine's macro_context feature)
  * memory/DAILY-BRIEF.md  (appended narrative)
  * Optional Telegram notification with the summary line

Cost control:
  * Single call, ~3-5K input tokens, ~1K output.
  * OPUS_MODEL env var overrides the model string (defaults to claude-opus-4-7).
  * If ANTHROPIC_API_KEY missing, writes a stub and exits 0 (cron-safe).

Idempotency: re-runs in the same day overwrite the JSON but append a new
markdown section (audit trail).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from lib.db import get_connection
from lib.markdown_memory import append_daily_brief


OPUS_MODEL = os.environ.get("OPUS_MODEL", "claude-opus-4-7")
MAX_INPUT_TOKENS = int(os.environ.get("OPUS_DAILY_MAX_INPUT_TOKENS", "8000"))
MAX_OUTPUT_TOKENS = int(os.environ.get("OPUS_DAILY_MAX_OUTPUT_TOKENS", "1500"))


SYSTEM_PROMPT = """You are the lead strategist for an aggressive crypto day-trading bot \
with a $100-$500 bankroll. Your role each morning is to produce a clear, \
tight, actionable market brief.

Output structure (markdown):

## Regime read
One tight paragraph: bull trend / bear trend / range / high vol / low vol, \
and why.

## What to watch today
3-5 numbered bullets with specific levels, events, or catalysts to monitor.

## Biases
- **Long bias:** assets / setups to favour
- **Short bias:** assets / setups to favour
- **Avoid:** assets or conditions where you'd sit out

## Risk posture
- Suggested exposure (% of max deployment)
- Confluence threshold adjustment (default 60 — should it be 55 more aggressive, or 70 more selective today?)
- Leverage cap suggestion (system max is 10x; you can only suggest lower)

## Headlines to monitor (next 24h)
Compact bulleted list of macro events with exact UTC times.

Keep the whole brief under 600 words. No fluff. Be decisive. Quote specific \
numbers from the inputs where possible. If inputs contradict each other, \
flag the conflict.

IMPORTANT: You cannot change hardcoded risk rules. The bot will enforce \
max 2% per trade, 6% daily DD cap, stop loss required, max 10x leverage \
regardless of what you write. Your "risk posture" is a soft recommendation \
that tightens — never loosens — these limits."""


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as e:
        print(f"[opus_daily_review] failed to load {path}: {e}")
        return None


def _recent_trades(conn, since_hours: int = 24) -> list[dict]:
    # NOTE: trades.asset is the symbol column (schema in lib/db.py); the table
    # has no `symbol` column. Keep aliases so the LLM still sees a `symbol` key.
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).isoformat()
    rows = conn.execute(
        "SELECT id, asset AS symbol, strategy, direction, entry_price, exit_price, "
        "pnl_pct, pnl_usd, confluence_score, closed_at "
        "FROM trades WHERE status='closed' AND closed_at >= ? "
        "ORDER BY closed_at DESC",
        (cutoff,),
    ).fetchall()
    return [dict(r) for r in rows]


def _open_positions(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT id, asset AS symbol, strategy, direction, entry_price, stop_loss, "
        "take_profit, leverage, opened_at "
        "FROM trades WHERE status='open' "
        "ORDER BY opened_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def _recent_news_signals(conn, since_hours: int = 72) -> list[dict]:
    """Try the signals table first; if empty, look at data/signals/YYYY-MM-DD/news_signals.json."""
    # signals schema: asset (not symbol), strength (not score), details_json
    # (not metadata), timestamp (not created_at). See lib/db.py SCHEMA.
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).isoformat()
    try:
        rows = conn.execute(
            "SELECT source, asset AS symbol, direction, strength AS score, "
            "details_json AS metadata, timestamp AS created_at "
            "FROM signals WHERE source='news' AND timestamp >= ? "
            "ORDER BY timestamp DESC LIMIT 30",
            (cutoff,),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _build_input_blob(today: str) -> dict:
    signals_dir = Path(PROJECT_ROOT) / "data" / "signals" / today
    memory_dir = Path(PROJECT_ROOT) / "data" / "memory"

    conn = get_connection()
    try:
        blob = {
            "date": today,
            "closed_trades_last_24h": _recent_trades(conn, 24),
            "open_positions": _open_positions(conn),
            "recent_news_signals_last_72h": _recent_news_signals(conn, 72),
        }
    finally:
        conn.close()

    research = _load_json(signals_dir / "research_log.json")
    if research:
        blob["perplexity_research"] = research.get("topics", {})

    regime = _load_json(memory_dir / "market_regime.json")
    if regime:
        blob["market_regime"] = regime

    strat_mem = _load_json(memory_dir / "strategy_memory.json")
    if strat_mem:
        # Keep only the summary fields to control prompt size.
        compact = {}
        for sid, s in (strat_mem.get("strategies") or {}).items():
            compact[sid] = {
                "mode": s.get("mode"),
                "total_trades": s.get("total_trades"),
                "win_rate": s.get("win_rate"),
                "last_20_win_rate": s.get("last_20_win_rate"),
                "sharpe_30d": s.get("sharpe_30d"),
                "consecutive_losses": s.get("consecutive_losses"),
            }
        blob["strategy_snapshot"] = compact

    return blob


def _stub_response(reason: str) -> str:
    return (
        f"## Regime read\n_(stub — {reason})_\n\n"
        "## What to watch today\n- _(Opus brief unavailable; hot-path rules still apply.)_\n\n"
        "## Biases\n- **Long bias:** n/a\n- **Short bias:** n/a\n- **Avoid:** n/a\n\n"
        "## Risk posture\nDefault: confluence >= 60, max 3x leverage, full risk rules enforced.\n"
    )


def _call_opus(input_blob: dict) -> tuple[str, dict]:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return _stub_response("ANTHROPIC_API_KEY not set"), {"model": None, "stubbed": True}

    # Cost gate (D6.6): allowlisted as opus_daily_brief, so this still runs
    # even when the monthly cap is hit — but cost is logged either way.
    try:
        from lib.anthropic_cost_tracker import should_allow, track_call  # type: ignore
        ok, reason = should_allow("opus_daily_brief")
        if not ok:
            return _stub_response(f"cost gate: {reason}"), {"model": None, "stubbed": True, "cost_gate": reason}
    except Exception:
        track_call = None  # type: ignore

    try:
        import anthropic  # type: ignore
    except ImportError:
        return _stub_response("anthropic SDK missing"), {"model": None, "stubbed": True}

    client = anthropic.Anthropic(api_key=api_key)
    user_content = (
        "Here is today's input data as JSON. Produce the daily brief per "
        "the system instructions.\n\n"
        f"```json\n{json.dumps(input_blob, default=str, indent=2)[:60000]}\n```"
    )

    try:
        # D6.2: prompt caching on the stable system prompt (~5min TTL).
        # System prompt + playbook context = stable; today's data = volatile.
        resp = client.messages.create(
            model=OPUS_MODEL,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_content}],
        )
    except Exception as e:
        print(f"[opus_daily_review] Opus call failed: {e}")
        return _stub_response(f"Opus call failed: {e}"), {"model": OPUS_MODEL, "stubbed": True, "error": str(e)}

    text = "".join(getattr(b, "text", "") for b in resp.content)
    usage = getattr(resp, "usage", None)
    in_tok = getattr(usage, "input_tokens", 0) if usage else 0
    cached_tok = getattr(usage, "cache_read_input_tokens", 0) if usage else 0
    out_tok = getattr(usage, "output_tokens", 0) if usage else 0

    if track_call is not None:
        try:
            usd = track_call(
                job="opus_daily_brief",
                model=OPUS_MODEL,
                input_tokens=in_tok - cached_tok,
                cached_input_tokens=cached_tok,
                output_tokens=out_tok,
            )
        except Exception as e:
            usd = None
            print(f"[opus_daily_review] cost track failed: {e}")
    else:
        usd = None

    meta = {
        "model": getattr(resp, "model", OPUS_MODEL),
        "stop_reason": getattr(resp, "stop_reason", None),
        "input_tokens": in_tok,
        "cached_input_tokens": cached_tok,
        "output_tokens": out_tok,
        "usd_cost": usd,
        "stubbed": False,
    }
    return text.strip(), meta


def run() -> dict:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir = Path(PROJECT_ROOT) / "data" / "signals" / today
    out_dir.mkdir(parents=True, exist_ok=True)

    blob = _build_input_blob(today)
    brief_text, meta = _call_opus(blob)

    record = {
        "date": today,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": meta.get("model"),
        "stubbed": meta.get("stubbed", False),
        "input_counts": {
            "closed_trades_24h": len(blob.get("closed_trades_last_24h", [])),
            "open_positions": len(blob.get("open_positions", [])),
            "news_signals_72h": len(blob.get("recent_news_signals_last_72h", [])),
            "research_topics": len(blob.get("perplexity_research", {})),
        },
        "usage": {
            "input_tokens": meta.get("input_tokens"),
            "output_tokens": meta.get("output_tokens"),
        },
        "brief": brief_text,
    }
    with open(out_dir / "opus_daily_brief.json", "w") as f:
        json.dump(record, f, indent=2)

    append_daily_brief(
        brief_text,
        model=meta.get("model") or "stub",
        inputs_summary=record["input_counts"],
        date=today,
    )

    # Best-effort telegram ping
    try:
        from lib.notifier import send_telegram
        first_para = brief_text.split("\n\n", 1)[0][:350]
        send_telegram(f"🧠 Opus daily brief ({today}):\n{first_para}")
    except Exception as e:
        print(f"[opus_daily_review] telegram skipped: {e}")

    print(f"[opus_daily_review] {meta.get('model')} brief written → {out_dir / 'opus_daily_brief.json'}")
    return record


def main() -> int:
    run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
