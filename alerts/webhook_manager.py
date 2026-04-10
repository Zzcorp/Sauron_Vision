"""Webhook manager — delivery functions for user-defined webhook endpoints."""
import logging
import requests
import json
from django.utils import timezone

logger = logging.getLogger(__name__)


def send_webhook_event(event_type, payload, user=None):
    """Send an event to all matching webhook endpoints.

    event_type: 'signal', 'trade', 'alert', 'portfolio', 'news'
    payload: dict to send as JSON
    user: specific user, or None for all users
    """
    from alerts.models import WebhookEndpoint

    field_map = {
        'signal': 'on_signal',
        'trade': 'on_trade',
        'alert': 'on_alert',
        'portfolio': 'on_portfolio',
        'news': 'on_news',
    }

    filter_field = field_map.get(event_type)
    if not filter_field:
        return 0

    qs = WebhookEndpoint.objects.filter(is_active=True, **{filter_field: True})
    if user:
        qs = qs.filter(user=user)

    # Skip webhooks with too many consecutive failures
    qs = qs.filter(consecutive_failures__lt=10)

    sent = 0
    for webhook in qs:
        try:
            _deliver_webhook(webhook, event_type, payload)
            webhook.total_sent += 1
            webhook.last_sent_at = timezone.now()
            webhook.consecutive_failures = 0
            webhook.last_error = ''
            webhook.save(update_fields=['total_sent', 'last_sent_at', 'consecutive_failures', 'last_error'])
            sent += 1
        except Exception as e:
            webhook.consecutive_failures += 1
            webhook.last_error = str(e)[:500]
            webhook.save(update_fields=['consecutive_failures', 'last_error'])
            logger.error(f"Webhook delivery failed for {webhook.name}: {e}")

            if webhook.consecutive_failures >= 10:
                webhook.is_active = False
                webhook.save(update_fields=['is_active'])
                logger.warning(f"Webhook {webhook.name} auto-disabled after 10 consecutive failures")

    return sent


def _deliver_webhook(webhook, event_type, payload):
    """Deliver a single webhook event with optional HMAC signature."""
    import hashlib
    import hmac

    body = json.dumps({
        'event': event_type,
        'timestamp': timezone.now().isoformat(),
        'source': 'sauron_vision',
        'data': payload,
    }, default=str)

    headers = {
        'Content-Type': 'application/json',
        'X-Sauron-Event': event_type,
    }

    # HMAC signing if secret configured
    if webhook.secret:
        signature = hmac.new(
            webhook.secret.encode(),
            body.encode(),
            hashlib.sha256
        ).hexdigest()
        headers['X-Sauron-Signature'] = f"sha256={signature}"

    response = requests.post(
        webhook.url,
        data=body,
        headers=headers,
        timeout=10,
    )
    response.raise_for_status()
