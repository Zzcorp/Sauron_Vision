"""Generic webhook alert channel."""
import requests
import logging

logger = logging.getLogger(__name__)


def send_webhook(url: str, title: str, message: str, extra_data: dict = None):
    """Send an alert to a generic webhook endpoint."""
    payload = {
        "title": title,
        "message": message,
        "source": "sauron_vision",
    }
    if extra_data:
        payload.update(extra_data)

    response = requests.post(url, json=payload)
    if not response.ok:
        raise Exception(f"Webhook error: {response.text}")
