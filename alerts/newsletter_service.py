"""The weekly letter: who receives it, what it looks like, how it is sent.

THE REDESIGN (2026-09-29). Until today an edition went out inside the
admin's POST: one post to the platform group, then the RAW MARKDOWN by
plain-text mail to every active user with an address, whatever their
settings said, fail_silently and a bare except around it, "sent" at zero
deliveries. The operator's decisions, built here:

  * ONE WEEKLY LETTER. The Saturday weekly review is the edition
    (weekly_draft, called by ai_agents.tasks.generate_weekly_review): READY
    at once, scheduled for the next Sunday 08:00 Europe/Paris
    (next_send_time), and the staff are told (announce_draft) when it goes
    out and where to read, edit or cancel it. alerts.tasks.
    send_due_newsletters sends it then, behind the newsletter_send switch.
  * THE AUDIENCE (audience): active, an address, "Weekly newsletter" on,
    and the ONE channel of the user's profile: "none" receives nothing,
    "telegram" gets it in the user's own chat, "email" and "discord" (which
    has no newsletter path) by email. Quiet hours do not apply: this is a
    scheduled weekly letter at a fixed, civil hour, not an alert, and a
    window that swallowed it would lose the week's edition, not delay it.
  * A REAL EMAIL (build_email): text and HTML, the unsubscribe link in the
    footer and in List-Unsubscribe (one click, RFC 8058), absolute links
    only (telegram_alert.platform_link: none at all without DOMAIN).
  * A RELIABLE SEND (send_newsletter): the edition is claimed under
    select_for_update and a lease, every recipient is a NewsletterDelivery
    row, email goes in batches of EMAIL_BATCH over one connection, a
    failure is recorded against its recipient and retried by the next pass
    (up to NewsletterDelivery.MAX_ATTEMPTS), and a delivered row is never
    sent again. "sent" when at least one delivery went out, "failed" when
    none did, and the failures are logged at WARNING with their count.
"""
from __future__ import annotations

import logging
import os
import re
from collections import namedtuple
from datetime import datetime, time, timedelta
from datetime import timezone as dt_tz
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth.models import User
from django.utils import timezone

logger = logging.getLogger(__name__)

BRAND = "Sauron Vision"
#: The letter's civil hour: Sunday 08:00 in Paris, DST included.
PARIS = ZoneInfo("Europe/Paris")
SEND_WEEKDAY = 6            # Sunday
SEND_HOUR = 8
#: Emails per connection.
EMAIL_BATCH = 50
#: A "sending" row whose lease is older than this was abandoned.
SEND_LEASE_MINUTES = 30
UNSUBSCRIBE_SALT = "newsletter-unsubscribe"
ADMIN_PATH = "/admin-dashboard/newsletters/"
SETTINGS_PATH = "/notifications/settings/"
ARCHIVE_PATH = "/newsletters/"
READ_WORDS = "Read it on the platform"
#: The statuses an edition can be sent from by an explicit "Send now";
#: the scheduled pass sends READY and APPROVED only.
SENDABLE = ("draft", "ai_generated", "approved", "cancelled", "failed")
#: What the email backend is when EMAIL_HOST is empty (config/settings.py):
#: it prints the message and reports it sent. For a letter that would be
#: a delivery recorded "sent" that reached nobody.
CONSOLE_BACKEND = "django.core.mail.backends.console.EmailBackend"

EDITION_WORDS = {"weekly": "weekly letter", "adhoc": "special edition",
                 "monthly": "monthly letter"}


# ── names ─────────────────────────────────────────────────────────────────

_BRAND_LEAD = re.compile(r"^\s*sauron\s+vision\b[\s:·—–-]*", re.I)


def plain_title(title) -> str:
    """The edition's title without a leading brand ("Sauron Vision Weekly
    Review — …" is "Weekly Review — …"): every place that shows it adds
    the brand once."""
    text = " ".join(str(title or "").split())
    rest = _BRAND_LEAD.sub("", text).strip()
    return rest or text or "Newsletter"


def email_subject(newsletter) -> str:
    """"Sauron Vision — Weekly Review · 26 September 2026": the brand once."""
    return f"{BRAND} — {plain_title(newsletter.title)}"


def telegram_title(newsletter) -> str:
    return f"{BRAND} · {plain_title(newsletter.title)}"


def edition_words(newsletter) -> str:
    return EDITION_WORDS.get(newsletter.frequency, "letter")


def date_words(moment, *, weekday=False) -> str:
    """"4 October 2026", or "Sunday 4 October 2026" (Paris date)."""
    if moment is None:
        return ""
    local = moment.astimezone(PARIS) if moment.tzinfo else moment
    words = "%d %s" % (local.day, local.strftime("%B %Y"))
    return f"{local.strftime('%A')} {words}" if weekday else words


def week_title(now) -> str:
    """"Weekly Review · week of 28 September 2026": the Monday of the
    trading week the Saturday review looks back on (the letter's date line
    says when it went out)."""
    local = now.astimezone(PARIS) if now.tzinfo else now
    monday = local.date() - timedelta(days=local.weekday())
    return "Weekly Review · week of %d %s" % (monday.day,
                                              monday.strftime("%B %Y"))


