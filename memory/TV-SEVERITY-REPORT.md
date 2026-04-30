# TV Severity Sweep — tv_severity_20260430T132139Z.json

- started:  2026-04-29T23:13:06.980245+00:00
- ended:    2026-04-30T13:21:39.787056+00:00
- days:     180
- min_trades: 200
- symbols:  8
- timeframes: ['1h']

**PASS**: 65 · **FAIL**: 10 · **ERROR**: 0

## Passed (≥ gate trades)

| Strategy | Trades | Win % | Avg R |
|---|---:|---:|---:|
| `freqtrade.bb_width_squeeze` | 235 | 32% | +0.05R |
| `tradingview.range_filter` | 431 | 41% | +0.02R |
| `tradingview.supertrend_pullback` | 474 | 36% | +0.00R |
| `freqtrade.macd_divergence` | 939 | 39% | -0.02R |
| `freqtrade.range_filter_break` | 395 | 31% | -0.03R |
| `tradingview.squeeze_momentum` | 611 | 37% | -0.03R |
| `freqtrade.keltner_breakout` | 631 | 35% | -0.04R |
| `jesse.obv_trend` | 1403 | 35% | -0.05R |
| `freqtrade.awesome_macd_combo` | 1250 | 35% | -0.05R |
| `freqtrade.atr_squeeze_break` | 215 | 29% | -0.05R |
| `classic.ema_cross_9_21_50` | 712 | 38% | -0.06R |
| `freqtrade.parabolic_proxy` | 1337 | 34% | -0.07R |
| `freqtrade.heikin_ashi_trend` | 1165 | 35% | -0.08R |
| `classic.wilder_adx_trend` | 1064 | 37% | -0.08R |
| `jesse.ema_ribbon` | 1164 | 32% | -0.08R |
| `freqtrade.ichimoku_cloud_lite` | 1026 | 35% | -0.09R |
| `internal.momentum_breakout` | 939 | 47% | -0.09R |
| `freqtrade.macd_cross_v1` | 783 | 36% | -0.09R |
| `freqtrade.ema_cross_trend` | 506 | 33% | -0.10R |
| `classic.dual_thrust` | 1236 | 36% | -0.10R |
| `awesome_quant.dmi_adx` | 1381 | 34% | -0.10R |
| `classic.macd_momentum_12_26_9` | 521 | 36% | -0.10R |
| `classic.donchian_breakout_20_10` | 1285 | 30% | -0.10R |
| `jesse.fib_retrace` | 648 | 32% | -0.10R |
| `lean.opening_range` | 1744 | 31% | -0.12R |
| `jesse.chaikin_volatility` | 1278 | 33% | -0.12R |
| `awesome_quant.stochastic_kd` | 1767 | 38% | -0.12R |
| `freqtrade.macd_histogram_zero` | 778 | 35% | -0.12R |
| `tradingview.lonesome_engulfing` | 1215 | 35% | -0.12R |
| `freqtrade.supertrend_v2` | 436 | 33% | -0.12R |
| `lean.meb_faber_tactical` | 326 | 37% | -0.13R |
| `community.bb_squeeze_breakout` | 442 | 29% | -0.13R |
| `tradingview.chandelier_exit` | 1377 | 33% | -0.13R |
| `freqtrade.triple_ema_stack` | 736 | 32% | -0.13R |
| `tradingview.swing_failure_pattern` | 1168 | 31% | -0.13R |
| `freqtrade.three_white_soldiers` | 1141 | 35% | -0.13R |
| `classic.supertrend_follow_10_3` | 852 | 31% | -0.14R |
| `community.rsi_divergence` | 672 | 35% | -0.14R |
| `freqtrade.roc_momentum` | 600 | 32% | -0.14R |
| `tradingview.hull_ma_cross` | 1198 | 34% | -0.15R |
| `tradingview.qqe_signal` | 789 | 35% | -0.15R |
| `jesse.dual_thrust` | 559 | 30% | -0.16R |
| `freqtrade.donchian_50` | 594 | 28% | -0.16R |
| `jesse.bb_walk_trend` | 529 | 36% | -0.17R |
| `tradingview.volume_profile_poc` | 2411 | 36% | -0.17R |
| `awesome_quant.williams_r` | 540 | 34% | -0.18R |
| `lean.volatility_targeting` | 1399 | 27% | -0.19R |
| `classic.turtle_system2_55_20` | 614 | 27% | -0.19R |
| `tradingview.smc_liquidity_sweep` | 1879 | 33% | -0.19R |
| `freqtrade.nr4_breakout` | 1388 | 29% | -0.19R |
| `lean.pairs_zscore` | 1409 | 39% | -0.19R |
| `community.heikin_ashi_pullback` | 1142 | 32% | -0.20R |
| `awesome_quant.aroon_cross` | 990 | 31% | -0.21R |
| `freqtrade.bb_percent_b` | 634 | 38% | -0.22R |
| `freqtrade.inside_bar_break` | 1116 | 28% | -0.22R |
| `freqtrade.sma_50_200_golden` | 235 | 32% | -0.22R |
| `internal.mean_reversion` | 1078 | 42% | -0.23R |
| `community.vwap_reversion` | 1061 | 37% | -0.23R |
| `jesse.camarilla_revert` | 1659 | 35% | -0.24R |
| `community.inside_bar_followthrough` | 1174 | 31% | -0.25R |
| `lean.macro_regime` | 445 | 28% | -0.26R |
| `lean.dual_momentum` | 344 | 30% | -0.27R |
| `community.bb_rsi_scalper` | 919 | 36% | -0.27R |
| `community.funding_skew_revert` | 438 | 34% | -0.30R |
| `freqtrade.rsi_2_pullback` | 333 | 32% | -0.35R |

## Failed (below gate)

| Strategy | Trades | Reason |
|---|---:|---|
| `awesome_quant.mfi_extreme` | 168 | only_168_trades_below_200_gate |
| `awesome_quant.cci_extreme` | 158 | only_158_trades_below_200_gate |
| `jesse.pivot_bounce` | 150 | only_150_trades_below_200_gate |
| `freqtrade.volume_spike_long` | 145 | only_145_trades_below_200_gate |
| `freqtrade.bbands_rsi_v1` | 131 | only_131_trades_below_200_gate |
| `freqtrade.vwap_pullback` | 120 | only_120_trades_below_200_gate |
| `freqtrade.rsi_overbought_short` | 4 | only_4_trades_below_200_gate |
| `classic.elder_triple_screen` | 0 | only_0_trades_below_200_gate |
| `internal.copy_trade` | 0 | only_0_trades_below_200_gate |
| `internal.news_catalyst` | 0 | only_0_trades_below_200_gate |
