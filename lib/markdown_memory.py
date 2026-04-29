"""Markdown-memory mirror for the trading system.

The source of truth for scripts is SQLite (`data/db/trading.db`). But SQLite is
opaque: you can't read it in a browser, you can't diff it in git, and Claude
(including when pasted into the UI for manual trade review) reads markdown far
more naturally than it reads DB rows.

So every important event also gets appended to a dated section of a markdown
file under `memory/`. Those files are committed to git, giving us:
  * A human-readable audit trail
  * A format the Opus 4.7 UI can read when pasted as context
  * Diffable history ("what did we believe on 2026-04-15?")

This module is the ONLY write path into `memory/*.md`. All callers go through
the helpers below so the format stays consistent.

File conventions:
  memory/
    TRADING-STRATEGY.md   — static doctrine (risk rules, strategy doctrine)
    PROJECT-CONTEXT.md    — evolving "what is this project" doc
    TRADE-LOG.md          — every closed trade, append-only
    RESEARCH-LOG.md       — daily Perplexity research dumps
    WEEKLY-REVIEW.md      — Sunday retrospectives w/ letter grade
    DAILY-BRIEF.md        — daily Opus 4.7 market review

All writes are append-only. Idempotency is NOT guaranteed at this layer —
callers that run on cron should gate themselves on "already-written-today".
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MEMORY_DIR = Path(PROJECT_ROOT) / "memory"


# ── Primitives ───────────────────────────────────────────────────────────────
def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _ensure_file(path: Path, header: str) -> None:
    """Create file with header if it doesn't exist. No-op otherwise."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(header.rstrip() + "\n")


def append_section(
    file_name: str,
    heading: str,
    body: str,
    *,
    level: int = 2,
    timestamp: Optional[str] = None,
) -> Path:
    """Append a markdown section to a file under memory/.

    Args:
        file_name: bare filename, e.g. "TRADE-LOG.md"
        heading: section heading (no leading # — we add them)
        body: the markdown body
        level: heading level (default 2 → "## heading")
        timestamp: override timestamp in the heading. Defaults to now.

    Returns the path written to.
    """
    path = MEMORY_DIR / file_name
    _ensure_file(path, f"# {file_name.replace('.md','').replace('-', ' ').title()}\n")
    ts = timestamp or _now_iso()
    hashes = "#" * level
    block = f"\n{hashes} {heading}  ·  {ts}\n\n{body.rstrip()}\n"
    with open(path, "a") as f:
        f.write(block)
    return path


# ── Trade log ────────────────────────────────────────────────────────────────
def append_trade_log_entry(trade: dict) -> Path:
    """Append a closed trade to TRADE-LOG.md in a consistent format.

    Expected keys (missing ones are rendered as "n/a"):
      id, symbol, direction, strategy, entry_price, exit_price, stop_loss,
      take_profit, leverage, pnl_usd, pnl_pct, confluence_score,
      opened_at, closed_at, reasoning.
    """
    sym = trade.get("symbol", "?")
    direction = trade.get("direction", "?")
    pnl_pct = trade.get("pnl_pct")
    pnl_usd = trade.get("pnl_usd")
    verdict = "WIN" if (pnl_pct or 0) > 0 else "LOSS" if (pnl_pct or 0) < 0 else "SCRATCH"
    heading = f"Trade #{trade.get('id','?')} · {sym} {direction.upper()} · {verdict}"

    def fmt(v: Any, suffix: str = "") -> str:
        return f"{v}{suffix}" if v is not None else "n/a"

    body = (
        f"- **Strategy:** {trade.get('strategy', 'n/a')}\n"
        f"- **Entry:** {fmt(trade.get('entry_price'))}  →  **Exit:** {fmt(trade.get('exit_price'))}\n"
        f"- **SL / TP:** {fmt(trade.get('stop_loss'))} / {fmt(trade.get('take_profit'))}\n"
        f"- **Leverage:** {fmt(trade.get('leverage'), 'x')}\n"
        f"- **P&L:** {fmt(pnl_usd, ' USD')}  ·  {fmt(pnl_pct, '%')}\n"
        f"- **Confluence score:** {fmt(trade.get('confluence_score'))}\n"
        f"- **Opened:** {fmt(trade.get('opened_at'))}  ·  **Closed:** {fmt(trade.get('closed_at'))}\n"
    )
    reasoning = trade.get("reasoning")
    if reasoning:
        truncated = reasoning if len(reasoning) < 2000 else reasoning[:2000] + "\n…(truncated)"
        body += f"\n**Reasoning / post-mortem:**\n\n```\n{truncated}\n```\n"
    return append_section("TRADE-LOG.md", heading, body)