def paris_words(moment) -> str:
    """"Sunday 4 October 2026 at 08:00 Paris time"; "" for None."""
    if moment is None:
        return ""
    local = moment.astimezone(PARIS)
    return "%s %d %s at %s Paris time" % (
        local.strftime("%A"), local.day, local.strftime("%B %Y"),
        local.strftime("%H:%M"))


# ── the schedule ──────────────────────────────────────────────────────────

def next_send_time(after=None) -> datetime:
    """The first Sunday 08:00 Europe/Paris strictly after `after` (now by
    default), in UTC. Built on the Paris calendar with zoneinfo, so it is
    06:00 UTC in summer and 07:00 UTC in winter, the weekend the clocks
    change included (a Saturday review plus "one day" in UTC would be an
    hour off on those two Sundays)."""
    after = after or timezone.now()
    if after.tzinfo is None:
        after = after.replace(tzinfo=dt_tz.utc)
    local = after.astimezone(PARIS)
    day = local.date() + timedelta(days=(SEND_WEEKDAY - local.weekday()) % 7)
    candidate = datetime.combine(day, time(SEND_HOUR, 0), tzinfo=PARIS)
    if candidate <= local:
        candidate = datetime.combine(day + timedelta(days=7),
                                     time(SEND_HOUR, 0), tzinfo=PARIS)
    return candidate.astimezone(dt_tz.utc)


def parse_paris_input(value):
    """A <input type="datetime-local"> value ("2026-10-04T08:00"), read as
    Paris time, in UTC; None when it is not one."""
    try:
        naive = datetime.fromisoformat(str(value or "").strip())
    except ValueError:
        return None
    if naive.tzinfo is not None:
        return naive.astimezone(dt_tz.utc)
    return naive.replace(tzinfo=PARIS).astimezone(dt_tz.utc)


def paris_input(moment) -> str:
    """The value a datetime-local input shows for `moment` (Paris)."""
    if moment is None:
        return ""
    return moment.astimezone(PARIS).strftime("%Y-%m-%dT%H:%M")


# ── the prose ─────────────────────────────────────────────────────────────

_MD_LINK = re.compile(r"\[([^\]\n]+)\]\(((?:[^()\s]|\([^()\s]*\))+)\)")


def letter_prose(markdown) -> str:
    """The edition's markdown as it is sent. The weekly review ends on the
    ```json calls block the calibration grades: it comes out, with the one
    line heading it (monday_plan.split_plan, the same reading). Then the
    platform's rule for model text (monday_plan.readable): a table becomes
    a list a phone can read, a rule goes, a bold line alone becomes its
    heading, and a link to another site is said as "label (address)",
    never followed. A same-site link is made absolute, or said as its
    label when the platform does not name its host."""
    from ai_agents import monday_plan as mp
    from alerts.channels.telegram_alert import platform_link
    prose, _calls = mp.split_plan(str(markdown or ""))
    text = mp.readable(prose)

    def same_site(m):
        label, url = m.group(1), m.group(2)
        link = platform_link(url) if url.startswith("/") else ""
        return f"[{label}]({link})" if link else label

    return _MD_LINK.sub(same_site, text)


# ── the audience ──────────────────────────────────────────────────────────

#: One person the edition is for: their channel ("email" or "telegram"),
#: where it goes (the address or the chat id), and, when it cannot go,
#: why ("" when it can).
Recipient = namedtuple("Recipient", ["user", "channel", "address", "skip"])


def audience(newsletter=None) -> list:
    """Everyone the edition is for, one Recipient per person.

    Active, a non-empty email, not an investor login (an investor sees
    one book through the investor panel, percentages only: the weekly
    review speaks about the whole platform's positions and money), and
    UserNotificationPrefs.receive_weekly_newsletter on — prefs created
    with the model's defaults for a user who has none, as the settings
    page does. Then the profile's one channel: "none" receives nothing,
    "telegram" the user's own chat (a chat several users share is sent
    once, like the digests), "email" and "discord" by email. A user with
    no TraderProfile has never chosen: the model's default applies.
    A Telegram user without a chat, or a channel this edition does not
    use (its send_email / send_telegram), is listed with the reason: the
    ledger records it "skipped", so the admin page can say so.
    Quiet hours do not apply (the module docstring says why).
    """
    from alerts.models import UserNotificationPrefs
    from portfolio.trader_profile import TraderProfile

    users = (User.objects.filter(is_active=True)
             .exclude(email__isnull=True).exclude(email__exact="")
             .filter(investor_access__isnull=True).order_by("pk"))
    have = set(UserNotificationPrefs.objects.filter(user__in=users)
               .values_list("user_id", flat=True))
    missing = [UserNotificationPrefs(user_id=pk)
               for pk in users.values_list("pk", flat=True)
               if pk not in have]
    if missing:
        UserNotificationPrefs.objects.bulk_create(missing,
                                                  ignore_conflicts=True)
    prefs = {p.user_id: p for p in
             UserNotificationPrefs.objects.filter(user__in=users)}
    chosen = dict(TraderProfile.objects.filter(user__in=users)
                  .values_list("user_id", "notify_channel"))
    default = TraderProfile._meta.get_field("notify_channel").default

    by_email = getattr(newsletter, "send_email", True)
    by_telegram = getattr(newsletter, "send_telegram", True)
    out, chats = [], {}
    for user in users:
        email = (user.email or "").strip()
        p = prefs.get(user.pk)
        if not email or p is None or not p.receive_weekly_newsletter:
            continue
        channel = chosen.get(user.pk) or default
        if channel == "none":
            continue
        if channel == "telegram":
            chat = str(p.telegram_chat_id or "").strip()
            if not by_telegram:
                skip = "this edition does not go out on Telegram"
            elif not chat:
                skip = ("Telegram is this user's channel and no Telegram "
                        "chat id is set")
            elif chat in chats:
                skip = (f"shares a Telegram chat with {chats[chat]}: sent "
                        f"there once")
            else:
                chats[chat] = user.username
                skip = ""
            out.append(Recipient(user, "telegram", chat, skip))
        else:
            skip = "" if by_email else "this edition does not go out by email"
            out.append(Recipient(user, "email", email, skip))
    return out


