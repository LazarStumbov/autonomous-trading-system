"""Telegram bot command handler for the trading system.

Listens for incoming messages and dispatches commands:
  status update / status / /status  → open positions snapshot
  pnl / /pnl                        → today's P&L
  help / /help                      → command list

Registration:
  After deploying the telegram_webhook Modal endpoint, register the URL once:
    curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
         -H "Content-Type: application/json" \
         -d '{"url": "https://<your-modal-url>/telegram-webhook"}'
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)


# ─── Telegram send ────────────────────────────────────────────────────────────

def _send(chat_id: str | int, text: str) -> None:
    import requests
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        print("[telegram_bot] TELEGRAM_BOT_TOKEN not set")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        ).raise_for_status()
    except Exception as e:
        print(f"[telegram_bot] send failed: {e}")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _time_ago(dt_str: str | None) -> str:
    """Return a human-readable 'Xh Ym' ago string for a stored ISO datetime."""
    if not dt_str:
        return "unknown"
    try:
        # Handle both naive and tz-aware strings
        if dt_str.endswith("Z"):
            dt_str = dt_str[:-1] + "+00:00"
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        total_seconds = int(delta.total_seconds())
        if total_seconds < 60:
            return f"{total_seconds}s"
        if total_seconds < 3600:
            return f"{total_seconds // 60}m"
        h, m = divmod(total_seconds // 60, 60)
        return f"{h}h {m}m" if m else f"{h}h"
    except Exception:
        return "?"


def _fetch_price(symbol: str) -> float | None:
    """Fetch current market price via public exchange (no auth required)."""
    try:
        from lib.paper_engine import get_public_price
        return get_public_price(symbol)
    except Exception:
        pass
    # Fallback: try ccxt directly
    try:
        import ccxt
        ex_id = os.environ.get("PAPER_PRICE_EXCHANGE", "okx")
        ex_cls = getattr(ccxt, ex_id, None)
        if ex_cls:
            ex = ex_cls({"options": {"defaultType": "swap"}, "enableRateLimit": True})
            candles = ex.fetch_ohlcv(symbol, "1m", limit=2)
            if candles:
                return float(candles[-1][4])
    except Exception:
        pass
    return None


# ─── Command: status update ───────────────────────────────────────────────────

def _build_status_message() -> str:
    from lib.db import get_connection, init_db, get_open_trades, get_system_state

    init_db()
    conn = get_connection()
    try:
        trades = get_open_trades(conn)
        daily_pnl = float(get_system_state(conn, "daily_pnl_usd") or 0)
        halted = get_system_state(conn, "trading_halted") == "true"
        consec_losses = int(get_system_state(conn, "consecutive_losses") or 0)
    finally:
        conn.close()

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = [f"📊 <b>Status Update</b> — {now_str}"]

    if halted:
        lines.append("\n🛑 <b>TRADING HALTED</b>")
    if consec_losses >= 2:
        lines.append(f"⚠️ Consecutive losses: {consec_losses}")

    market_trades = [t for t in trades if t.get("pillar") == "market"]
    pm_trades     = [t for t in trades if t.get("pillar") == "polymarket"]

    if not trades:
        lines.append("\n<i>No open positions.</i>")
    else:
        lines.append(f"\n<b>Open Positions: {len(trades)}</b>")

    # ── Market positions ──
    total_unrealized = 0.0
    for i, t in enumerate(market_trades, 1):
        asset     = t["asset"]
        direction = t["direction"]
        entry     = float(t["entry_price"])
        sl        = float(t["stop_loss"] or 0)
        tp        = float(t["take_profit"] or 0)
        qty       = float(t["quantity"] or 0)
        leverage  = float(t.get("leverage") or 1)
        opened_at = t.get("opened_at") or t.get("timestamp")

        price = _fetch_price(asset)
        if price is None:
            price = entry  # fallback: no movement shown

        if direction == "long":
            pnl_usd = (price - entry) * qty
            r_moved = (price - entry) / abs(entry - sl) if sl and sl != entry else 0.0
            sl_dist_pct  = (sl   - price) / price * 100 if sl  else 0.0
            tp_dist_pct  = (tp   - price) / price * 100 if tp  else 0.0
        else:
            pnl_usd = (entry - price) * qty
            r_moved = (entry - price) / abs(entry - sl) if sl and sl != entry else 0.0
            sl_dist_pct  = (price - sl)  / price * 100 if sl  else 0.0
            tp_dist_pct  = (price - tp)  / price * 100 if tp  else 0.0

        pnl_pct = (pnl_usd / (entry * qty)) * 100 if entry and qty else 0.0
        total_unrealized += pnl_usd

        dir_emoji = "🟢" if direction == "long" else "🔴"
        pnl_sign  = "+" if pnl_usd >= 0 else ""
        pnl_emoji = "💰" if pnl_usd >= 0 else "📉"

        lines.append(
            f"\n{i}. {dir_emoji} <b>{direction.upper()} {asset}</b>"
            f"  [{leverage}x]"
        )
        lines.append(
            f"   Entry: <code>${entry:,.4f}</code> → Now: <code>${price:,.4f}</code>"
        )
        lines.append(
            f"   {pnl_emoji} P&L: <b>{pnl_sign}${pnl_usd:.2f} ({pnl_sign}{pnl_pct:.2f}%)</b>"
            f"  [{pnl_sign}{r_moved:.2f}R]"
        )
        sl_label  = f"<code>${sl:,.4f}</code> ({sl_dist_pct:+.2f}%)"  if sl else "—"
        tp_label  = f"<code>${tp:,.4f}</code> ({tp_dist_pct:+.2f}%)"  if tp else "—"
        lines.append(f"   SL: {sl_label} | TP: {tp_label}")
        lines.append(f"   Open: {_time_ago(opened_at)}")

    if market_trades:
        sign = "+" if total_unrealized >= 0 else ""
        lines.append(f"\n💼 Total unrealized: <b>{sign}${total_unrealized:.2f}</b>")

    # ── Polymarket positions ──
    if pm_trades:
        lines.append(f"\n🎯 <b>Polymarket Bets: {len(pm_trades)}</b>")
        for t in pm_trades:
            direction = t["direction"]          # 'yes' or 'no'
            entry     = float(t["entry_price"]) # odds at entry (0–1)
            qty       = float(t["quantity"] or 0)
            opened_at = t.get("opened_at") or t.get("timestamp")
            asset     = t["asset"]
            lines.append(
                f"  • {direction.upper()} <i>{asset[:60]}</i>"
                f"  Entry odds: {entry:.2%} | Stake: ${qty:.2f}"
                f"  (open {_time_ago(opened_at)})"
            )

    # ── Daily P&L footer ──
    dpnl_sign = "+" if daily_pnl >= 0 else ""
    lines.append(f"\n📅 Daily realized P&L: <b>{dpnl_sign}${daily_pnl:.2f}</b>")

    return "\n".join(lines)


# ─── Command: pnl ─────────────────────────────────────────────────────────────

def _build_pnl_message() -> str:
    from lib.db import get_connection, init_db, get_system_state, get_daily_stats

    init_db()
    conn = get_connection()
    try:
        daily_pnl = float(get_system_state(conn, "daily_pnl_usd") or 0)
        stats = get_daily_stats(conn) or {}
    finally:
        conn.close()

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sign = "+" if daily_pnl >= 0 else ""
    emoji = "💰" if daily_pnl >= 0 else "📉"

    lines = [
        f"{emoji} <b>P&L — {now_str}</b>",
        f"Realized: <b>{sign}${daily_pnl:.2f}</b>",
    ]
    if stats:
        lines += [
            f"Trades closed: {stats.get('total_trades', 0)}",
            f"Wins / Losses: {stats.get('winning_trades', 0)} / {stats.get('losing_trades', 0)}",
        ]
    return "\n".join(lines)


# ─── Command: help ────────────────────────────────────────────────────────────

def _build_help_message() -> str:
    return (
        "🤖 <b>Trading Bot Commands</b>\n\n"
        "/status  —  Open positions snapshot (P&L, SL, TP)\n"
        "/pnl     —  Today's realized P&L summary\n"
        "/help    —  This message"
    )


# ─── Dispatcher ───────────────────────────────────────────────────────────────

_STATUS_TRIGGERS = {"status", "status update", "/status"}
_PNL_TRIGGERS    = {"pnl", "/pnl", "daily pnl"}
_HELP_TRIGGERS   = {"help", "/help", "/start"}


def handle_update(payload: dict) -> None:
    """Parse a Telegram update payload and respond."""
    message = payload.get("message") or payload.get("edited_message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    text    = (message.get("text") or "").strip().lower()

    if not chat_id or not text:
        return

    if text in _STATUS_TRIGGERS:
        reply = _build_status_message()
    elif text in _PNL_TRIGGERS:
        reply = _build_pnl_message()
    elif text in _HELP_TRIGGERS:
        reply = _build_help_message()
    else:
        # Unknown command — only reply if it looks like a command attempt
        if text.startswith("/") or "status" in text or "pnl" in text:
            reply = "❓ Unknown command. Try /help"
        else:
            return  # ignore plain messages

    _send(chat_id, reply)
