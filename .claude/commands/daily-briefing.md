Generate a comprehensive daily trading briefing. Execute the full pipeline:

1. **News Scan**: Run the news-monitor skill to check for breaking news and upcoming economic events
2. **Market Scan**: Run market-scan to pull fresh data and run technical analysis on the full watchlist
3. **Signal Follow**: Run signal-follow to check what top traders are doing
4. **Polymarket Scan**: Run polymarket-bet (scan mode) to check for PM opportunities
5. **Confluence Engine**: Run confluence-engine to detect multi-signal convergence
6. **Generate Report**: Compile everything into a daily briefing PDF using performance-report skill

Save the briefing to `data/reports/daily/` and send a summary via Telegram.

For each high-confluence setup (score >= 60), present the full analysis:
- Asset, direction, strategy, confidence score
- Entry/SL/TP levels with reasoning
- Supporting signals
- Risk check result

End with: upcoming events in next 24h, current portfolio status, daily P&L.