def audience_counts(recipients) -> dict:
    """{"people", "email", "telegram", "skipped"} of an audience()."""
    reach = [r for r in recipients if not r.skip]
    return {
        "people": len(reach),
        "email": sum(1 for r in reach if r.channel == "email"),
        "telegram": sum(1 for r in reach if r.channel == "telegram"),
        "skipped": len(recipients) - len(reach),
    }


def reach_words(counts) -> str:
    """"will reach 12 people: 9 by email, 3 by Telegram (1 skipped)"."""
    people = counts["people"]
    text = (f"will reach {people} {'person' if people == 1 else 'people'}: "
            f"{counts['email']} by email, {counts['telegram']} by Telegram")
    if counts.get("skipped"):
        text += f" ({counts['skipped']} skipped)"
    return text


# ── unsubscribe ───────────────────────────────────────────────────────────

def unsubscribe_token(user) -> str:
    """A signed token carrying the user id (salt "newsletter-unsubscribe",
    no expiry: a letter read a year later still unsubscribes)."""
    from django.core import signing
    return signing.dumps({"u": user.pk}, salt=UNSUBSCRIBE_SALT, compress=True)


def user_for_token(token):
    """The user a token names, or None for anything else (bad signature,
    malformed, a user since deleted)."""
    from django.core import signing
    try:
        data = signing.loads(str(token or ""), salt=UNSUBSCRIBE_SALT)
    except (signing.BadSignature, ValueError, TypeError):
        return None
    pk = data.get("u") if isinstance(data, dict) else None
    if not isinstance(pk, int):
        return None
    return User.objects.filter(pk=pk).first()


def unsubscribe_path(user) -> str:
    return f"/newsletter/unsubscribe/{unsubscribe_token(user)}/"


# ── the email ─────────────────────────────────────────────────────────────

def email_context(newsletter, user=None, *, web=False) -> dict:
    """What templates/email/newsletter.{html,txt} read. `web`: the copy on
    the platform (the archive, the admin preview without a recipient): no
    personal unsubscribe link. Every link absolute or absent."""
    from alerts.channels.telegram_alert import platform_link
    from core.templatetags.sauron_tags import newsletter_md, newsletter_plain
    prose = letter_prose(newsletter.content_markdown)
    moment = newsletter.sent_at or newsletter.scheduled_for or timezone.now()
    unsubscribe = ""
    if user is not None and not web:
        unsubscribe = platform_link(unsubscribe_path(user))
    body_text = newsletter_plain(prose)
    return {
        "brand": BRAND,
        "subject": email_subject(newsletter),
        "title": plain_title(newsletter.title),
        "edition": edition_words(newsletter),
        "date_words": date_words(moment, weekday=True),
        "preheader": _preheader(body_text),
        "body_html": newsletter_md(prose),
        "body_text": body_text,
        "archive_url": (platform_link(newsletter.archive_path)
                        if newsletter.pk else ""),
        "settings_url": platform_link(SETTINGS_PATH),
        "home_url": platform_link("/"),
        "unsubscribe_url": unsubscribe,
        "web": web,
        "recipient": user,
    }


def _preheader(body_text, limit=140) -> str:
    """The inbox's grey line under the subject: the letter's first line of
    prose (a heading in capitals is not one), cut at a word."""
    for line in str(body_text or "").splitlines():
        line = " ".join(line.split()).lstrip("• ")
        if len(line) < 20 or line.upper() == line:
            continue
        if len(line) <= limit:
            return line
        return line[:limit].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"
    return ""


def render_email(newsletter, user=None, *, web=False) -> tuple:
    """(text, html) of the edition as `user` receives it."""
    from django.template.loader import render_to_string
    ctx = email_context(newsletter, user, web=web)
    return (render_to_string("email/newsletter.txt", ctx),
            render_to_string("email/newsletter.html", ctx))


