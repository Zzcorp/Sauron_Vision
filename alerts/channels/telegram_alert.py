"""Telegram alert channel — two-way bot with command support."""
import os
import requests
import logging

logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"


def send_telegram(title, message):
    """Send a message via Telegram bot."""
    if not BOT_TOKEN or not CHAT_ID:
        logger.warning("Telegram not configured")
        return

    text = f"*{title}*\n\n{message}"
    resp = requests.post(f"{BASE_URL}/sendMessage", json={
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
    })
    if not resp.ok:
        raise Exception(f"Telegram error: {resp.text}")


def send_strategy_proposal(strategy):
    """Send a strategy proposal with approve/reject buttons."""
    if not BOT_TOKEN or not CHAT_ID:
        return

    text = (
        f"*NEW STRATEGY PROPOSAL*\n\n"
        f"*{strategy.name}*\n"
        f"Horizon: {strategy.time_horizon}\n"
        f"Max allocation: {strategy.max_portfolio_allocation_pct}%\n\n"
        f"{strategy.description[:500]}\n\n"
        f"Reply with:\n"
        f"/approve {strategy.id} — to approve\n"
        f"/reject {strategy.id} — to reject"
    )

    requests.post(f"{BASE_URL}/sendMessage", json={
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
    })


def check_bot_updates():
    """Check for incoming Telegram messages (commands)."""
    if not BOT_TOKEN:
        return []

    try:
        resp = requests.get(f"{BASE_URL}/getUpdates", params={"timeout": 1, "limit": 10})
        if not resp.ok:
            return []
        data = resp.json()
        return data.get("result", [])
    except Exception:
        return []


def process_commands():
    """Process incoming Telegram commands."""
    from strategies.models import Strategy

    updates = check_bot_updates()
    processed = 0

    for update in updates:
        msg = update.get("message", {})
        text = msg.get("text", "").strip()

        if text.startswith("/approve "):
            try:
                strategy_id = int(text.split(" ")[1])
                strategy = Strategy.objects.get(id=strategy_id, status="proposed")
                strategy.status = "approved"
                strategy.save()
                send_telegram("Strategy Approved", f"{strategy.name} is now approved.")
                processed += 1
            except (ValueError, Strategy.DoesNotExist):
                send_telegram("Error", "Strategy not found or already processed.")

        elif text.startswith("/reject "):
            try:
                strategy_id = int(text.split(" ")[1])
                strategy = Strategy.objects.get(id=strategy_id, status="proposed")
                strategy.status = "rejected"
                strategy.save()
                send_telegram("Strategy Rejected", f"{strategy.name} has been rejected.")
                processed += 1
            except (ValueError, Strategy.DoesNotExist):
                send_telegram("Error", "Strategy not found or already processed.")

        elif text == "/status":
            from signals.models import Signal
            from portfolio.services import get_or_create_default_portfolio
            portfolio = get_or_create_default_portfolio()
            active_signals = Signal.objects.filter(is_active=True).count()
            send_telegram("Platform Status",
                f"Portfolio: {portfolio.currency} {portfolio.current_value}\n"
                f"Active signals: {active_signals}\n"
                f"Positions: {portfolio.positions.filter(closed_at__isnull=True).count()}"
            )
            processed += 1

        elif text == "/signals":
            from signals.models import Signal
            signals = Signal.objects.filter(is_active=True).order_by("-score")[:5]
            if signals:
                lines = ["*Active Signals:*\n"]
                for s in signals:
                    # The direction is already a word on this line, so the
                    # coloured dot it duplicated is gone rather than replaced
                    # — a Telegram client picks its own font for any mark.
                    lines.append(f"{s.instrument.symbol} {s.direction} — {s.score:.2f}")
                send_telegram("Signals", "\n".join(lines))
            else:
                send_telegram("Signals", "No active signals.")
            processed += 1

    return processed
