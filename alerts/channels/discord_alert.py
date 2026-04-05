"""Discord webhook alert channel."""
import os
import requests
import logging

logger = logging.getLogger(__name__)

WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")


def send_discord(title: str, message: str):
    """Send a message via Discord webhook."""
    if not WEBHOOK_URL:
        logger.warning("Discord webhook not configured — skipping alert")
        return

    payload = {
        "embeds": [{
            "title": f"🔴 {title}",
            "description": message,
            "color": 15158332,  # Red
        }]
    }

    response = requests.post(WEBHOOK_URL, json=payload)
    if not response.ok:
        raise Exception(f"Discord webhook error: {response.text}")