def build_email(newsletter, user, *, connection=None, subject_prefix=""):
    """One EmailMultiAlternatives for one recipient: the unsubscribe link
    is personal, so a message is never shared between two people. From
    settings.DEFAULT_FROM_EMAIL; List-Unsubscribe (and its RFC 8058 one-
    click twin) only when the link can be absolute."""
    from django.core.mail import EmailMultiAlternatives
    from alerts.channels.telegram_alert import platform_link
    text, html = render_email(newsletter, user)
    headers = {}
    link = platform_link(unsubscribe_path(user))
    if link:
        headers["List-Unsubscribe"] = f"<{link}>"
        headers["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg = EmailMultiAlternatives(
        subject=subject_prefix + email_subject(newsletter),
        body=text,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email.strip()],
        headers=headers,
        connection=connection,
    )
    msg.attach_alternative(html, "text/html")
    return msg


def email_unconfigured() -> str:
    """Why email cannot go out on this server, or ""."""
    if settings.EMAIL_BACKEND == CONSOLE_BACKEND:
        return ("no mail server is configured (EMAIL_HOST is empty): the "
                "console backend would only print the message")
    return ""


def send_test(newsletter, user) -> tuple:
    """(ok, words): the edition to `user`'s own address only, marked as a
    test in the subject. No ledger row, no status change, no bell."""
    from core.secret_scrub import scrub
    email = (getattr(user, "email", "") or "").strip()
    if not email:
        return False, ("Your account has no email address: set one on your "
                       "profile to receive a test.")
    why = email_unconfigured()
    if why:
        return False, f"The test was not sent: {why}."
    try:
        sent = build_email(newsletter, user,
                           subject_prefix="[Test] ").send(fail_silently=False)
    except Exception as e:  # noqa: BLE001 — said on the page, and logged
        logger.warning("[newsletter] the test of %s to %s failed: %s",
                       newsletter.pk, email, scrub(e)[:300])
        return False, f"The test was not sent: {scrub(e)[:300]}"
    if not sent:
        return False, "The mail server did not accept the test."
    return True, f"A test was sent to {email}."


# ── the send ──────────────────────────────────────────────────────────────

def published():
    """The editions a reader may open: gone out ("sent", or still
    "sending" its retries after the first delivery)."""
    from alerts.models import Newsletter
    return Newsletter.objects.filter(status__in=("sent", "sending"),
                                     sent_at__isnull=False)


def claim(newsletter_id, *, scheduled=False) -> tuple:
    """(the edition, "") when this worker may send it now, else (None, why).

    Under select_for_update, so two workers cannot both take it: the
    first sets "sending" and the lease, the second finds a fresh lease and
    stops. A "sending" row whose lease was released (a retry is due) or
    is older than SEND_LEASE_MINUTES (its worker died) is resumed.
    `scheduled` (the send_due pass): READY or APPROVED only, and only once
    `scheduled_for` has come (a queued task must not send an edition
    rescheduled or cancelled since). Otherwise (Send now) any SENDABLE
    status; a FAILED edition gets a fresh round of attempts.
    """
    from django.db import transaction

    from alerts.models import Newsletter, NewsletterDelivery
    now = timezone.now()
    with transaction.atomic():
        nl = (Newsletter.objects.select_for_update()
              .filter(pk=newsletter_id).first())
        if nl is None:
            return None, "no such edition"
        if nl.status == "sending":
            lease = nl.send_started_at
            if lease and lease > now - timedelta(minutes=SEND_LEASE_MINUTES):
                return None, "another worker is sending it"
        elif scheduled:
            if nl.status not in ("ai_generated", "approved"):
                return None, f"its status is {nl.status}"
            if nl.scheduled_for is None or nl.scheduled_for > now:
                return None, "it is not due"
        elif nl.status not in SENDABLE:
            return None, f"its status is {nl.status}"
        if nl.status != "sending" and not (nl.content_markdown or "").strip():
            if scheduled:
                nl.status = "failed"
                nl.last_error = "Nothing was sent: the edition is empty."
                nl.save(update_fields=["status", "last_error", "updated_at"])
            return None, "it is empty"
        if nl.status == "failed":
            NewsletterDelivery.objects.filter(
                newsletter=nl, status="failed").update(attempts=0)
        nl.status = "sending"
        nl.send_started_at = now
        nl.last_error = ""
        nl.save(update_fields=["status", "send_started_at", "last_error",
                               "updated_at"])
    return nl, ""


def send_newsletter(newsletter, *, scheduled=False) -> dict:
    """Send one edition: claim it, build its ledger, deliver, conclude.

    {"status", "recipients", "email", "telegram", "failed", "skipped",
    "pending"} — "recipients" is the deliveries that went out, all
    channels, all runs. Never raises for a recipient: each failure is
    recorded against its row. An unexpected error stops the run and
    marks the edition "failed" with the reason (Send now resumes it; a
    delivered row is never sent again), then re-raises for the worker's
    log.
    """
    from core.secret_scrub import scrub
    nl, why = claim(newsletter.pk, scheduled=scheduled)
    if nl is None:
        logger.info("[newsletter] %s not sent: %s", newsletter.pk, why)
        return {"status": "skipped", "reason": why, "recipients": 0}
    try:
        return _run(nl)
    except Exception as e:
        from alerts.models import Newsletter
        words = scrub(e)[:300]
        logger.exception("[newsletter] the send of %s stopped: %s", nl.pk,
                         words)
        Newsletter.objects.filter(pk=nl.pk, status="sending").update(
            status="failed", send_started_at=None,
            last_error=(f"The send stopped: {words}. Send now resumes it; "
                        f"no one who received it gets it twice.")[:500])
        raise


