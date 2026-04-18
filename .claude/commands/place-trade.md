Execute a trade through the full pipeline. This command requires explicit parameters.

Usage: /place-trade [asset] [direction] [entry] [stop_loss] [take_profit] [leverage]

Example: /place-trade BTC/USDT:USDT long 65000 63500 68000 3

Pipeline:
1. **Validate inputs** — Ensure all required parameters are provided
2. **Confluence check** — Run confluence-engine to verify signal alignment
3. **Risk check** — Run risk-check skill (MUST PASS to proceed)
4. **Confirm with user** — Show the full trade plan and ask for confirmation
5. **Execute** — Run execute-trade skill to place the order on Bybit
6. **Log** — Record in trade journal with full reasoning
7. **Notify** — Send Telegram alert with trade details

If risk check FAILS, show the rejection reasons and do NOT proceed.
If running in autonomous mode (via Modal cron), skip user confirmation but still require risk check PASS.
