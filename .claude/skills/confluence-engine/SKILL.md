---
name: confluence-engine
description: Multi-signal convergence detection. Combines technical, sentiment, trader, news, and volume signals to score trade setups. Only setups scoring >= 60 proceed to risk check.
allowed-tools: Bash, Read
---

# Confluence Engine Skill

The confluence engine is the quality filter. It ensures we only trade when multiple independent signals agree.

## When to Use
- After market-scan and signal-follow produce new signals
- After news-monitor detects a high-urgency event
- Before any trade reaches the risk-check stage

## Pipeline

### Step 1: Confluence Detection
```bash
python3 .claude/skills/confluence-engine/scripts/confluence_detector.py
```
Reads latest signals from all sources (technicals, news, trader positions, sentiment, volume).
Groups by asset and direction.
Counts independent signal types that agree.

### Step 2: Score Setup
```bash
python3 .claude/skills/confluence-engine/scripts/score_setup.py
```
Calculates confidence score (0-100) using weighted signals from `config/watchlist.json`.
- 3 signals aligning = base 60 score
- Each additional signal adds weighted points
- News catalyst signals get 1.5x weight
- Trader accumulation gets 1.2x weight

### Step 3: Alert Generation
```bash
python3 .claude/skills/confluence-engine/scripts/alert_generator.py
```
Generates actionable alerts for setups scoring >= 60.
Includes full context: which signals, entry/SL/TP, suggested leverage.

## Scoring Logic
```
base_score = 40 + (num_signals * 10)
weighted_score = sum(signal_weight * signal_strength for each signal)
final_score = min(100, (base_score + weighted_score) / 2)
```

## Signal Types (7 total)
1. **technical_breakout** (weight: 1.0) — Price breaks key S/R with volume
2. **sentiment_shift** (weight: 0.8) — News sentiment changes direction
3. **trader_accumulation** (weight: 1.2) — Top traders loading same asset
4. **polymarket_whale_entry** (weight: 0.7) — PM whales betting on related event
5. **news_catalyst** (weight: 1.5) — Breaking news with directional impact
6. **volume_anomaly** (weight: 0.9) — Unusual volume spike
7. **cross_asset_correlation** (weight: 0.6) — Correlated assets moving in sync

## Thresholds
- **< 60**: Log signal, no action
- **60-79**: Standard trade — default leverage, standard sizing
- **>= 80**: High conviction — eligible for higher leverage (up to max)