def _run(nl) -> dict:
    from alerts.channels.telegram_alert import markdown_lines
    from alerts.models import NewsletterDelivery

    recipients = audience(nl)
    by_user = {r.user.pk: r for r in recipients}
    ledger = NewsletterDelivery.objects.filter(newsletter=nl)
    known = set(ledger.values_list("user_id", flat=True))
    NewsletterDelivery.objects.bulk_create(
        [NewsletterDelivery(newsletter=nl, user=r.user, channel=r.channel,
                            status="skipped" if r.skip else "pending",
                            error=r.skip[:500])
         for r in recipients if r.user.pk not in known],
        ignore_conflicts=True)

    todo = []
    retry = (ledger.filter(status__in=("pending", "failed"),
                           attempts__lt=NewsletterDelivery.MAX_ATTEMPTS)
             .select_related("user"))
    for d in retry:
        r = by_user.get(d.user_id)
        if r is None:
            d.status, d.error = "skipped", ("no longer in the audience "
                                            "(unsubscribed, deactivated or "
                                            "no address) before this attempt")
            d.save(update_fields=["status", "error"])
            continue
        if r.skip:
            d.status, d.error = "skipped", r.skip[:500]
            d.save(update_fields=["status", "error"])
            continue
        if d.channel != r.channel:
            # The user changed channel between two attempts: this row
            # follows (one row per user: nobody receives it twice).
            d.channel = r.channel
            d.save(update_fields=["channel"])
        todo.append((d, r))

    sent_users = []
    emails = [(d, r) for d, r in todo if d.channel == "email"]
    for start in range(0, len(emails), EMAIL_BATCH):
        sent_users += _send_email_batch(nl, emails[start:start + EMAIL_BATCH])
        _heartbeat(nl, sent_users)
    telegram = [(d, r) for d, r in todo if d.channel == "telegram"]
    if telegram:
        lines = markdown_lines(letter_prose(nl.content_markdown))
        for d, r in telegram:
            if _send_telegram(nl, d, r.address, lines):
                sent_users.append((d.user, "telegram"))
        _heartbeat(nl, sent_users)

    _bell(nl, sent_users)
    return _conclude(nl, attempted=len(todo), sent_now=len(sent_users))


def _record(d, ok, error=""):
    from core.secret_scrub import scrub
    d.status = "sent" if ok else "failed"
    d.error = "" if ok else scrub(error)[:500]
    if ok:
        d.sent_at = timezone.now()
    d.save(update_fields=["status", "error", "attempts", "sent_at"])


def _send_email_batch(nl, batch) -> list:
    """One connection for up to EMAIL_BATCH messages, each sent on its own
    over it so every outcome is known: a message the server refuses is
    recorded failed and the others go on; a connection that breaks is
    replaced for the rest of the batch (no message is sent twice: the
    ones before the break were recorded sent). A server that cannot be
    reached fails the rest of the batch with its reason."""
    from django.core.mail import get_connection
    why = email_unconfigured()
    out, connection = [], None
    for i, (d, r) in enumerate(batch):
        d.attempts += 1
        if why:
            _record(d, False, why)
            continue
        try:
            msg = build_email(nl, d.user)
        except Exception as e:  # noqa: BLE001 — recorded against the row
            _record(d, False, f"the email could not be built: {e}")
            continue
        if connection is None:
            try:
                connection = get_connection(fail_silently=False)
                connection.open()
            except Exception as e:  # noqa: BLE001
                connection = None
                reason = f"the mail server could not be reached: {e}"
                _record(d, False, reason)
                for d2, _r2 in batch[i + 1:]:
                    d2.attempts += 1
                    _record(d2, False, reason)
                break
        msg.connection = connection
        try:
            ok = connection.send_messages([msg]) == 1
            _record(d, ok, "" if ok else "the mail server did not accept it")
        except Exception as e:  # noqa: BLE001 — one refusal, not the batch
            _record(d, False, str(e))
            try:
                connection.close()
            except Exception:  # noqa: BLE001
                pass
            connection = None
            continue
        if ok:
            out.append((d.user, "email"))
    if connection is not None:
        try:
            connection.close()
        except Exception:  # noqa: BLE001
            pass
    return out


