"""Notification system for trade alerts, reports, and system events."""

import os
import json
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()


def load_notification_config() -> dict:
    """Load notification routing config."""
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "notifications.json")
    with open(config_path) as f:
        return json.load(f)


def send_telegram(message: str, parse_mode: str = "HTML") -> bool:
    """Send a message via Telegram bot.

    Args:
        message: Message text (supports HTML formatting)
        parse_mode: "HTML" or "Markdown"

    Returns:
        True if sent successfully
    """
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        print("[NOTIFY] Telegram not configured (missing bot token or chat ID)")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": parse_mode,
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"[NOTIFY] Telegram error: {e}")
        return False


def send_slack(message: str) -> bool:
    """Send a message via Slack webhook.

    Args:
        message: Message text (supports Slack markdown)

    Returns:
        True if sent successfully
    """
    webhook_url = os.getenv("SLACK_WEBHOOK_URL")

    if not webhook_url:
        print("[NOTIFY] Slack not configured (missing webhook URL)")
        return False

    try:
        resp = requests.post(webhook_url, json={"text": message}, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"[NOTIFY] Slack error: {e}")
        return False


def notify(alert_type: str, message: str, data: dict = None) -> dict:
    """Route a notification to the appropriate channels based on config.

    Args:
        alert_type: One of the alert types from notifications.json
        message: Human-readable message
        data: Optional structured data to include

    Returns:
        Dict with delivery status per channel
    """
    config = load_notification_config()
    channels = config.get("alert_routing", {}).get(alert_type, ["telegram"])
    results = {}

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    full_message = f"<b>[{alert_type.upper()}]</b> {timestamp}\n\n{message}"

    if data:
        details = "\n".join(f"  {k}: {v}" for k, v in data.items())
        full_message += f"\n\n<pre>{details}</pre>"

    for channel in channels:
        if channel == "telegram" and config["channels"]["telegram"]["enabled"]:
            results["telegram"] = send_telegram(full_message)
        elif channel == "slack" and config["channels"]["slack"]["enabled"]:
            results["slack"] = send_slack(message)

    return results


def notify_trade_executed(asset: str, direction: str, entry: float, sl: float, tp: float, leverage: float, size: float) -> dict:
    """Send trade execution notification."""
    msg = (
        f"{'🟢' if direction == 'long' else '🔴'} <b>{direction.upper()} {asset}</b>\n"
        f"Entry: ${entry:,.2f}\n"
        f"Stop Loss: ${sl:,.2f}\n"
        f"Take Profit: ${tp:,.2f}\n"
        f"Leverage: {leverage}x\n"
        f"Size: {size}"
    )
    return notify("trade_executed", msg)


def notify_trade_closed(asset: str, direction: str, pnl_usd: float, pnl_pct: float) -> dict:
    """Send trade close notification."""
    emoji = "💰" if pnl_usd > 0 else "💸"
    msg = (
        f"{emoji} <b>CLOSED {direction.upper()} {asset}</b>\n"
        f"P&L: ${pnl_usd:+,.2f} ({pnl_pct:+.1f}%)"
    )
    return notify("trade_closed", msg)


def notify_circuit_breaker(reason: str) -> dict:
    """Send circuit breaker alert."""
    msg = f"⚠️ <b>CIRCUIT BREAKER TRIGGERED</b>\n\n{reason}\n\nAll trading halted."
    return notify("circuit_breaker_triggered", msg)


def notify_drawdown_warning(daily_pct: float, weekly_pct: float) -> dict:
    """Send drawdown warning."""
    msg = (
        f"⚠️ <b>DRAWDOWN WARNING</b>\n"
        f"Daily: {daily_pct:.1f}%\n"
        f"Weekly: {weekly_pct:.1f}%"
    )
    return notify("drawdown_warning", msg)
