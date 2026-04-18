---
name: market-scan
description: Scan watchlist for trade setups using technical analysis. Pull prices, run RSI/MACD/BB/ATR/volume, detect breakouts and reversals, screen across multiple timeframes.
allowed-tools: Bash, Read, WebFetch
---

# Market Scan Skill

Scan the crypto watchlist for actionable trade setups.

## When to Use
- Every hour during the market scan cycle
- When manually requested via `/scan-markets`
- When news monitor detects an event affecting a watched asset

## Pipeline

### Step 1: Fetch Market Data
```bash
python3 .claude/skills/market-scan/scripts/fetch_market_data.py
```
Pulls OHLCV data for all assets in `config/watchlist.json` from Bybit via ccxt.
Outputs: `data/signals/YYYY-MM-DD/market_data.json`

### Step 2: Technical Analysis
```bash
python3 .claude/skills/market-scan/scripts/technical_analysis.py
```
Runs indicators (RSI, MACD, Bollinger Bands, ATR, EMA 20/50/200, volume profile) across primary and confirmation timeframes.
Outputs: `data/signals/YYYY-MM-DD/technicals.json`

### Step 3: Support & Resistance
```bash
python3 .claude/skills/market-scan/scripts/support_resistance.py
```
Identifies key S/R levels from price action on daily timeframe.
Outputs: Appends to technicals.json

### Step 4: Multi-Timeframe Screener
```bash
python3 .claude/skills/market-scan/scripts/screener.py
```
Screens for setups matching strategy configs (momentum breakout, mean reversion).
Outputs: Ranked list of setups with confidence scores.

## Output
JSON array of trade setups, each with:
- Asset, direction, strategy, confidence score (0-100)
- Entry price, stop loss, take profit
- Suggested leverage
- List of supporting signals
- Reasoning

## Key Config
- `config/watchlist.json` — Assets, timeframes, indicator thresholds
- `config/strategies/*.json` — Strategy-specific entry/exit conditions