def _send_telegram(nl, d, chat, lines) -> bool:
    """The edition to the user's own chat, in the house style: HTML, every
    field escaped, the newsletter's mark, the markdown as lines, and a
    button to the archive copy (or its path as the last line when the
    platform names no host). send_to_chat never raises and logs a refusal
    at WARNING with Telegram's own words."""
    from alerts.channels.telegram_alert import (MARKS, button_markup,
                                                page_line, send_to_chat)
    d.attempts += 1
    if not os.getenv("TELEGRAM_BOT_TOKEN", ""):
        _record(d, False, "TELEGRAM_BOT_TOKEN is not set")
        return False
    button = (READ_WORDS, nl.archive_path)
    told = list(lines) or [plain_title(nl.title)]
    if button_markup(button) is None:
        told.append(page_line(nl.archive_path, READ_WORDS))
    ok = send_to_chat(chat, telegram_title(nl), lines=told,
                      mark=MARKS["newsletter"], button=button)
    _record(d, ok, "" if ok else ("Telegram refused the message (the "
                                  "WARNING line before this says why)"))
    return ok


def _heartbeat(nl, sent_users):
    """Renew the lease after a batch; stamp sent_at at the first delivery
    (the edition is then readable in the archive, retries or not)."""
    from alerts.models import Newsletter
    now = timezone.now()
    Newsletter.objects.filter(pk=nl.pk, status="sending").update(
        send_started_at=now)
    if sent_users:
        Newsletter.objects.filter(pk=nl.pk, sent_at__isnull=True).update(
            sent_at=now)


def _bell(nl, sent_users):
    """A bell row ("newsletter") for each person reached this run, linking
    to the archive copy. Best-effort: the letter went out either way."""
    if not sent_users:
        return 0
    from alerts.models import Notification, _push_live
    url = Notification.safe_url(nl.archive_path)
    where = {"email": "by email", "telegram": "to your Telegram chat"}
    rows = [Notification(
        user=user, notification_type="newsletter",
        title=plain_title(nl.title)[:200],
        body=(f"The {edition_words(nl)} from {BRAND} was sent to you "
              f"{where.get(channel, '')}. Every edition stays in the "
              f"archive."),
        url=url) for user, channel in sent_users]
    try:
        Notification.objects.bulk_create(rows)
    except Exception:  # noqa: BLE001
        logger.warning("[newsletter] %s: the bell rows could not be "
                       "written", nl.pk, exc_info=True)
        return 0
    for row in rows:
        _push_live(row)
    return len(rows)


def ledger_counts(newsletter_ids) -> dict:
    """{id: {"email", "telegram", "failed", "skipped", "pending"}} from the
    ledger: "email"/"telegram" count the deliveries SENT on each."""
    from django.db.models import Count

    from alerts.models import NewsletterDelivery
    out = {i: {"email": 0, "telegram": 0, "failed": 0, "skipped": 0,
               "pending": 0} for i in newsletter_ids}
    rows = (NewsletterDelivery.objects
            .filter(newsletter_id__in=list(newsletter_ids))
            .values("newsletter_id", "channel", "status")
            .annotate(n=Count("id")))
    for row in rows:
        counts = out[row["newsletter_id"]]
        if row["status"] == "sent":
            counts[row["channel"]] += row["n"]
        else:
            counts[row["status"]] += row["n"]
    return out


def delivery_words(counts) -> str:
    """"9 sent by email, 3 by Telegram, 1 failed, 2 skipped"."""
    text = (f"{counts['email']} sent by email, {counts['telegram']} by "
            f"Telegram, {counts['failed']} failed, {counts['skipped']} "
            f"skipped")
    if counts.get("pending"):
        text += f", {counts['pending']} waiting"
    return text


def _conclude(nl, *, attempted, sent_now) -> dict:
    """The run's verdict on the edition. Retries left: it stays "sending"
    with the lease released, for the next send_due pass. Otherwise "sent"
    when at least one delivery ever went out, "failed" when none did."""
    from alerts.models import Newsletter, NewsletterDelivery
    counts = ledger_counts([nl.pk])[nl.pk]
    sent = counts["email"] + counts["telegram"]
    retry = NewsletterDelivery.objects.filter(
        newsletter=nl, status__in=("pending", "failed"),
        attempts__lt=NewsletterDelivery.MAX_ATTEMPTS).count()
    now = timezone.now()
    fields = {"send_started_at": None, "recipients_count": sent}
    if retry:
        status = "sending"
        fields["last_error"] = (
            f"{retry} deliver{'y' if retry == 1 else 'ies'} failed and will "
            f"be tried again by the next pass (at most "
            f"{NewsletterDelivery.MAX_ATTEMPTS} attempts each).")
    elif sent:
        status = "sent"
        fields["last_error"] = (
            f"{counts['failed']} could not be delivered after "
            f"{NewsletterDelivery.MAX_ATTEMPTS} attempts."
            if counts["failed"] else "")
    else:
        status = "failed"
        total = counts["failed"] + counts["skipped"] + counts["pending"]
        fields["last_error"] = (
            "Nothing was sent: nobody receives it (no active user with an "
            "email has the weekly newsletter on, on a channel that has a "
            "newsletter)." if not total else
            f"Nothing was sent: {counts['failed']} failed, "
            f"{counts['skipped']} skipped.")
    fields["status"] = status
    Newsletter.objects.filter(pk=nl.pk).update(updated_at=now, **fields)
    if sent:
        # The first delivery's time, when the heartbeat already stamped it.
        Newsletter.objects.filter(pk=nl.pk, sent_at__isnull=True).update(
            sent_at=now)

    failed_now = counts["failed"]
    if failed_now:
        logger.warning("[newsletter] %s: %d deliver%s failed (%s)", nl.pk,
                       failed_now, "y" if failed_now == 1 else "ies",
                       delivery_words(counts))
    if status == "failed":
        logger.warning("[newsletter] %s failed: %s", nl.pk,
                       fields["last_error"])
    logger.info("[newsletter] %s: %s; %d attempted this run, %d sent",
                nl.pk, delivery_words(counts), attempted, sent_now)
    return {"status": status, "recipients": sent, **counts}


