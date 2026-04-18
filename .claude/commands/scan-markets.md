Quick market scan across the watchlist. Run market-scan skill:

1. Fetch latest prices for all assets in `config/watchlist.json`
2. Run technical analysis (RSI, MACD, BB, ATR, volume) on primary timeframe
3. Check for any setups matching strategy configs
4. Run confluence-engine on any detected signals

Report results as a concise table:
| Asset | Price | RSI | MACD | Trend | Volume | Signals | Score |

Highlight any assets with confluence score >= 60.
