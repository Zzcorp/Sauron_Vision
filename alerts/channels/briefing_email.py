"""Phase 45 — HTML email channel for the daily Sauron's Mind briefing.

Renders `templates/email/briefing.html` (and a plaintext fallback) and sends
via Django's email backend using `EmailMultiAlternatives` so clients without
HTML support still see a readable version.

Why a separate helper instead of extending `send_email_alert`: the briefing
has structured fields (posture · watchlist · ideas) that benefit from HTML
formatting in a way the generic plain-text helper can't easily express.
Other notification kinds keep using `send_email_alert` unchanged.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


def send_briefing_email(to_email: str, briefing) -> bool:
    """Send a Sauron-themed HTML briefing email. Returns True on success."""
    if not to_email:
        return False
    try:
        subject = (
            f"Sauron — {briefing.posture.upper()} "
            f"({briefing.created_at:%b %d})"
        )
        ctx = {"b": briefing}
        text_body = render_to_string("email/briefing.txt", ctx)
        html_body = render_to_string("email/briefing.html", ctx)

        msg = EmailMultiAlternatives(
            subject=f"Sauron Vision — {subject}",
            body=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[to_email],
        )
        msg.attach_alternative(html_body, "text/html")
        msg.send(fail_silently=False)
        return True
    except Exception as e:
        logger.warning("[briefing_email] send failed for %s: %s", to_email, e)
        return False