def due_newsletter_ids(now=None) -> list:
    """Editions the scheduled pass should send now: READY or APPROVED whose
    time has come, and "sending" ones whose lease was released (retries
    due) or abandoned (older than SEND_LEASE_MINUTES)."""
    from django.db.models import Q

    from alerts.models import Newsletter
    now = now or timezone.now()
    stale = now - timedelta(minutes=SEND_LEASE_MINUTES)
    due = Newsletter.objects.filter(
        Q(status__in=("ai_generated", "approved"), scheduled_for__lte=now)
        | Q(status="sending", send_started_at__isnull=True)
        | Q(status="sending", send_started_at__lt=stale))
    return list(due.order_by("scheduled_for", "pk").values_list("pk",
                                                                  flat=True))


# ── the weekly draft ──────────────────────────────────────────────────────

def weekly_draft(review_text, *, now=None, prompt="") -> tuple:
    """The Saturday review as the week's edition: (the row, the notice).

    READY with scheduled_for = the next Sunday 08:00 Paris; any older
    weekly edition still waiting to go out is cancelled (two letters on
    one Sunday would be one too many); the staff are told at once
    (announce_draft). An empty review is recorded "failed", scheduled
    for nothing, and the staff are told that instead.
    """
    from alerts.models import Newsletter
    now = now or timezone.now()
    title = week_title(now)
    text = str(review_text or "")
    if not text.strip():
        nl = Newsletter.objects.create(
            title=title, frequency="weekly", status="failed",
            content_markdown="", ai_prompt=prompt,
            last_error="The weekly review came back empty: nothing is "
                       "scheduled this week.")
        logger.warning("[newsletter] the weekly review was empty: edition "
                       "%s recorded failed, nothing scheduled", nl.pk)
        return nl, announce_draft(nl)
    when = next_send_time(now)
    superseded = Newsletter.objects.filter(
        frequency="weekly", status__in=("ai_generated", "approved"),
        scheduled_for__isnull=False)
    nl = Newsletter.objects.create(
        title=title, frequency="weekly", status="ai_generated",
        content_markdown=text, ai_prompt=prompt, scheduled_for=when)
    superseded.exclude(pk=nl.pk).update(
        status="cancelled", scheduled_for=None,
        last_error=f"Superseded by the edition of {date_words(now)}.")
    return nl, announce_draft(nl)


def announce_draft(nl) -> dict:
    """Tell the staff the week's edition is ready (or that it failed): a
    bell row ("newsletter") for every active staff user, and one house-
    style message to each staff Telegram chat (bot_program.morgul.
    recipients, the chats the Eye and the Monday plan use; the platform
    chat when none is configured). {"bell", "telegram"}."""
    from alerts.channels.telegram_alert import (MARKS, page_line,
                                                send_telegram, send_to_chat)
    from alerts.models import Notification, _push_live
    name = plain_title(nl.title)
    if nl.status == "failed":
        title = "Weekly letter not ready"
        lines = [f"Edition: {name}", nl.last_error or "It failed.",
                 page_line(ADMIN_PATH, "Newsletters")]
        body = f"{name}: {nl.last_error}"
    else:
        counts = audience_counts(audience(nl))
        when = paris_words(nl.scheduled_for)
        title = "Weekly letter ready · goes out " + (
            nl.scheduled_for.astimezone(PARIS).strftime("%A %H:%M")
            + " Paris time" if nl.scheduled_for else "when sent")
        lines = [f"Edition: {name}",
                 f"Goes out: {when}" if when else "Goes out: when sent",
                 "Audience: " + reach_words(counts),
                 page_line(ADMIN_PATH, "Read, edit or cancel it")]
        body = (f"{name} goes out {when or 'when sent'} unless cancelled. "
                f"It {reach_words(counts)}. Read, edit or cancel it on the "
                f"Newsletters page.")
    url = Notification.safe_url(ADMIN_PATH)
    staff = list(User.objects.filter(is_staff=True, is_active=True))
    rows = [Notification(user=u, notification_type="newsletter",
                         title=title[:200], body=body, url=url)
            for u in staff]
    bell = 0
    try:
        Notification.objects.bulk_create(rows)
        for row in rows:
            _push_live(row)
        bell = len(rows)
    except Exception:  # noqa: BLE001 — Telegram still goes
        logger.warning("[newsletter] the staff bell rows could not be "
                       "written", exc_info=True)

    told = {"chats": 0, "sent": 0}
    try:
        from bot_program.morgul import recipients
        chats = []
        for user in recipients():
            prefs = getattr(user, "notification_prefs", None)
            chat = str(getattr(prefs, "telegram_chat_id", "") or "").strip()
            if chat and chat not in chats:
                chats.append(chat)
        mark = MARKS["newsletter"]
        button = ("Read, edit or cancel", ADMIN_PATH)
        if chats:
            for chat in chats:
                told["chats"] += 1
                if send_to_chat(chat, title, lines=lines, mark=mark,
                                button=button):
                    told["sent"] += 1
        elif os.getenv("TELEGRAM_CHAT_ID", ""):
            told["chats"] = 1
            told["sent"] = int(send_telegram(title, lines=lines, mark=mark,
                                             button=button))
    except Exception:  # noqa: BLE001 — the bell already has it
        logger.warning("[newsletter] the staff Telegram message could not "
                       "be sent", exc_info=True)
    return {"bell": bell, "telegram": told}


