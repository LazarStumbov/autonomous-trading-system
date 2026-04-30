#!/bin/bash
# Deploy the autonomous trading system to Modal cloud.
#
# Prerequisites:
#   1. modal CLI installed: pip install modal
#   2. modal token configured: modal token new
#   3. Modal secrets created in dashboard:
#      - trading-broker-keys (OKX_API_KEY, OKX_SECRET_KEY, OKX_PASSPHRASE, OKX_DEMO)
#      - trading-data-keys (ALPHA_VANTAGE_API_KEY, FINNHUB_API_KEY, COINMARKETCAP_API_KEY, MARKETAUX_API_KEY)
#      - trading-ai-keys (ANTHROPIC_API_KEY, PERPLEXITY_API_KEY)
#      - trading-notification-keys (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
#
# Usage:
#   cd /path/to/Trading
#   bash modal/deploy.sh

set -e

echo "=== Autonomous Trading System - Modal Deployment ==="
echo ""

# Check modal is installed
if ! command -v modal &> /dev/null; then
    echo "Error: modal CLI not found. Install with: pip install modal"
    exit 1
fi

# Check we're in the right directory
if [ ! -f "CLAUDE.md" ]; then
    echo "Error: Run this script from the Trading project root"
    exit 1
fi

echo "Deploying to Modal..."
echo ""

modal deploy modal/trading_webhook.py

echo ""
echo "=== Deployment Complete ==="
echo ""
echo "Endpoints:"
echo "  - Status:          GET  /status"
echo "  - TradingView:     POST /tradingview_alert"
echo "  - Manual Trade:    POST /manual_trade"
echo "  - Halt Trading:    POST /halt_trading"
echo "  - Resume Trading:  POST /resume_trading"
echo ""
echo "Cron Jobs:"
echo "  - News scan:       Every 15 minutes"
echo "  - Market scan:     Every hour"
echo "  - Polymarket scan: Every 4 hours"
echo "  - Daily report:    21:00 UTC daily"
echo "  - Weekly review:   12:00 UTC Sunday"
echo ""
echo "Monitor at: https://modal.com/apps"
