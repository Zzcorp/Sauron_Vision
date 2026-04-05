"""Email alert channel."""
import logging
from django.core.mail import send_mail
from django.conf import settings

logger = logging.getLogger(__name__)


def send_email_alert(to_email, subject, message):
    """Send an email alert."""
    try:
        send_mail(
            subject=f"Sauron Vision — {subject}",
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[to_email],
            fail_silently=False,
        )
        return True
    except Exception as e:
        logger.error(f"Email send failed to {to_email}: {e}")
        return False


def send_email_to_user(user, subject, message):
    """Send email to a user if they have email notifications enabled."""
    try:
        prefs = user.notification_prefs
        if prefs.email_notifications and user.email:
            return send_email_alert(user.email, subject, message)
    except Exception:
        if user.email:
            return send_email_alert(user.email, subject, message)
    return False