# ── an ad-hoc edition, written by the model ───────────────────────────────

class _NewsletterWriterAgent:
    """Concrete BaseAgent for newsletter prose — defined lazily so the module
    imports without pulling the ai_agents app at import time."""

    def __new__(cls):
        from ai_agents.base_agent import BaseAgent

        class NewsletterWriterAgent(BaseAgent):
            agent_name = "newsletter_writer"
            default_tier = "fast"  # short marketing prose — haiku tier

            def get_system_prompt(self) -> str:
                return (
                    "You are the newsletter writer for the Sauron Vision "
                    "trading-intelligence platform. Write professional, "
                    "concise, data-driven markdown in English. Never invent "
                    "numbers — use only the figures provided in the context."
                )

            def build_context(self, **kwargs) -> str:
                return kwargs["prompt"]

            def parse_response(self, raw_response: str) -> dict:
                return {"markdown": raw_response.strip()}

        return NewsletterWriterAgent()


def generate_newsletter_with_ai(newsletter) -> bool:
    """Write an ad-hoc edition's content with the model (run by
    alerts.tasks.generate_newsletter_task, never inside a request).

    The row is "generating" while this runs. Success: the content, READY,
    no schedule (it waits for Send now or a reschedule). Failure: "failed"
    with the reason in last_error, said on the admin page. Either is
    written only while the row is still "generating": an edition
    cancelled or deleted meanwhile stays as the operator left it."""
    from django.db.models import Avg

    from alerts.models import Newsletter
    from core.secret_scrub import scrub
    from scraping.models import NewsArticle
    from signals.models import Signal
    from strategies.models import Strategy

    now = timezone.now()
    period = now - timedelta(days=7)
    signals = Signal.objects.filter(created_at__gte=period)
    strategies = Strategy.objects.filter(created_at__gte=period)
    news = NewsArticle.objects.filter(
        published_at__gte=period).order_by("-published_at")[:20]

    prompt = f"""Write a trading newsletter for the Sauron Vision platform.

Title: {plain_title(newsletter.title)}
Period: the last seven days
Active signals: {signals.filter(is_active=True).count()}
New signals generated: {signals.count()}
Bullish: {signals.filter(direction='bullish').count()}, Bearish: {signals.filter(direction='bearish').count()}
Avg signal score: {signals.aggregate(avg=Avg('score'))['avg'] or 0:.2f}
New strategies proposed: {strategies.filter(status='proposed').count()}
Active strategies: {strategies.filter(status__in=['active', 'approved']).count()}

Top news headlines:
{chr(10).join(f'- {n.title} ({n.source})' for n in news[:10])}

Target markets: {', '.join(newsletter.target_markets) if newsletter.target_markets else 'all'}

Write a professional, concise newsletter in markdown with ## headings:
1. Market Overview (2-3 sentences)
2. Key Signals This Period
3. Strategy Performance
4. News Highlights
5. Outlook for Next Period
6. Risk Warnings

Keep it under 500 words. Professional tone, data-driven, in English."""

    try:
        # BaseAgent is abstract: a concrete agent, so the call lands in
        # the AgentTask cost ledger like every other agent.
        result = _NewsletterWriterAgent().run(prompt=prompt)
        content = (result or {}).get("markdown", "")
        if not content:
            raise ValueError("the model returned an empty newsletter")
    except Exception as e:  # noqa: BLE001 — recorded on the row
        words = scrub(e)[:300]
        logger.warning("[newsletter] generating %s failed: %s",
                       newsletter.pk, words)
        Newsletter.objects.filter(pk=newsletter.pk, status="generating"
                                  ).update(status="failed",
                                           last_error=f"Generation failed: "
                                                      f"{words}"[:500],
                                           ai_prompt=prompt,
                                           updated_at=timezone.now())
        return False
    Newsletter.objects.filter(pk=newsletter.pk, status="generating").update(
        status="ai_generated", content_markdown=content, ai_prompt=prompt,
        last_error="", updated_at=timezone.now())
    return True
