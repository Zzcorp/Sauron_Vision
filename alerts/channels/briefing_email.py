"""Phase 45 — HTML email channel for the daily Sauron's Mind briefing.

Renders `templates/email/briefing.html` (and a plaintext fallback) and sends
via Django's email backend using `EmailMultiAlternatives` so clients without
HTML support still see a readable version.

Why a separate helper instead of extending `send_email_alert`: the briefing
has structured fields (posture · watchlist · ideas) that benefit from HTML
formatting in a way the generic plain-text helper can't easily express.
Other notification kinds keep using `send_email_alert` unchanged.

THE SAME CONVENTIONS AS THE WEEKLY LETTER (2026-09-29,
alerts/newsletter_service.py): the links are absolute
(telegram_alert.platform_link; none at all when DOMAIN is unset, never a
relative path an inbox cannot open), the model's **emphasis** is rendered
(briefing_md in the HTML, briefing_plain in the text) instead of printed,
the subject names the brand once ("Sauron Vision — Daily briefing ·
DEFENSIVE (Sep 29)", not "Sauron Vision — Sauron — DEFENSIVE"), and the
model and the cost of the run are shown to staff only.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)

BRIEFING_PATH = "/briefing/"
SETTINGS_PATH = "/notifications/settings/"


def briefing_subject(briefing) -> str:
    return (f"Sauron Vision — Daily briefing · {briefing.posture.upper()} "
            f"({briefing.created_at:%b %d})")


def send_briefing_email(to_email: str, briefing, *, staff: bool = False) -> bool:
    """Send a Sauron-themed HTML briefing email. Returns True on success.

    `staff`: the recipient is staff, and the footer may say which model
    wrote the briefing and what it cost."""
    if not to_email:
        return False
    try:
        from alerts.channels.telegram_alert import platform_link
        ctx = {
            "b": briefing,
            "staff": bool(staff),
            "briefing_url": platform_link(BRIEFING_PATH),
            "settings_url": platform_link(SETTINGS_PATH),
        }
        text_body = render_to_string("email/briefing.txt", ctx)
        html_body = render_to_string("email/briefing.html", ctx)

        msg = EmailMultiAlternatives(
            subject=briefing_subject(briefing),
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
