# Daily Market Intelligence System

A Claude Code scheduled task that generates comprehensive daily trading briefings with market analysis, top trader discovery, Polymarket prediction market tracking, and multi-signal confluence detection.

## What it does

Every trading day, this system:

1. **Fetches market data** across US stocks, crypto, and forex from multiple APIs
2. **Runs technical analysis** (RSI, MACD, Bollinger Bands, S/R levels, volume) on your watchlist
3. **Discovers top 10 trending traders** from public trading platform leaderboards
4. **Discovers top 10 Polymarket accounts** with skill-based scoring (not just PnL)
5. **Runs confluence detection** to find high-confidence setups where multiple signals align
6. **Generates a professional PDF briefing** saved to your trading folder
7. **Updates rolling memory** to track which trader recommendations actually performed well
8. **Archives to Notion** for searchable history and performance tracking

## Quick start

### 1. Get free API keys

You need API keys from these free services:

| Service | URL | What it provides |
|---------|-----|-----------------|
| Alpha Vantage | https://www.alphavantage.co/support/#api-key | Stock quotes, forex, technicals |
| Finnhub | https://finnhub.io/register | News, sentiment, economic calendar |
| CoinMarketCap | https://coinmarketcap.com/api/ | Crypto prices, market caps |
| MarketAux | https://www.marketaux.com/ | Entity-tagged news with sentiment |

### 2. Configure your watchlist

Edit `config/watchlist.json`:

- Add your API keys in the `api_keys` section
- Customize `watchlist.us_stocks` with your tickers
- Customize `watchlist.crypto` with your coins
- Customize `watchlist.forex` with your pairs
- Set your `pdf_directory` path
- Adjust `technical_analysis.alert_thresholds` to your preferences

### 3. Install to Claude Code

Copy the project to your Claude Code workspace:

```bash
cp -r market-intel-system/ ~/your-project/
```

The slash command at `.claude/commands/daily-briefing.md` will be automatically recognized by Claude Code.

### 4. Set up the scheduled task

**Option A — Claude Desktop App (Cowork):**

1. Open Claude Desktop → Settings → Scheduled Tasks
2. Create new task
3. Set schedule: Daily at 14:00 (or your preferred pre-market time)
4. Set the task to run: `/daily-briefing`

**Option B — Claude Code CLI with cron:**

```bash
# Add to crontab (runs at 14:00 EET, Monday-Friday)
0 14 * * 1-5 cd ~/your-project && claude-code --command "/daily-briefing"
```

**Option C — Manual run:**

```bash
cd ~/your-project
claude /daily-briefing
```

## Project structure

```
market-intel-system/
├── .claude/
│   └── commands/
│       └── daily-briefing.md     # Main slash command (8-step pipeline)
├── config/
│   └── watchlist.json            # Your personalized configuration
├── data/
│   ├── trader_memory.json        # Rolling trader performance memory
│   └── raw/                      # Daily data snapshots (auto-created)
│       ├── market_data_YYYY-MM-DD.json
│       ├── technicals_YYYY-MM-DD.json
│       ├── top_traders_YYYY-MM-DD.json
│       ├── polymarket_traders_YYYY-MM-DD.json
│       └── confluence_YYYY-MM-DD.json
├── scripts/
│   ├── fetch_market_data.py      # Market data ingestion (stocks, crypto, forex)
│   ├── technical_analysis.py     # RSI, MACD, BB, S/R, volume analysis
│   ├── discover_traders.py       # Traditional market trader discovery
│   ├── discover_polymarket.py    # Polymarket leaderboard + scoring
│   ├── confluence_engine.py      # Multi-signal convergence detection
│   ├── generate_briefing_pdf.py  # Professional PDF generation
│   └── update_memory.py          # Rolling memory + performance tracking
└── README.md
```

## The scoring system

### Traditional traders
Composite score = weighted sum of:
- **Win rate consistency** (30%) — rolling 30-day, penalizing variance
- **Risk-adjusted returns** (25%) — PnL / max drawdown
- **Trade frequency** (20%) — active but not noise-trading
- **Specialization match** (15%) — aligned with your watchlist
- **Recency bonus** (10%) — recent performance weighted higher

### Polymarket traders
Skill score = **win_rate × ln(1 + total_positions)**

This formula is key — it separates genuine skill from lucky streaks. A trader who won 3 out of 3 bets gets a lower score than one who won 60 out of 100, because the latter has proven consistency at scale.

Additional factors: conviction scoring (position sizing patterns), category diversity, and memory-based boost/penalty from past recommendation accuracy.

### Confluence engine
Scans 7 independent signal types across all data sources:
1. Technical breakout
2. Sentiment shift
3. Trader accumulation
4. Polymarket whale entry
5. News catalyst
6. Volume anomaly
7. Cross-asset correlation

When 3+ independent sources agree → High Confluence Alert

## Customization

### Adding trading platforms
Edit `scripts/discover_traders.py` — the `collect_sample_traders()` function has commented examples for:
- Binance Futures leaderboard
- eToro popular investors
- dYdX leaderboard
- Bybit copy trading

Add your platform API integrations there.

### Changing the PDF layout
Edit `scripts/generate_briefing_pdf.py` — each section has its own `build_*` function. The color palette and styles are defined at the top of the file.

### Adjusting scoring weights
Edit `config/watchlist.json` → `trader_discovery.scoring_weights`

### Rate limits
The free API tiers have rate limits. The scripts include appropriate delays:
- Alpha Vantage: 5 calls/min → 12-second delays between calls
- Finnhub: 60 calls/min → no delay needed
- CoinMarketCap: 30 calls/min → no delay needed
- Polymarket: public API, reasonable rate limiting

## Important disclaimer

This system is an information tool, not financial advice. All trading decisions are yours. The confluence alerts, trader recommendations, and technical signals are data points to inform your judgment — not instructions to trade. Always use proper risk management.

## Notion integration

The system pushes daily summaries to Notion for searchable archiving. This requires:
1. Notion MCP server connected in Claude Desktop
2. A database titled "Daily Market Intelligence" in your Notion workspace
3. The `notion_archive: true` flag in `config/watchlist.json`

Each day creates a new page with the briefing summary, enabling you to:
- Search across all historical briefings
- Add your own notes after the trading day
- Track which confluence alerts were profitable over time
- Build a personal trading journal alongside the automated analysis
