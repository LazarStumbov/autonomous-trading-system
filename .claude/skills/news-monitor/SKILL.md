---
name: news-monitor
description: Continuous news monitoring for market-moving events. Scans geopolitical, economic, regulatory, and crypto news every 15 minutes. Returns urgency-scored alerts with affected assets and trading implications.
allowed-tools: Bash, Read, WebSearch, WebFetch
---

# News Monitor Skill

Scan multiple news sources for events that could move markets.

## When to Use
- Every 15 minutes (highest frequency scan)
- When a geopolitical event is developing
- Before placing any trade (check for pending news)

## Pipeline

### Step 1: News Aggregation
```bash
python3 .claude/skills/news-monitor/scripts/news_aggregator.py
```
Pulls from MarketAux, Finnhub news, and web search for breaking headlines.
Filters for crypto, macro, geopolitical relevance.

### Step 2: Geopolitical Scanner
```bash
python3 .claude/skills/news-monitor/scripts/geopolitical_scanner.py
```
Specifically scans for war/conflict, sanctions, regime changes, trade disputes.
Maps to affected assets (gold, oil, crypto safe havens).

### Step 3: Economic Calendar
```bash
python3 .claude/skills/news-monitor/scripts/economic_calendar.py
```
Fetches upcoming economic events (CPI, NFP, Fed decisions, earnings).
Flags high-impact events within next 24 hours.

### Step 4: Sentiment Scoring
```bash
python3 .claude/skills/news-monitor/scripts/sentiment_scorer.py
```
NLP-based sentiment analysis on aggregated news.
Scores overall market sentiment and per-asset sentiment shifts.

## Output
- Urgency-scored alerts (1-10)
- Affected assets from watchlist
- Expected direction (bullish/bearish)
- Upcoming high-impact events
- Sentiment snapshot

## Urgency Levels
- **9-10**: IMMEDIATE ACTION — war, major hack, emergency policy
- **7-8**: HIGH — CPI surprise, ETF decision, major regulation
- **5-6**: MEDIUM — partnership, whale movement, exchange listing
- **1-4**: LOW — routine updates, scheduled events
