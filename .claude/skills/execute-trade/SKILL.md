---
name: execute-trade
description: Execute trades on Bybit via ccxt. Place orders with stop loss and take profit, manage positions, handle partial exits and trailing stops. Only executes PASS-approved trades.
allowed-tools: Bash, Read
---

# Execute Trade Skill

Place and manage trades on Bybit. This skill ONLY works after a trade passes the risk-check gate.

## When to Use
- After risk-check returns PASS
- To manage existing open positions (adjust SL/TP)
- To manually close a position

## Prerequisites
- `BYBIT_API_KEY` and `BYBIT_SECRET_KEY` in `.env`
- `BYBIT_TESTNET=true` for paper trading (default)
- Risk check verdict must be PASS

## Pipeline

### Step 1: Build Order
```bash
python3 .claude/skills/execute-trade/scripts/order_builder.py --asset "BTC/USDT:USDT" --direction long --size 0.015 --leverage 3 --entry 65000 --sl 63500 --tp 68000
```
Constructs the complete order with entry, SL, TP parameters.

### Step 2: Execute via Bybit API
```bash
python3 .claude/skills/execute-trade/scripts/execution_engine.py --order-json '...'
```
Uses ccxt to:
1. Set leverage on the symbol
2. Place entry order (market or limit)
3. Place stop loss order
4. Place take profit order
5. Log to database and notify via Telegram

### Step 3: Monitor Position
```bash
python3 .claude/skills/execute-trade/scripts/position_monitor.py
```
Tracks all open positions:
- Check fill status
- Move SL to breakeven at 1R profit
- Activate trailing stop at configured threshold
- Handle partial TP (close 50% at 1R, let rest run)
- Detect and log closures

## Bybit API Integration
Uses `ccxt` library for unified exchange access:
```python
import ccxt
exchange = ccxt.bybit({
    'apiKey': os.getenv('BYBIT_API_KEY'),
    'secret': os.getenv('BYBIT_SECRET_KEY'),
    'sandbox': os.getenv('BYBIT_TESTNET', 'true').lower() == 'true',
})
```

## Safety Rules
- NEVER execute without a PASS from risk-check
- ALWAYS verify sufficient balance before placing order
- ALWAYS set stop loss — no naked positions
- Log every order attempt (success or failure) to database