# ── EOD snapshot ─────────────────────────────────────────────────────────────
def append_eod_snapshot(portfolio_state: dict, date: Optional[str] = None) -> Path:
    """Daily EOD portfolio snapshot. One section per day."""
    d = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    equity = portfolio_state.get("equity_usd")
    cash = portfolio_state.get("cash_usd")
    open_positions = portfolio_state.get("open_positions", [])
    daily_pnl_pct = portfolio_state.get("daily_pnl_pct")
    weekly_pnl_pct = portfolio_state.get("weekly_pnl_pct")

    body = (
        f"- **Equity:** {equity if equity is not None else 'n/a'} USD\n"
        f"- **Cash available:** {cash if cash is not None else 'n/a'} USD\n"
        f"- **Daily P&L:** {daily_pnl_pct if daily_pnl_pct is not None else 'n/a'}%\n"
        f"- **Weekly P&L:** {weekly_pnl_pct if weekly_pnl_pct is not None else 'n/a'}%\n"
        f"- **Open positions:** {len(open_positions)}\n"
    )
    if open_positions:
        body += "\n| Symbol | Dir | Entry | Qty | Unrealized P&L |\n|---|---|---|---|---|\n"
        for p in open_positions:
            body += (
                f"| {p.get('symbol','?')} | {p.get('direction','?')} | "
                f"{p.get('entry_price','?')} | {p.get('qty','?')} | "
                f"{p.get('unrealized_pnl_pct','?')}% |\n"
            )
    return append_section("DAILY-BRIEF.md", f"EOD snapshot · {d}", body, level=3)


# ── Daily market review (Opus 4.7 API output) ────────────────────────────────
def append_daily_brief(
    narrative: str,
    model: str,
    inputs_summary: Optional[dict] = None,
    date: Optional[str] = None,
) -> Path:
    """Append the Opus 4.7 daily market review to DAILY-BRIEF.md."""
    d = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    header = f"Daily market brief · {d}"
    body = f"*Model: `{model}`*\n\n{narrative.rstrip()}\n"
    if inputs_summary:
        body += "\n---\n\n**Inputs summary:**\n"
        for k, v in inputs_summary.items():
            body += f"- {k}: {v}\n"
    return append_section("DAILY-BRIEF.md", header, body)


# ── Research log (Perplexity + any other sources) ────────────────────────────
def append_research_log(content_blocks: dict, date: Optional[str] = None) -> Path:
    """Append a dated research log.

    content_blocks: ordered dict { "topic title": "markdown body" }.
    Example topics: "BTC dominance & flow", "Funding rates", "Macro catalysts today",
                    "Altcoin breadth", "Dominant narrative".
    """
    d = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    parts = []
    for topic, text in content_blocks.items():
        parts.append(f"### {topic}\n\n{text.rstrip()}\n")
    body = "\n".join(parts) if parts else "_(no research this run)_"
    return append_section("RESEARCH-LOG.md", f"Research · {d}", body)


# ── Weekly review ────────────────────────────────────────────────────────────
def append_weekly_review(
    narrative: dict,
    grade: str,
    metrics: Optional[dict] = None,
    date: Optional[str] = None,
) -> Path:
    """Friday/Sunday weekly recap.

    narrative keys (all optional, rendered if present):
      worked         — list[str]
      didnt_work     — list[str]
      key_lessons    — list[str]
      adjustments    — list[str]
      overall        — str  (paragraph summary)

    grade: "A" / "B" / ... / "F" (or "A-", "B+" etc.)
    """
    d = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    header = f"Weekly review · {d}  ·  Grade: **{grade}**"

    def _bullets(title: str, items: Optional[list]) -> str:
        if not items:
            return ""
        return f"**{title}:**\n" + "\n".join(f"- {x}" for x in items) + "\n\n"

    body = ""
    if metrics:
        body += "**Metrics:**\n"
        for k, v in metrics.items():
            body += f"- {k}: {v}\n"
        body += "\n"
    body += _bullets("What worked", narrative.get("worked"))
    body += _bullets("What didn't work", narrative.get("didnt_work"))
    body += _bullets("Key lessons", narrative.get("key_lessons"))
    body += _bullets("Adjustments for next week", narrative.get("adjustments"))
    if narrative.get("overall"):
        body += f"**Overall:** {narrative['overall']}\n"
    return append_section("WEEKLY-REVIEW.md", header, body)


# ── Generic "what happened" helper (used by various skills) ──────────────────
def append_event(file_name: str, title: str, body: str) -> Path:
    """Escape hatch for one-off events. Prefer the typed helpers above."""
    return append_section(file_name, title, body, level=3)


# ── Self-test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    append_event(
        "DAILY-BRIEF.md",
        "Self-test",
        "markdown_memory.py loaded successfully.",
    )
    print(f"[markdown_memory] self-test OK → {MEMORY_DIR}")
