---
name: signal-follow
description: Track positions from top Bybit leaderboard traders. Discover new top performers, monitor their positions, score signals by track record, and generate copy-trade recommendations.
allowed-tools: Bash, Read, WebSearch, WebFetch
---

# Signal Follow Skill

Follow the smart money — track what top traders are doing and generate copy-trade signals.

## When to Use
- Every hour during the market scan cycle
- Weekly for account discovery refresh
- When checking for new signals from followed accounts

## Pipeline

### Step 1: Discover Top Traders
```bash
python3 .claude/skills/signal-follow/scripts/discover_traders.py
```
Scrapes Bybit leaderboard. Scores by win rate, risk-adjusted returns, frequency, specialization, recency.
Updates `config/trader_accounts.json` and `data/memory/trader_memory.json`.

### Step 2: Track Positions
```bash
python3 .claude/skills/signal-follow/scripts/track_positions.py
```
Monitors followed accounts' open positions. Detects new entries, exits, size changes.
Logs to `signals` table in database.

### Step 3: Score Signals
```bash
python3 .claude/skills/signal-follow/scripts/signal_scorer.py
```
Scores each new signal by the account's skill score and alignment with our technical analysis.

### Step 4: Copy Trade Engine
```bash
python3 .claude/skills/signal-follow/scripts/copy_trade_engine.py
```
Generates copy-trade recommendations with sizing scaled by conviction.
Applies rules: max 3 copies, skip if moved >1%, require risk check.

## Key Config
- `config/trader_accounts.json` — Followed accounts and discovery rules
- `config/strategies/copy_trade.json` — Copy trade parameters
- `data/memory/trader_memory.json` — Rolling performance scores
