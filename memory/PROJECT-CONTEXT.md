# Project Context

> The "why" doc. Updated when the strategic picture changes, not on every trade.

## Mission

Build an autonomous, hedge-fund-caliber trading system operating on a modest
$100–$500 bankroll. The system must:

- trade aggressively but never violate hardcoded risk rules,
- learn from every closed trade,
- survive 24/7 without human intervention (Modal cron),
- but remain fully auditable by a human reading `memory/*.md` + git history.

## Architecture at a glance

- **Skills** (`.claude/skills/<name>/`) — intent + bundled scripts. Ten skills total.
- **Shared libraries** (`lib/`) — DB, risk engine, strategy engine, notifier, etc.
- **Strategy library** (`lib/strategy_library/`) — pluggable `Strategy` subclasses
  sourced from freqtrade, jesse, QuantConnect Lean, Stefan Jansen, TradingView.
- **SQLite source of truth** (`data/db/trading.db`) — trades, signals, strategy
  performance, backtests, hypotheses.
- **Markdown memory mirror** (`memory/*.md`) — human-readable audit trail of
  everything that matters, committed to git.
- **Cloud execution** (`modal/trading_webhook.py`) — cron jobs + webhooks.

## Model usage

- **Hot path** (15m/1h/4h scans): pure Python. No LLM calls. Deterministic.
- **Daily market brief**: Opus 4.7 via Anthropic API (user pays).
- **Weekly hypothesis generator + weekly review narrative**: Opus 4.7.
- **Per-trade review**: packet emitted to `reviews/pending/`, user pastes
  into Claude UI (Opus subscription), response ingested from `reviews/completed/`.
- **Subagents** (market-analyst, risk-manager, etc.): Sonnet 4.5 — cost-efficient.

## Research

`news-monitor` calls Perplexity (`lib/perplexity.py`) for citation-backed
research. Output lands in `memory/RESEARCH-LOG.md` and
`data/signals/<date>/research_log.json`.

## Multi-asset roadmap

Core implementation is crypto (Bybit). Broker abstraction in `lib/brokers/`
lets us plug in Alpaca (stocks), IBKR (bonds/futures), and CFD venues later.
Non-crypto adapters start as `mode=disabled` stubs until Stage 4 ships.

## What this doc is NOT

Not a TODO list. Not a daily journal. Those live in `TRADE-LOG.md`,
`DAILY-BRIEF.md`, and `WEEKLY-REVIEW.md`.
