"""Signal dispatch — route notifications to users based on their preferences and rules."""
import logging
from django.contrib.auth.models import User
from alerts.models import AlertRule, UserNotificationPrefs

logger = logging.getLogger(__name__)


def dispatch_signal_alert(signal):
    """Send a signal notification to all users whose rules match."""
    from alerts.channels.telegram_alert import send_telegram
    from alerts.channels.email_alert import send_email_to_user
    from alerts.channels.whatsapp_alert import send_whatsapp_to_user

    for user in User.objects.filter(is_active=True):
        # Check user's alert rules
        rules = AlertRule.objects.filter(user=user, is_active=True)

        matched = False
        for rule in rules:
            if _rule_matches(rule, signal):
                matched = True
                title = f"Signal: {signal.instrument.symbol} {signal.direction.upper()}"
                message = (
                    f"Score: {signal.score:.2f}\n"
                    f"Type: {signal.signal_type}\n"
                    f"{signal.title}\n"
                    f"Urgency: {signal.urgency}"
                )

                if rule.notify_telegram:
                    try:
                        prefs = user.notification_prefs
                        if prefs.telegram_chat_id:
                            import requests, os
                            token = os.getenv("TELEGRAM_BOT_TOKEN", "")
                            if token:
                                requests.post(
                                    f"https://api.telegram.org/bot{token}/sendMessage",
                                    json={"chat_id": prefs.telegram_chat_id, "text": f"*{title}*\n{message}", "parse_mode": "Markdown"},
                                    timeout=10,
                                )
                    except Exception as e:
                        logger.warning(f"Telegram dispatch to {user.username} failed: {e}")

                if rule.notify_email:
                    send_email_to_user(user, title, message)

                if rule.notify_whatsapp:
                    send_whatsapp_to_user(user, title, message)

                break  # One match is enough

        # If no custom rules, check global prefs
        if not matched and not rules.exists():
            try:
                prefs = user.notification_prefs
                if prefs.receive_signals:
                    title = f"Signal: {signal.instrument.symbol} {signal.direction.upper()}"
                    message = f"Score: {signal.score:.2f} | {signal.title}"
                    if prefs.telegram_chat_id:
                        import requests, os
                        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
                        if token:
                            requests.post(
                                f"https://api.telegram.org/bot{token}/sendMessage",
                                json={"chat_id": prefs.telegram_chat_id, "text": f"*{title}*\n{message}", "parse_mode": "Markdown"},
                                timeout=10,
                            )
                    if prefs.email_notifications and user.email:
                        send_email_to_user(user, title, message)
            except Exception:
                pass


def _rule_matches(rule, signal):
    """Check if a signal matches an alert rule."""
    if rule.instrument_symbol and rule.instrument_symbol != signal.instrument.symbol:
        return False
    if rule.asset_class and rule.asset_class != signal.instrument.asset_class:
        return False
    if rule.direction and rule.direction != signal.direction:
        return False
    if signal.score < rule.min_score:
        return False
    return True


def dispatch_strategy_alert(strategy):
    """Notify users about a new strategy proposal."""
    from alerts.channels.telegram_alert import send_strategy_proposal
    send_strategy_proposal(strategy)


def dispatch_news_alert(article):
    """Notify users about critical news."""
    if not article.ai_urgency or article.ai_urgency not in ["critical", "high"]:
        return

    from alerts.channels.telegram_alert import send_telegram
    send_telegram(
        "Breaking News Alert",
        f"{article.title}\n\nSource: {article.source}\nUrgency: {article.ai_urgency.upper()}"
    )
