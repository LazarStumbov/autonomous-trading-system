---
name: polymarket-bet
description: Polymarket prediction market operations. Scan for mispriced markets, estimate true probabilities, track top accounts, calculate Kelly-optimal bet sizes, and execute bets via CLOB API.
allowed-tools: Bash, Read, WebSearch, WebFetch
---

# Polymarket Bet Skill

Find and exploit mispricings in prediction markets.

## When to Use
- Every 4 hours during the Polymarket scan cycle
- When news creates a sudden probability shift
- Via `/polymarket-scan` for manual scan

## Pipeline

### Step 1: Market Scan
```bash
python3 .claude/skills/polymarket-bet/scripts/polymarket_api.py --action scan
```
Pulls active markets from Polymarket API. Filters by:
- Minimum liquidity ($10K+)
- Categories of interest
- Time to resolution (skip markets resolving in <24h unless high edge)

### Step 2: Odds Analysis
```bash
python3 .claude/skills/polymarket-bet/scripts/odds_analyzer.py --market-id "0x..."
```
For each candidate market:
- Deep research the question (news, polls, expert analysis)
- Establish base rates from historical analogues
- Estimate true probability with confidence range

### Step 3: Edge Calculation
```bash
python3 .claude/skills/polymarket-bet/scripts/edge_calculator.py --estimated-prob 0.48 --market-odds 0.35
```
- Edge = estimated_probability - market_odds
- Minimum edge required: 5%
- Quarter-Kelly bet sizing via `lib/kelly.py`
- Cap at 5% of bankroll per bet

### Step 4: Account Tracking
```bash
python3 .claude/skills/polymarket-bet/scripts/account_tracker.py
```
Monitors top PM accounts for new positions:
- Skill score: win_rate * ln(1 + total_positions)
- Detect whale entries (large positions in new markets)
- Generate signals when high-skill accounts enter

### Step 5: Bet Execution
```bash
python3 .claude/skills/polymarket-bet/scripts/bet_executor.py --market-id "0x..." --direction yes --amount 12.50
```
Places bet via Polymarket CLOB API:
- Requires wallet with USDC
- Uses limit orders for better fills
- Logs to database

## Risk Limits (from config/risk_params.json)
- Max 5% of bankroll per bet
- Min 5% edge required
- Quarter-Kelly sizing (0.25x)
- Max 15% exposure per category
- Max 40% total PM exposure
- Min $10K market liquidity
- Max 3 correlated bets
