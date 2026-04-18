---
name: self-improve
description: Post-trade analysis and strategy optimization. Analyze closed trades for patterns, tune strategy parameters based on performance data, update trader/account scores, detect market regime changes.
allowed-tools: Bash, Read
---

# Self-Improve Skill

The system gets smarter over time. Every trade teaches something.

## When to Use
- Daily after performance-report generates
- Weekly during the full review cycle
- After a circuit breaker is triggered (diagnose why)

## Pipeline

### Step 1: Trade Post-Mortem
```bash
python3 .claude/skills/self-improve/scripts/trade_analyzer.py --period today
```
For each closed trade:
- Was entry timing optimal? (compare actual entry to ideal)
- Was stop loss appropriate? (stopped out then reversed = too tight)
- Was take profit optimal? (left money on table = too conservative)
- Did confluence score correlate with outcome?
- Which signals were most predictive?

### Step 2: Strategy Tuning
```bash
python3 .claude/skills/self-improve/scripts/strategy_tuner.py
```
Analyzes rolling performance by strategy:
- If a strategy has <40% win rate over 20+ trades, suggest parameter changes
- If stop losses are consistently too tight/wide, adjust ATR multiplier
- If certain assets perform better with specific strategies, update preferences
- Writes suggestions to `data/memory/strategy_memory.json`

### Step 3: Memory Update
```bash
python3 .claude/skills/self-improve/scripts/memory_updater.py
```
Updates rolling memory files:
- `data/memory/trader_memory.json` — Recalculate skill scores for followed accounts
- `data/memory/strategy_memory.json` — Update strategy performance by regime
- `data/memory/market_regime.json` — Detect current regime (trending, ranging, volatile)
- `data/memory/polymarket_memory.json` — Update PM account scores

## What Gets Tuned
- Strategy entry/exit parameters (within safe bounds)
- Followed account scores (promote/demote)
- Confluence signal weights (which signals are most predictive)
- Market regime classification

## What NEVER Gets Auto-Tuned
- Core risk parameters (max risk per trade, drawdown limits, stop loss requirement)
- These can only be changed manually by the user

## Learning Loop
```
Trade Closed → Post-Mortem → Pattern Detection → Parameter Suggestion → 
Human Review (weekly) → Apply Changes → Track Impact → Repeat
```
