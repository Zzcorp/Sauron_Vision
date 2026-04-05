"""WhatsApp alert channel via Twilio API."""
import os
import logging

logger = logging.getLogger(__name__)

TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM = os.getenv("TWILIO_WHATSAPP_FROM", "")  # whatsapp:+14155238886


def is_configured():
    return bool(TWILIO_SID and TWILIO_TOKEN and TWILIO_FROM)


def send_whatsapp(to_number, message, title=""):
    """Send a WhatsApp message via Twilio."""
    if not is_configured():
        logger.warning("Twilio WhatsApp not configured — set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM")
        return False

    try:
        from twilio.rest import Client
        client = Client(TWILIO_SID, TWILIO_TOKEN)

        # Format WhatsApp number
        to_wa = to_number if to_number.startswith("whatsapp:") else f"whatsapp:{to_number}"
        from_wa = TWILIO_FROM if TWILIO_FROM.startswith("whatsapp:") else f"whatsapp:{TWILIO_FROM}"

        body = f"*{title}*\n\n{message}" if title else message

        msg = client.messages.create(
            body=body[:1600],  # WhatsApp limit
            from_=from_wa,
            to=to_wa,
        )
        logger.info(f"WhatsApp sent to {to_number}: {msg.sid}")
        return True
    except ImportError:
        logger.error("twilio package not installed: pip install twilio")
        return False
    except Exception as e:
        logger.error(f"WhatsApp send failed: {e}")
        return False


def send_whatsapp_to_user(user, title, message):
    """Send WhatsApp to a user based on their notification preferences."""
    try:
        prefs = user.notification_prefs
        if prefs.whatsapp_number:
            return send_whatsapp(prefs.whatsapp_number, message, title)
    except Exception:
        pass
    return False
