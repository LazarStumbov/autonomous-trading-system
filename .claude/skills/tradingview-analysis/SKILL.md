---
name: tradingview-analysis
description: Receive and process TradingView alerts via webhook. Parse alert payloads, map TV indicators to internal signal format, and feed into the confluence engine.
allowed-tools: Bash, Read
---

# TradingView Analysis Skill

Integrate TradingView alerts into the autonomous trading pipeline.

## When to Use
- When a TradingView webhook alert is received
- When processing TV alert payloads from Modal endpoint

## Pipeline

### Step 1: Receive Webhook
The Modal deployment (`modal/trading_webhook.py`) exposes a `/alert/tradingview` endpoint.
TradingView sends alerts in JSON format with a secret for validation.

### Step 2: Parse Alert
```bash
python3 .claude/skills/tradingview-analysis/scripts/chart_analyzer.py --payload '{"symbol":"BTCUSDT","action":"buy","price":65000,...}'
```
Parses the TV alert payload and extracts:
- Symbol, timeframe
- Alert type (breakout, crossover, divergence, etc.)
- Price at trigger
- Any custom fields from the TV alert message

### Step 3: Map to Internal Signals
```bash
python3 .claude/skills/tradingview-analysis/scripts/indicator_mapper.py --tv-signal '...'
```
Maps TradingView alert data to our internal signal format:
- TV breakout alert → `technical_breakout` signal
- TV RSI divergence → feeds into confluence engine
- TV volume spike → `volume_anomaly` signal

The mapped signal is logged to the `signals` table and fed into the confluence engine.

## TradingView Alert Format
Configure TV alerts to send JSON like:
```json
{
  "secret": "{{webhook_secret}}",
  "symbol": "{{ticker}}",
  "action": "buy|sell",
  "price": {{close}},
  "timeframe": "{{interval}}",
  "indicator": "breakout|rsi_div|macd_cross|bb_squeeze|volume",
  "message": "{{strategy.order.comment}}"
}
```

## Integration Note
The TradingView-Claude system prompt will be provided separately and will define the full TV integration behavior. This skill handles the webhook/signal processing pipeline.
