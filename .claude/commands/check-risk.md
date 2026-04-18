Portfolio risk snapshot. Check current risk exposure:

1. List all open positions with current P&L
2. Calculate total portfolio exposure (% of capital deployed)
3. Show daily drawdown status vs 6% limit
4. Show weekly drawdown status vs 15% limit
5. Check circuit breaker state (consecutive losses, halt status)
6. Show correlation analysis (how many positions in same direction)

Use `lib/risk_engine.py` and `lib/db.py` to pull current state.

Present as a risk dashboard:
- Capital: $XXX
- Open positions: X ($XXX deployed, XX% exposure)
- Daily P&L: $XX (X.X% drawdown)
- Weekly P&L: $XX (X.X% drawdown)
- Circuit breakers: OK / TRIGGERED
- Risk status: GREEN / YELLOW / RED
