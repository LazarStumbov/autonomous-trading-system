Scan Polymarket for mispriced markets and betting opportunities.

1. **Market Scan**: Pull active markets from Polymarket API, filter by liquidity and categories
2. **Account Check**: Check tracked accounts for new positions
3. **Odds Analysis**: For top candidate markets, estimate true probability via research
4. **Edge Calculation**: Calculate edge (estimated prob - market odds) and Kelly bet size
5. **News Context**: Check latest news relevant to candidate markets

Present opportunities as:
| Market Question | Category | Market Odds | Est. Prob | Edge | Kelly Bet | Top Account Signals |

Only show markets with edge >= 5% and sufficient liquidity.

For each opportunity, include:
- Key factors driving the probability estimate
- Confidence level (low/medium/high)
- Which tracked accounts have positions (if any)
- Recommended bet size (quarter-Kelly, capped at 5% bankroll)
