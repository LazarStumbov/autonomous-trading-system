"""Backtester: replays a strategy against historical OHLCV and returns trade metrics.

This is the gatekeeper that decides which strategies graduate backtest → paper
and (via strategy_tuner.py) paper → live. It uses the SAME `Strategy` interface
as the live scanner so backtest behavior matches live behavior exactly — no
separate signal logic to drift out of sync.

Design notes:
  - Bar-by-bar simulation, not vectorized. Slower, but lets us reuse the
    strategy's own entry_signal / exit_signal methods without rewriting them.
  - Risk sizing honors the strategy's `sizing()` suggestion but caps risk at
    the project-wide max (currently 2% per trade, from risk_params.json).
  - Exits in priority order: stop-loss → take-profit → strategy exit_signal →
    timeout (default 10 * timeframe bars).
  - Fees + slippage are applied on every entry and exit.
  - Outputs go to data/backtests/<strategy_id>/<run_timestamp>.json AND
    the backtest_results DB table.

CLI:
    python3 lib/backtester.py --strategy internal.momentum_breakout --days 90
    python3 lib/backtester.py --promote-all
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from lib.strategy_engine import Strategy, EntrySignal, Sizing, ohlcv_from_candles
from lib.strategy_loader import load_all
from lib.technical_indicators import atr as atr_fn
from lib.historical_data import fetch_ohlcv, candles_to_ohlcv, slice_ohlcv, TF_MS
from lib.db import get_connection, log_backtest, set_strategy_mode


# ── Defaults ─────────────────────────────────────────────────────────────────
DEFAULT_FEE_BPS = 6.0               # 0.06% round-trip on crypto perps
DEFAULT_SLIPPAGE_BPS = 3.0          # 0.03% per side
DEFAULT_STARTING_CAPITAL = 500.0
DEFAULT_MAX_RISK_PCT = 2.0          # matches risk_params.json
DEFAULT_TIMEOUT_BARS = 60           # exit stale trades after N bars
MIN_BARS_FOR_SIGNAL = 60            # warmup before any strategy is called
BACKTEST_OUT_DIR = os.path.join(PROJECT_ROOT, "data", "backtests")
GATES_PATH = os.path.join(PROJECT_ROOT, "config", "strategy_gates.json")


# ── Data containers ──────────────────────────────────────────────────────────
@dataclass
class BacktestTrade:
    entry_index: int
    exit_index: int
    entry_ts: Optional[int]
    exit_ts: Optional[int]
    direction: str
    entry_price: float
    exit_price: float
    stop_loss: float
    take_profit: float
    quantity: float
    leverage: float
    pnl_usd: float
    pnl_r: float
    exit_reason: str
    fees_usd: float


@dataclass
class BacktestResult:
    strategy_id: str
    symbol: str
    timeframe: str
    period_start: str
    period_end: str
    starting_capital: float
    ending_capital: float
    trades: list[BacktestTrade] = field(default_factory=list)
    # metrics (set by _compute_metrics)
    n_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    sharpe: float = 0.0
    sortino: float = 0.0
    max_dd_pct: float = 0.0
    avg_r: float = 0.0
    total_return_pct: float = 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["trades"] = [asdict(t) for t in self.trades]
        return d


# ── Metrics ──────────────────────────────────────────────────────────────────
def _compute_metrics(result: BacktestResult) -> None:
    trades = result.trades
    n = len(trades)
    result.n_trades = n
    if n == 0:
        return

    wins = [t for t in trades if t.pnl_usd > 0]
    losses = [t for t in trades if t.pnl_usd <= 0]
    result.win_rate = len(wins) / n
    gross_wins = sum(t.pnl_usd for t in wins)
    gross_losses = abs(sum(t.pnl_usd for t in losses))
    result.profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else float("inf") if gross_wins > 0 else 0.0
    result.avg_r = sum(t.pnl_r for t in trades) / n
    result.total_return_pct = ((result.ending_capital - result.starting_capital) / result.starting_capital) * 100

    # Equity curve for Sharpe / Sortino / max DD
    equity = [result.starting_capital]
    capital = result.starting_capital
    for t in trades:
        capital += t.pnl_usd
        equity.append(capital)

    returns = []
    for i in range(1, len(equity)):
        prev = equity[i - 1] if equity[i - 1] != 0 else 1e-9
        returns.append((equity[i] - equity[i - 1]) / prev)

    if returns:
        mean_r = sum(returns) / len(returns)
        var_r = sum((r - mean_r) ** 2 for r in returns) / len(returns)
        std_r = math.sqrt(var_r) if var_r > 0 else 1e-9
        downside = [r for r in returns if r < 0]
        var_d = sum((r - 0) ** 2 for r in downside) / len(downside) if downside else 0.0
        std_d = math.sqrt(var_d) if var_d > 0 else 1e-9
        # Annualize roughly by trade frequency (approx trades/year)
        annual_factor = math.sqrt(252) if n > 0 else 1
        result.sharpe = (mean_r / std_r) * annual_factor if std_r > 0 else 0.0
        result.sortino = (mean_r / std_d) * annual_factor if std_d > 0 else 0.0

    peak = equity[0]
    max_dd = 0.0
    for e in equity:
        if e > peak:
            peak = e
        dd = (peak - e) / peak if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
    result.max_dd_pct = max_dd * 100


# ── Simulator ────────────────────────────────────────────────────────────────
def _position_size(capital: float, entry: float, stop: float, max_risk_pct: float, max_leverage: float) -> tuple[float, float]:
    """Return (quantity, leverage) subject to the project-wide risk cap."""
    risk_usd = capital * (max_risk_pct / 100.0)
    sl_distance = abs(entry - stop)
    if sl_distance <= 0:
        return 0.0, 1.0
    qty = risk_usd / sl_distance
    notional = qty * entry
    leverage = notional / (capital * 0.3)  # align with max 30% deployment rule
    if leverage > max_leverage:
        qty = (capital * 0.3 * max_leverage) / entry
        leverage = max_leverage
    return qty, max(1.0, leverage)


def _apply_fees_slippage(price: float, side: str, fee_bps: float, slip_bps: float) -> tuple[float, float]:
    """Return (effective_price, fee_usd_rate). Slippage is applied to the fill price;
    the fee is returned as a multiplier you apply to notional when the trade closes."""
    slip = price * (slip_bps / 10_000.0)
    # Buys fill worse (higher), sells fill worse (lower)
    effective = price + slip if side == "buy" else price - slip
    fee_rate = fee_bps / 10_000.0
    return effective, fee_rate


def backtest_strategy(
    strategy: Strategy,
    symbol: str,
    timeframe: str,
    candles: list[list],
    starting_capital: float = DEFAULT_STARTING_CAPITAL,
    fee_bps: float = DEFAULT_FEE_BPS,
    slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
    max_risk_pct: float = DEFAULT_MAX_RISK_PCT,
    max_leverage: float = 10.0,
    timeout_bars: int = DEFAULT_TIMEOUT_BARS,
) -> BacktestResult:
    """Replay strategy bar-by-bar against a candle list ([[ts,o,h,l,c,v], ...])."""
    ohlcv_full = candles_to_ohlcv(candles)
    n = len(candles)

    capital = starting_capital
    open_pos: Optional[dict] = None
    trades: list[BacktestTrade] = []

    period_start = datetime.fromtimestamp(candles[0][0] / 1000, tz=timezone.utc).isoformat() if n else ""
    period_end = datetime.fromtimestamp(candles[-1][0] / 1000, tz=timezone.utc).isoformat() if n else ""

    for i in range(MIN_BARS_FOR_SIGNAL, n):
        window = slice_ohlcv(ohlcv_full, i)
        bar = {
            "open": window["open"][-1],
            "high": window["high"][-1],
            "low": window["low"][-1],
            "close": window["close"][-1],
            "volume": window["volume"][-1],
            "timestamp": window["timestamp"][-1],
            "index": i,
        }

        # ── If a position is open, check for exit ─────────────────────────
        if open_pos is not None:
            exit_reason = None
            exit_price = None
            # Intrabar: check SL first (conservative — assume worst price hit first)
            if open_pos["direction"] == "long":
                if bar["low"] <= open_pos["stop_loss"]:
                    exit_price, exit_reason = open_pos["stop_loss"], "stop_loss"
                elif bar["high"] >= open_pos["take_profit"]:
                    exit_price, exit_reason = open_pos["take_profit"], "take_profit"
            else:  # short
                if bar["high"] >= open_pos["stop_loss"]:
                    exit_price, exit_reason = open_pos["stop_loss"], "stop_loss"
                elif bar["low"] <= open_pos["take_profit"]:
                    exit_price, exit_reason = open_pos["take_profit"], "take_profit"

            # Timeout
            if exit_reason is None and (i - open_pos["entry_index"]) >= timeout_bars:
                exit_price, exit_reason = bar["close"], "timeout"

            # Strategy-driven early exit
            if exit_reason is None:
                try:
                    indicators = strategy.populate_indicators(window)
                    early = strategy.exit_signal(indicators, bar, open_pos)
                    if early is not None:
                        exit_price, exit_reason = bar["close"], f"strategy:{early.reason}"
                except Exception:
                    pass

            if exit_reason is not None:
                # Apply exit slippage + fees
                side = "sell" if open_pos["direction"] == "long" else "buy"
                eff_exit, fee_rate = _apply_fees_slippage(exit_price, side, fee_bps, slippage_bps)
                qty = open_pos["quantity"]
                if open_pos["direction"] == "long":
                    gross = (eff_exit - open_pos["entry_price"]) * qty
                else:
                    gross = (open_pos["entry_price"] - eff_exit) * qty
                fees = (open_pos["entry_price"] * qty + eff_exit * qty) * fee_rate
                pnl = gross - fees - open_pos["entry_fee"]
                r_distance = abs(open_pos["entry_price"] - open_pos["stop_loss"]) * qty
                pnl_r = pnl / r_distance if r_distance > 0 else 0.0

                trades.append(BacktestTrade(
                    entry_index=open_pos["entry_index"],
                    exit_index=i,
                    entry_ts=open_pos["entry_ts"],
                    exit_ts=bar["timestamp"],
                    direction=open_pos["direction"],
                    entry_price=open_pos["entry_price"],
                    exit_price=eff_exit,
                    stop_loss=open_pos["stop_loss"],
                    take_profit=open_pos["take_profit"],
                    quantity=qty,
                    leverage=open_pos["leverage"],
                    pnl_usd=pnl,
                    pnl_r=pnl_r,
                    exit_reason=exit_reason,
                    fees_usd=fees + open_pos["entry_fee"],
                ))
                capital += pnl
                open_pos = None

        # ── If flat, check for entry ──────────────────────────────────────
        if open_pos is None and capital > 0:
            try:
                indicators = strategy.populate_indicators(window)
                entry: Optional[EntrySignal] = strategy.entry_signal(indicators, bar)
            except Exception:
                entry = None

            if entry is not None:
                atr_vals = indicators.get("atr_14") or atr_fn(window["high"], window["low"], window["close"], 14)
                atr_val = atr_vals[-1] if atr_vals and atr_vals[-1] is not None else 0.0
                if atr_val <= 0:
                    continue

                sizing: Sizing = strategy.sizing(entry_price=bar["close"], atr_value=atr_val, entry=entry)
                # Apply entry slippage
                side = "buy" if entry.direction == "long" else "sell"
                eff_entry, fee_rate = _apply_fees_slippage(bar["close"], side, fee_bps, slippage_bps)
                qty, lev = _position_size(capital, eff_entry, sizing.stop_loss, max_risk_pct, max_leverage)
                if qty <= 0:
                    continue

                entry_fee = eff_entry * qty * fee_rate
                open_pos = {
                    "entry_index": i,
                    "entry_ts": bar["timestamp"],
                    "direction": entry.direction,
                    "entry_price": eff_entry,
                    "stop_loss": sizing.stop_loss,
                    "take_profit": sizing.take_profit,
                    "quantity": qty,
                    "leverage": lev,
                    "entry_fee": entry_fee,
                }

    # Close any still-open position at the final bar
    if open_pos is not None and n > 0:
        last = candles[-1]
        side = "sell" if open_pos["direction"] == "long" else "buy"
        eff_exit, fee_rate = _apply_fees_slippage(last[4], side, fee_bps, slippage_bps)
        qty = open_pos["quantity"]
        if open_pos["direction"] == "long":
            gross = (eff_exit - open_pos["entry_price"]) * qty
        else:
            gross = (open_pos["entry_price"] - eff_exit) * qty
        fees = (open_pos["entry_price"] * qty + eff_exit * qty) * fee_rate
        pnl = gross - fees - open_pos["entry_fee"]
        r_distance = abs(open_pos["entry_price"] - open_pos["stop_loss"]) * qty
        pnl_r = pnl / r_distance if r_distance > 0 else 0.0
        trades.append(BacktestTrade(
            entry_index=open_pos["entry_index"],
            exit_index=n - 1,
            entry_ts=open_pos["entry_ts"],
            exit_ts=last[0],
            direction=open_pos["direction"],
            entry_price=open_pos["entry_price"],
            exit_price=eff_exit,
            stop_loss=open_pos["stop_loss"],
            take_profit=open_pos["take_profit"],
            quantity=qty,
            leverage=open_pos["leverage"],
            pnl_usd=pnl,
            pnl_r=pnl_r,
            exit_reason="period_end",
            fees_usd=fees + open_pos["entry_fee"],
        ))
        capital += pnl

    result = BacktestResult(
        strategy_id=strategy.strategy_id,
        symbol=symbol,
        timeframe=timeframe,
        period_start=period_start,
        period_end=period_end,
        starting_capital=starting_capital,
        ending_capital=capital,
        trades=trades,
    )
    _compute_metrics(result)
    return result


# ── Promotion gate ───────────────────────────────────────────────────────────
def load_gates() -> dict:
    if not os.path.exists(GATES_PATH):
        return {}
    with open(GATES_PATH) as f:
        return json.load(f)


def passes_backtest_gate(result: BacktestResult, gates: dict) -> tuple[bool, list[str]]:
    """Check if a backtest result qualifies for paper promotion."""
    g = gates.get("backtest_to_paper", {})
    reasons: list[str] = []
    if result.n_trades < g.get("min_trades", 30):
        reasons.append(f"trades {result.n_trades} < {g.get('min_trades', 30)}")
    if result.win_rate < g.get("min_win_rate", 0.45):
        reasons.append(f"win_rate {result.win_rate:.2f} < {g.get('min_win_rate', 0.45)}")
    if result.profit_factor < g.get("min_profit_factor", 1.3):
        reasons.append(f"profit_factor {result.profit_factor:.2f} < {g.get('min_profit_factor', 1.3)}")
    if result.sharpe < g.get("min_sharpe", 1.0):
        reasons.append(f"sharpe {result.sharpe:.2f} < {g.get('min_sharpe', 1.0)}")
    if result.max_dd_pct > g.get("max_drawdown_pct", 20.0):
        reasons.append(f"max_dd {result.max_dd_pct:.2f}% > {g.get('max_drawdown_pct', 20.0)}%")
    return (len(reasons) == 0, reasons)


# ── Orchestration ────────────────────────────────────────────────────────────
def _save_backtest_report(result: BacktestResult, passed: bool, fail_reasons: list[str]) -> str:
    d = os.path.join(BACKTEST_OUT_DIR, result.strategy_id.replace("/", "_"))
    Path(d).mkdir(parents=True, exist_ok=True)
    path = os.path.join(d, f"{int(time.time())}.json")
    with open(path, "w") as f:
        payload = result.to_dict()
        payload["passed_gate"] = passed
        payload["fail_reasons"] = fail_reasons
        json.dump(payload, f, indent=2)
    return path


def run_backtest(
    strategy: Strategy,
    symbol: str,
    timeframe: str,
    days: int,
    save: bool = True,
) -> tuple[BacktestResult, bool, list[str]]:
    since_ms = int(time.time() * 1000) - days * 24 * 60 * 60_000
    candles = fetch_ohlcv(symbol, timeframe, since_ms=since_ms)
    if len(candles) < MIN_BARS_FOR_SIGNAL:
        empty = BacktestResult(
            strategy_id=strategy.strategy_id,
            symbol=symbol,
            timeframe=timeframe,
            period_start="",
            period_end="",
            starting_capital=DEFAULT_STARTING_CAPITAL,
            ending_capital=DEFAULT_STARTING_CAPITAL,
        )
        return empty, False, [f"insufficient history ({len(candles)} bars)"]

    result = backtest_strategy(strategy, symbol, timeframe, candles)
    gates = load_gates()
    passed, reasons = passes_backtest_gate(result, gates)

    if save:
        _save_backtest_report(result, passed, reasons)
        conn = get_connection()
        try:
            log_backtest(
                conn,
                strategy_id=strategy.strategy_id,
                period_start=result.period_start,
                period_end=result.period_end,
                symbols_json=json.dumps([symbol]),
                timeframe=timeframe,
                starting_capital=result.starting_capital,
                ending_capital=result.ending_capital,
                trades=result.n_trades,
                win_rate=result.win_rate,
                profit_factor=result.profit_factor if result.profit_factor != float("inf") else 999.0,
                sharpe=result.sharpe,
                sortino=result.sortino,
                max_dd_pct=result.max_dd_pct,
                avg_r=result.avg_r,
                params_json=json.dumps(strategy.effective_params),
                passed_gate=1 if passed else 0,
                notes="; ".join(reasons) if reasons else "gate passed",
            )
        finally:
            conn.close()
    return result, passed, reasons


def promote_all(days: int = 90, symbols: Optional[list[str]] = None, timeframes: Optional[list[str]] = None) -> None:
    """Run every backtest-mode strategy against each symbol/timeframe and promote passers."""
    symbols = symbols or ["BTC/USDT:USDT", "ETH/USDT:USDT"]
    timeframes = timeframes or ["1h"]
    strategies = load_all(include_disabled=False, modes={"backtest"})
    print(f"[promote-all] {len(strategies)} backtest-mode strategies to evaluate")

    conn = get_connection()
    try:
        for strat in strategies:
            # Require ALL symbol/timeframe pairs to pass, conservative
            all_passed = True
            last_fail_reasons: list[str] = []
            for sym in symbols:
                for tf in timeframes:
                    if strat.metadata.timeframes and tf not in strat.metadata.timeframes:
                        continue
                    result, passed, reasons = run_backtest(strat, sym, tf, days)
                    print(
                        f"  [{strat.strategy_id}] {sym} {tf}: "
                        f"trades={result.n_trades} wr={result.win_rate:.2f} "
                        f"pf={result.profit_factor:.2f} sharpe={result.sharpe:.2f} "
                        f"dd={result.max_dd_pct:.1f}% -> {'PASS' if passed else 'FAIL'}"
                    )
                    if not passed:
                        all_passed = False
                        last_fail_reasons = reasons
            if all_passed:
                set_strategy_mode(conn, strat.strategy_id, "paper", reason="auto-promoted via backtest gate")
                print(f"    -> promoted to paper")
            else:
                print(f"    -> stays in backtest ({'; '.join(last_fail_reasons)})")
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Backtest strategies and apply promotion gates")
    parser.add_argument("--strategy", help="Strategy slug, e.g. internal.momentum_breakout")
    parser.add_argument("--symbol", default="BTC/USDT:USDT")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--promote-all", action="store_true", help="Evaluate all backtest-mode strategies")
    args = parser.parse_args()

    if args.promote_all:
        promote_all(days=args.days)
        return

    if not args.strategy:
        parser.error("either --strategy or --promote-all is required")

    strategies = {s.strategy_id: s for s in load_all(include_disabled=True)}
    strat = strategies.get(args.strategy)
    if not strat:
        print(f"Unknown strategy: {args.strategy}")
        print(f"Known: {sorted(strategies.keys())}")
        sys.exit(1)

    result, passed, reasons = run_backtest(strat, args.symbol, args.timeframe, args.days)
    print(f"\n=== Backtest {strat.strategy_id} {args.symbol} {args.timeframe} ({args.days}d) ===")
    print(f"  period:         {result.period_start} → {result.period_end}")
    print(f"  trades:         {result.n_trades}")
    print(f"  win_rate:       {result.win_rate:.2%}")
    print(f"  profit_factor:  {result.profit_factor:.2f}")
    print(f"  sharpe:         {result.sharpe:.2f}")
    print(f"  sortino:        {result.sortino:.2f}")
    print(f"  max_dd:         {result.max_dd_pct:.2f}%")
    print(f"  avg_r:          {result.avg_r:.2f}")
    print(f"  total_return:   {result.total_return_pct:.2f}%")
    print(f"  gate:           {'PASS' if passed else 'FAIL — ' + '; '.join(reasons)}")


if __name__ == "__main__":
    main()
