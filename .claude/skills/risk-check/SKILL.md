---
name: risk-check
description: Pre-trade risk validation gate. MUST PASS before any trade execution. Checks position sizing, exposure, drawdown, leverage, correlation, stop loss, and risk-reward. Has absolute veto power.
allowed-tools: Bash, Read
---

# Risk Check Skill

The risk check is a mandatory gate. NO trade bypasses it. EVER.

## When to Use
- Before EVERY trade execution (market or Polymarket)
- When checking current portfolio risk exposure
- Via `/check-risk` for manual risk snapshot

## Pipeline

### Step 1: Position Sizing
```bash
python3 .claude/skills/risk-check/scripts/position_sizer.py --capital 500 --entry 65000 --stop 63500 --risk-pct 2
```
Calculates exact position size based on capital, entry, stop loss, and max risk %.

### Step 2: Portfolio Exposure
```bash
python3 .claude/skills/risk-check/scripts/portfolio_exposure.py
```
Checks current open positions against max exposure limit (30%).

### Step 3: Drawdown Monitor
```bash
python3 .claude/skills/risk-check/scripts/drawdown_monitor.py
```
Checks daily and weekly P&L against drawdown limits (6% daily, 15% weekly).

### Step 4: Risk Gate (Final Verdict)
```bash
python3 .claude/skills/risk-check/scripts/risk_gate.py --trade-json '{"asset":"BTC/USDT:USDT","direction":"long","entry":65000,"sl":63500,"tp":68000,"leverage":3,"confluence":75}'
```
Runs ALL checks and returns consolidated PASS/FAIL verdict.

Alternatively, use the Python API directly:
```python
from lib.risk_engine import check_trade
result = check_trade(capital=500, asset="BTC/USDT:USDT", direction="long",
                     entry_price=65000, stop_loss_price=63500,
                     take_profit_price=68000, requested_leverage=3,
                     confluence_score=75)
```

## Rules (from config/risk_params.json)
1. Max 2% risk per trade
2. Max 6% daily drawdown (halt all trading)
3. Max 15% weekly drawdown (require manual resume)
4. Stop loss REQUIRED on every trade
5. Min 2:1 risk-reward ratio
6. Leverage: default 3x, max 10x only at confluence >= 80
7. Max 30% capital deployed
8. Max 3 correlated positions
9. Circuit breaker: 3 consecutive losses = 4h halt

## Output
```json
{
  "verdict": "PASS" | "FAIL",
  "failures": ["reason1", "reason2"],
  "recommended_position": {
    "size": 0.015,
    "leverage": 3,
    "stop_loss": 63500,
    "take_profit": 68000,
    "risk_usd": 10.00
  }
}
```
