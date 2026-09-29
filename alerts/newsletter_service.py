"""The weekly letter: who receives it, what it looks like, how it is sent.

THE REDESIGN (2026-09-29). Until today an edition went out inside the
admin's POST: one post to the platform group, then the RAW MARKDOWN by
plain-text mail to every active user with an address, whatever their
settings said, fail_silently and a bare except around it, "sent" at zero
deliveries. The operator's decisions, built here:

  * ONE WEEKLY LETTER. The Saturday weekly review is the edition
    (weekly_draft, called by ai_agents.tasks.generate_weekly_review): READY
    at once, scheduled for the next Sunday 08:00 Europe/Paris
    (weekly_slot), and the staff are told (announce_draft) when it goes
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

THE REVIEW (2026-09-29), thirteen defects found and fixed:
  * A worker takes each delivery with one conditional UPDATE and sends
    only when it changed exactly one row; a row found in flight on resume
    is "unknown", never sent again; the lease is renewed after every
    message, and a worker writes the edition only while the lease is
    still the value it holds (it stops the moment it is not). Before, a
    worker that outlived its lease and the one that took over both sent
    every pending row.
  * An outcome that cannot be known (a Telegram read timeout, an SMTP
    timeout after DATA) is "unknown", never retried: retrying it posted
    the letter twice.
  * An address or a chat that already has the edition, under another
    account or from an earlier pass, is not sent it again.
  * audience() writes nothing: it created a preferences row with the
    model's defaults for every user without one, which subscribed them to
    signal emails.
  * A queued "Send now" is recorded and carries its request: Cancel and
    Reschedule stop it.
  * The unsubscribe link signs a random value, not the user id.
  * The Saturday review supersedes only an untouched review scheduled no
    later than its own slot, says so to the staff, and a review written
    on Sunday after 08:00 goes out that day.
"""
from __future__ import annotations

import logging
import os
import re
import secrets
import smtplib
from collections import namedtuple
from datetime import datetime, time, timedelta
from datetime import timezone as dt_tz
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth.models import User
from django.db.models import F
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
#: How far ahead the admin may schedule an edition.
MAX_SCHEDULE_DAYS = 365
UNSUBSCRIBE_SALT = "newsletter-unsubscribe"
ADMIN_PATH = "/admin-dashboard/newsletters/"
SETTINGS_PATH = "/notifications/settings/"
ARCHIVE_PATH = "/newsletters/"
READ_WORDS = "Read it on the platform"
#: The statuses an edition can be sent from by an explicit "Send now";
#: the scheduled pass sends READY and APPROVED only.
SENDABLE = ("draft", "ai_generated", "approved", "cancelled", "failed")
#: Delivery statuses whose message may have reached its address.
REACHED = ("sent", "unknown", "sending")
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


def _paris(moment):
    """`moment` in Paris, or None when it has no Paris equivalent (a year
    9999 stored before the input was checked: astimezone overflows)."""
    if moment is None:
        return None
    try:
        return moment.astimezone(PARIS) if moment.tzinfo else moment
    except (OverflowError, ValueError, OSError):
        return None


def _utc_words(moment) -> str:
    try:
        return moment.strftime("%Y-%m-%d %H:%M") + " UTC"
    except (ValueError, AttributeError):
        return str(moment)


def date_words(moment, *, weekday=False) -> str:
    """"4 October 2026", or "Sunday 4 October 2026" (Paris date). Never
    raises: a value with no Paris equivalent is said in UTC."""
    if moment is None:
        return ""
    local = _paris(moment)
    if local is None:
        return _utc_words(moment)
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
    """"Sunday 4 October 2026 at 08:00 Paris time"; "" for None. Never
    raises (see date_words)."""
    if moment is None:
        return ""
    local = _paris(moment)
    if local is None:
        return _utc_words(moment)
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


def weekly_slot(now=None) -> tuple:
    """(when the week's review goes out, whether the Sunday slot had
    passed). The next Sunday 08:00 Paris; but a review written ON a Sunday
    after 08:00 (review, 2026-09-29) goes out that same day at the next
    quarter hour, the next send_due pass: next_send_time's "a week later"
    was cancelled by the next Saturday's review, and that week's letter
    never went out."""
    now = now or timezone.now()
    local = now.astimezone(PARIS)
    if local.weekday() == SEND_WEEKDAY and local.time() >= time(SEND_HOUR):
        quarter = now.replace(second=0, microsecond=0)
        quarter -= timedelta(minutes=quarter.minute % 15)
        return quarter + timedelta(minutes=15), True
    return next_send_time(now), False


_LOCAL_INPUT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?")


def parse_paris_input(value, *, now=None):
    """A <input type="datetime-local"> value ("2026-10-04T08:00"), read as
    Paris time, in UTC; None when it is not one (review, 2026-09-29).

    Only the naive form the input sends: an offset or a zone ("…+00:00")
    is refused, the field is Paris time. A date with no UTC equivalent
    (year 1 in Paris) is refused rather than raised, and so is a time in
    the past or more than MAX_SCHEDULE_DAYS ahead: 9999-12-31 was saved
    and then made every GET of the admin page raise OverflowError."""
    text = str(value or "").strip()
    if not _LOCAL_INPUT.fullmatch(text):
        return None
    try:
        when = datetime.fromisoformat(text).replace(
            tzinfo=PARIS).astimezone(dt_tz.utc)
    except (ValueError, OverflowError):
        return None
    now = now or timezone.now()
    if when <= now or when > now + timedelta(days=MAX_SCHEDULE_DAYS):
        return None
    return when


def paris_input(moment) -> str:
    """The value a datetime-local input shows for `moment` (Paris); "" for
    None or a value with no Paris equivalent."""
    local = _paris(moment)
    if local is None:
        return ""
    return local.strftime("%Y-%m-%dT%H:%M")


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
    """Everyone the edition is for, one Recipient per person. READS ONLY.

    Active, a non-empty email, not an investor login (an investor sees
    one book through the investor panel, percentages only: the weekly
    review speaks about the whole platform's positions and money), and
    UserNotificationPrefs.receive_weekly_newsletter on. A user with no
    preferences row is read through an UNSAVED row with the model's
    defaults (review, 2026-09-29): this used to create the row, and a row
    with the defaults (email_notifications, receive_signals) is what
    alerts/dispatch.py mails signal alerts to, so a GET of the admin page
    subscribed every such user to them. Then the profile's one channel:
    "none" receives nothing, "telegram" the user's own chat, "email" and
    "discord" by email. A user with no TraderProfile has never chosen:
    the model's default applies.

    Sent once per address: a chat several users share goes to the first
    of them (like the digests), and so does an email address two accounts
    share, compared lower-cased (review, 2026-09-29: admin_create_user
    allows the same address twice). The others are listed with the
    reason, and so is a Telegram user without a chat, or a channel this
    edition does not use (its send_email / send_telegram): the ledger
    records them "skipped", so the admin page can say so.
    Quiet hours do not apply (the module docstring says why).
    """
    from alerts.models import UserNotificationPrefs
    from portfolio.trader_profile import TraderProfile

    users = (User.objects.filter(is_active=True)
             .exclude(email__isnull=True).exclude(email__exact="")
             .filter(investor_access__isnull=True).order_by("pk"))
    prefs = {p.user_id: p for p in
             UserNotificationPrefs.objects.filter(user__in=users)}
    chosen = dict(TraderProfile.objects.filter(user__in=users)
                  .values_list("user_id", "notify_channel"))
    default = TraderProfile._meta.get_field("notify_channel").default

    by_email = getattr(newsletter, "send_email", True)
    by_telegram = getattr(newsletter, "send_telegram", True)
    out, chats, addresses = [], {}, {}
    for user in users:
        email = (user.email or "").strip()
        p = prefs.get(user.pk) or UserNotificationPrefs(user_id=user.pk)
        if not email or not p.receive_weekly_newsletter:
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
            key = email.lower()
            if not by_email:
                skip = "this edition does not go out by email"
            elif key in addresses:
                skip = (f"shares the address {email} with "
                        f"{addresses[key]}: sent there once")
            else:
                addresses[key] = user.username
                skip = ""
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

def newsletter_token_for(user) -> str:
    """The random value the user's unsubscribe link signs, made the first
    time it is needed (review, 2026-09-29: the link carried the user id).

    Written only when a letter is built for the user, never by a page
    view. A user with no preferences row gets one with receive_signals
    off: a row the user never made must not start signal alerts
    (alerts/dispatch.py mails any user who has a row with it on, and
    skips a user who has none)."""
    from alerts.models import UserNotificationPrefs
    prefs = UserNotificationPrefs.objects.filter(user=user).first()
    if prefs is None:
        prefs, _ = UserNotificationPrefs.objects.get_or_create(
            user=user, defaults={"receive_signals": False})
    if not prefs.newsletter_token:
        UserNotificationPrefs.objects.filter(
            pk=prefs.pk, newsletter_token__isnull=True).update(
                newsletter_token=secrets.token_urlsafe(18))
        prefs.refresh_from_db(fields=["newsletter_token"])
    return prefs.newsletter_token


def unsubscribe_token(user) -> str:
    """The user's random value, signed (salt "newsletter-unsubscribe", no
    expiry: a letter read a year later still unsubscribes). Nothing in it
    says who the user is."""
    from django.core import signing
    return signing.Signer(salt=UNSUBSCRIBE_SALT).sign(
        newsletter_token_for(user))


def user_for_token(token):
    """The user a token names, or None for anything else: a bad signature,
    a malformed token, a value no row holds (its user deleted). The
    user-id tokens of the first cut stop working: none was ever sent (the
    feature ships with the review's fixes)."""
    from django.core import signing

    from alerts.models import UserNotificationPrefs
    try:
        value = signing.Signer(salt=UNSUBSCRIBE_SALT).unsign(str(token or ""))
    except (signing.BadSignature, ValueError, TypeError):
        return None
    if not value:
        return None
    prefs = (UserNotificationPrefs.objects.filter(newsletter_token=value)
             .select_related("user").first())
    return prefs.user if prefs else None


def unsubscribe_path(user) -> str:
    return f"/newsletter/unsubscribe/{unsubscribe_token(user)}/"


# ── the email ─────────────────────────────────────────────────────────────

def email_context(newsletter, user=None, *, web=False, preview=False) -> dict:
    """What templates/email/newsletter.{html,txt} read. `web`: the copy on
    the platform (the archive): no unsubscribe link. `preview`: the admin
    page's copy, which must write nothing (review, 2026-09-29): the
    unsubscribe link is named, not made, since making it creates the
    reader's token. Every link absolute or absent."""
    from alerts.channels.telegram_alert import platform_link
    from core.templatetags.sauron_tags import newsletter_md, newsletter_plain
    prose = letter_prose(newsletter.content_markdown)
    moment = newsletter.sent_at or newsletter.scheduled_for or timezone.now()
    unsubscribe = ""
    if user is not None and not (web or preview) and platform_link("/"):
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
        "preview": preview,
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


def _render(ctx) -> tuple:
    from django.template.loader import render_to_string
    return (render_to_string("email/newsletter.txt", ctx),
            render_to_string("email/newsletter.html", ctx))


def render_email(newsletter, user=None, *, web=False, preview=False) -> tuple:
    """(text, html) of the edition as `user` receives it."""
    return _render(email_context(newsletter, user, web=web, preview=preview))


def build_email(newsletter, user, *, connection=None, subject_prefix=""):
    """One EmailMultiAlternatives for one recipient: the unsubscribe link
    is personal, so a message is never shared between two people. From
    settings.DEFAULT_FROM_EMAIL; List-Unsubscribe (and its RFC 8058 one-
    click twin) only when the link can be absolute."""
    from django.core.mail import EmailMultiAlternatives
    ctx = email_context(newsletter, user)
    text, html = _render(ctx)
    headers = {}
    link = ctx["unsubscribe_url"]
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


def _same_request(stored, requested) -> bool:
    try:
        return stored is not None and (
            datetime.fromisoformat(str(requested)) == stored)
    except (TypeError, ValueError):
        return False


def claim(newsletter_id, *, scheduled=False, requested=None) -> tuple:
    """(the edition, "") when this worker may send it now, else (None, why).

    Under select_for_update, so two workers cannot both take it: the
    first sets "sending" and the lease, the second finds a fresh lease and
    stops. A "sending" row whose lease was released (a retry is due) or
    is older than SEND_LEASE_MINUTES (its worker died) is resumed.
    `scheduled` (the send_due pass): READY or APPROVED only, and only once
    `scheduled_for` has come (a queued task must not send an edition
    rescheduled or cancelled since). `requested` (a queued "Send now",
    review 2026-09-29): sent only while the edition still carries that
    request; Cancel and Reschedule clear it. A call with neither (the
    shell) sends any SENDABLE edition but a cancelled one. A FAILED
    edition gets a fresh round of attempts.
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
        elif requested is not None:
            if not _same_request(nl.send_requested_at, requested):
                return None, ("the send was cancelled or rescheduled after "
                              "it was requested")
            if nl.status not in SENDABLE:
                return None, f"its status is {nl.status}"
        elif nl.status not in SENDABLE or nl.status == "cancelled":
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
        nl.send_requested_at = None
        nl.last_error = ""
        nl.save(update_fields=["status", "send_started_at",
                               "send_requested_at", "last_error",
                               "updated_at"])
    return nl, ""


class _LeaseLost(Exception):
    """Another worker holds the edition now: this run stops where it is."""


def send_newsletter(newsletter, *, scheduled=False, requested=None) -> dict:
    """Send one edition: claim it, build its ledger, deliver, conclude.

    {"status", "recipients", "email", "telegram", "failed", "skipped",
    "unknown", "pending", "sending"} — "recipients" is the deliveries that
    went out, all channels, all runs. Never raises for a recipient: each
    outcome is recorded against its row. A run whose lease another worker
    took stops at once and says so ("stopped"), writing nothing more. An
    unexpected error stops the run and marks the edition "failed" with the
    reason (Send now resumes it; a delivered row is never sent again),
    then re-raises for the worker's log.
    """
    from alerts.models import Newsletter
    from core.secret_scrub import scrub
    nl, why = claim(newsletter.pk, scheduled=scheduled, requested=requested)
    if nl is None:
        logger.info("[newsletter] %s not sent: %s", newsletter.pk, why)
        return {"status": "skipped", "reason": why, "recipients": 0}
    run = _Run(nl)
    try:
        return _run(run)
    except _LeaseLost:
        logger.warning("[newsletter] %s: another worker took the edition "
                       "over; this run stopped after %d sent", nl.pk,
                       run.sent_now)
        return {"status": "stopped",
                "reason": "another worker holds the edition now",
                "recipients": run.sent_now}
    except Exception as e:
        words = scrub(e)[:300]
        logger.exception("[newsletter] the send of %s stopped: %s", nl.pk,
                         words)
        Newsletter.objects.filter(
            pk=nl.pk, status="sending", send_started_at=run.lease).update(
                status="failed", send_started_at=None,
                last_error=(f"The send stopped: {words}. Send now resumes "
                            f"it; no one who received it gets it "
                            f"twice.")[:500])
        raise


class _Run:
    """One worker's run over one edition: its lease token, what it took,
    what it reached."""

    def __init__(self, nl):
        self.nl = nl
        self.lease = nl.send_started_at
        self.sent_users = []        # (user, channel) reached, not yet belled
        self.sent_now = 0
        self.attempted = 0
        self.stamped = nl.sent_at is not None

    def renew(self):
        """After every message: renew the lease, only where it is still
        ours, and stamp sent_at at the first delivery. Raises _LeaseLost
        when the edition's lease is no longer the one this run holds."""
        from alerts.models import Newsletter
        now = max(timezone.now(), self.lease + timedelta(microseconds=1))
        fields = {"send_started_at": now}
        if self.sent_now and not self.stamped:
            fields["sent_at"] = now
        changed = Newsletter.objects.filter(
            pk=self.nl.pk, status="sending",
            send_started_at=self.lease).update(**fields)
        if changed != 1:
            raise _LeaseLost()
        self.lease = now
        if "sent_at" in fields:
            self.stamped = True

    def take(self, d, address) -> bool:
        """Take a delivery for this run with one conditional UPDATE: from
        the status and attempts it was read at, to "sending" and one more
        attempt. True only when exactly one row changed: then this run,
        and no other, sends it."""
        from alerts.models import NewsletterDelivery
        changed = NewsletterDelivery.objects.filter(
            pk=d.pk, status=d.status, attempts=d.attempts).update(
                status="sending", attempts=F("attempts") + 1,
                address=str(address or "")[:254], error="")
        if changed == 1:
            d.status, d.attempts, d.address = "sending", d.attempts + 1, address
            self.attempted += 1
        return changed == 1

    def record(self, d, status, error=""):
        """The outcome of a row this run took (only while it is still
        "sending": a row a later worker declared "unknown" stays so)."""
        from alerts.models import NewsletterDelivery
        from core.secret_scrub import scrub
        fields = {"status": status, "error": scrub(error)[:500]}
        if status == "sent":
            fields["sent_at"] = timezone.now()
        NewsletterDelivery.objects.filter(pk=d.pk, status="sending").update(
            **fields)
        d.status = status
        if status == "sent":
            self.sent_now += 1

    def bell(self):
        _bell(self.nl, self.sent_users)
        self.sent_users = []


def _skip(d, reason):
    """Mark a row skipped, unless another worker took it meanwhile."""
    from alerts.models import NewsletterDelivery
    NewsletterDelivery.objects.filter(
        pk=d.pk, status__in=("pending", "failed")).update(
            status="skipped", error=str(reason)[:500])


def _run(run) -> dict:
    from alerts.channels.telegram_alert import markdown_lines
    from alerts.models import NewsletterDelivery

    nl = run.nl
    ledger = NewsletterDelivery.objects.filter(newsletter=nl)
    # A row still "sending" belongs to a worker that is gone (this run
    # holds the lease): it may have sent the message and died before the
    # ledger write. Its outcome is unknown; it is never sent again.
    left = ledger.filter(status="sending").update(
        status="unknown",
        error="A worker took it and stopped before recording the answer: "
              "it may have been sent, so it is not sent again.")
    if left:
        logger.warning("[newsletter] %s: %d deliver%s left in flight by an "
                       "earlier worker, recorded unknown", nl.pk, left,
                       "y" if left == 1 else "ies")

    recipients = audience(nl)
    by_user = {r.user.pk: r for r in recipients}
    known = set(ledger.values_list("user_id", flat=True))
    NewsletterDelivery.objects.bulk_create(
        [NewsletterDelivery(newsletter=nl, user=r.user, channel=r.channel,
                            status="skipped" if r.skip else "pending",
                            error=r.skip[:500])
         for r in recipients if r.user.pk not in known],
        ignore_conflicts=True)

    # Addresses and chats that already have this edition, whichever
    # account it went to and in whichever pass (review, 2026-09-29): the
    # once-per-address rule of audience() holds across passes too.
    reached = list(ledger.filter(status__in=REACHED)
                   .values_list("channel", "address"))
    emails_had = {a.lower() for c, a in reached if c == "email" and a}
    chats_had = {a for c, a in reached if c == "telegram" and a}

    todo = []
    retry = (ledger.filter(status__in=("pending", "failed"),
                           attempts__lt=NewsletterDelivery.MAX_ATTEMPTS)
             .select_related("user"))
    for d in retry:
        r = by_user.get(d.user_id)
        if r is None:
            _skip(d, "no longer in the audience (unsubscribed, deactivated "
                     "or no address) before this attempt")
            continue
        if r.skip:
            _skip(d, r.skip)
            continue
        if d.channel != r.channel:
            # The user changed channel between two attempts: this row
            # follows (one row per user: nobody receives it twice).
            if not NewsletterDelivery.objects.filter(
                    pk=d.pk, status=d.status, attempts=d.attempts).update(
                        channel=r.channel):
                continue
            d.channel = r.channel
        todo.append((d, r))

    try:
        emails = [(d, r) for d, r in todo if d.channel == "email"]
        for start in range(0, len(emails), EMAIL_BATCH):
            _send_email_batch(run, emails[start:start + EMAIL_BATCH],
                              emails_had)
            run.bell()
        telegram = [(d, r) for d, r in todo if d.channel == "telegram"]
        if telegram:
            lines = markdown_lines(letter_prose(nl.content_markdown))
            for d, r in telegram:
                _send_telegram(run, d, r.address, lines, chats_had)
    finally:
        run.bell()
    return _conclude(run)


def _watch_data(connection):
    """Mark the SMTP session when it reaches DATA, so a timeout after it
    can be told from one before (review, 2026-09-29). Only for a backend
    that holds an smtplib session (`connection.connection`)."""
    smtp = getattr(connection, "connection", None)
    if smtp is None or not hasattr(smtp, "data"):
        return
    if not getattr(smtp, "_sv_watched", False):
        original = smtp.data

        def data(*args, **kwargs):
            smtp._sv_data_sent = True
            return original(*args, **kwargs)

        smtp.data = data
        smtp._sv_watched = True
    smtp._sv_data_sent = False


def _data_sent(connection):
    """True / False when the backend's SMTP session says whether DATA was
    reached; None when it cannot tell."""
    smtp = getattr(connection, "connection", None)
    if smtp is None or not getattr(smtp, "_sv_watched", False):
        return None
    return bool(getattr(smtp, "_sv_data_sent", False))


def email_outcome(exc, data_sent) -> str:
    """"failed" (retry it) or "unknown" (never again) for an exception from
    sending one message. A refusal the server said in words (a 4xx/5xx
    code, refused recipients) is failed. A timeout or a dropped connection
    is unknown once DATA was reached (the server may have accepted it) or
    when the backend cannot tell; before DATA it is failed."""
    if isinstance(exc, (smtplib.SMTPRecipientsRefused,
                        smtplib.SMTPResponseException)):
        return "failed"
    if isinstance(exc, (smtplib.SMTPServerDisconnected, TimeoutError,
                        OSError)):
        return "failed" if data_sent is False else "unknown"
    return "failed"


def _send_email_batch(run, batch, had):
    """One connection for up to EMAIL_BATCH messages, each taken, sent and
    recorded on its own over it, the lease renewed after each: a message
    the server refuses is recorded failed and the others go on; a
    connection that breaks is replaced for the rest of the batch. A server
    that cannot be reached fails the rest of the batch with its reason."""
    from django.core.mail import get_connection
    why = email_unconfigured()
    connection = None
    try:
        for d, r in batch:
            if r.address.lower() in had:
                _skip(d, "the address already has this edition (another "
                         "account shares it)")
                continue
            if not run.take(d, r.address):
                continue
            had.add(r.address.lower())
            if why:
                run.record(d, "failed", why)
                run.renew()
                continue
            try:
                msg = build_email(run.nl, d.user)
            except Exception as e:  # noqa: BLE001 — recorded against the row
                run.record(d, "failed", f"the email could not be built: {e}")
                run.renew()
                continue
            if connection is None:
                try:
                    connection = get_connection(fail_silently=False)
                    connection.open()
                except Exception as e:  # noqa: BLE001
                    connection = None
                    why = f"the mail server could not be reached: {e}"
                    run.record(d, "failed", why)
                    run.renew()
                    continue
            _watch_data(connection)
            msg.connection = connection
            try:
                ok = connection.send_messages([msg]) == 1
                run.record(d, "sent" if ok else "failed",
                           "" if ok else "the mail server did not accept it")
                if ok:
                    run.sent_users.append((d.user, "email"))
            except Exception as e:  # noqa: BLE001 — one message, not the batch
                outcome = email_outcome(e, _data_sent(connection))
                run.record(d, outcome, str(e) if outcome == "failed" else (
                    f"The outcome is not known ({e}): the server may have "
                    f"taken it, so it is not sent again."))
                try:
                    connection.close()
                except Exception:  # noqa: BLE001
                    pass
                connection = None
            run.renew()
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:  # noqa: BLE001
                pass


def _send_telegram(run, d, chat, lines, had):
    """The edition to the user's own chat, in the house style: HTML, every
    field escaped, the newsletter's mark, the markdown as lines, and a
    button to the archive copy (or its path as the last line when the
    platform names no host). send_to_chat_outcome never raises and logs a
    refusal at WARNING with Telegram's own words; a lost answer (a read
    timeout) is "unknown", never posted again. The lease is renewed after
    the message."""
    from alerts.channels.telegram_alert import (MARKS, button_markup,
                                                page_line,
                                                send_to_chat_outcome)
    if chat in had:
        _skip(d, "the chat already has this edition (another account "
                 "shares it)")
        return
    if not run.take(d, chat):
        return
    had.add(chat)
    if not os.getenv("TELEGRAM_BOT_TOKEN", ""):
        run.record(d, "failed", "TELEGRAM_BOT_TOKEN is not set")
        run.renew()
        return
    button = (READ_WORDS, run.nl.archive_path)
    told = list(lines) or [plain_title(run.nl.title)]
    if button_markup(button) is None:
        told.append(page_line(run.nl.archive_path, READ_WORDS))
    outcome = send_to_chat_outcome(chat, telegram_title(run.nl), lines=told,
                                   mark=MARKS["newsletter"], button=button)
    if outcome == "sent":
        run.record(d, "sent")
        run.sent_users.append((d.user, "telegram"))
    elif outcome == "unknown":
        run.record(d, "unknown", "Telegram's answer was lost (the WARNING "
                                 "line before this says why): it may have "
                                 "been posted, so it is not posted again.")
    elif outcome == "refused":
        run.record(d, "failed", "Telegram refused the message (the WARNING "
                                "line before this says why)")
    else:
        run.record(d, "failed", "the message did not reach Telegram (the "
                                "WARNING line before this says why)")
    run.renew()


def _bell(nl, sent_users):
    """A bell row ("newsletter") for each person reached, linking to the
    archive copy. Best-effort: the letter went out either way."""
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
    """{id: {"email", "telegram", "failed", "skipped", "unknown", "pending",
    "sending"}} from the ledger: "email"/"telegram" count the deliveries
    SENT on each."""
    from django.db.models import Count

    from alerts.models import NewsletterDelivery
    out = {i: {"email": 0, "telegram": 0, "failed": 0, "skipped": 0,
               "unknown": 0, "pending": 0, "sending": 0}
           for i in newsletter_ids}
    rows = (NewsletterDelivery.objects
            .filter(newsletter_id__in=list(newsletter_ids))
            .values("newsletter_id", "channel", "status")
            .annotate(n=Count("id")))
    for row in rows:
        counts = out[row["newsletter_id"]]
        if row["status"] == "sent":
            counts[row["channel"]] += row["n"]
        else:
            counts[row["status"]] = counts.get(row["status"], 0) + row["n"]
    return out


def delivery_words(counts) -> str:
    """"9 sent by email, 3 by Telegram, 1 failed, 2 skipped", and the
    outcomes not known, the ones in flight and the ones waiting when
    there are any."""
    text = (f"{counts['email']} sent by email, {counts['telegram']} by "
            f"Telegram, {counts['failed']} failed, {counts['skipped']} "
            f"skipped")
    if counts.get("unknown"):
        text += f", {counts['unknown']} outcome unknown"
    if counts.get("sending"):
        text += f", {counts['sending']} in flight"
    if counts.get("pending"):
        text += f", {counts['pending']} waiting"
    return text


def _conclude(run) -> dict:
    """The run's verdict on the edition, written only while the lease is
    still this run's. Retries left: it stays "sending" with the lease
    released, for the next send_due pass. Otherwise "sent" when at least
    one delivery ever went out, "failed" when none did."""
    from alerts.models import Newsletter, NewsletterDelivery
    nl = run.nl
    counts = ledger_counts([nl.pk])[nl.pk]
    sent = counts["email"] + counts["telegram"]
    retry = NewsletterDelivery.objects.filter(
        newsletter=nl, status__in=("pending", "failed"),
        attempts__lt=NewsletterDelivery.MAX_ATTEMPTS).count()
    now = timezone.now()
    unknown_words = (
        f" {counts['unknown']} outcome{'' if counts['unknown'] == 1 else 's'}"
        f" unknown (a timeout after the message left): not sent again."
        if counts["unknown"] else "")
    fields = {"send_started_at": None, "recipients_count": sent}
    if retry:
        status = "sending"
        fields["last_error"] = (
            f"{retry} deliver{'y' if retry == 1 else 'ies'} failed and will "
            f"be tried again by the next pass (at most "
            f"{NewsletterDelivery.MAX_ATTEMPTS} attempts each)."
            + unknown_words)
    elif sent:
        status = "sent"
        fields["last_error"] = ((
            f"{counts['failed']} could not be delivered after "
            f"{NewsletterDelivery.MAX_ATTEMPTS} attempts."
            if counts["failed"] else "") + unknown_words).strip()
    else:
        status = "failed"
        total = (counts["failed"] + counts["skipped"] + counts["pending"]
                 + counts["unknown"])
        fields["last_error"] = (
            "Nothing was sent: nobody receives it (no active user with an "
            "email has the weekly newsletter on, on a channel that has a "
            "newsletter)." if not total else
            f"Nothing was sent: {counts['failed']} failed, "
            f"{counts['skipped']} skipped." + unknown_words)
    fields["status"] = status
    changed = Newsletter.objects.filter(
        pk=nl.pk, status="sending", send_started_at=run.lease).update(
            updated_at=now, **fields)
    if changed != 1:
        logger.warning("[newsletter] %s: another worker holds the edition; "
                       "this run's verdict is not written", nl.pk)
        return {"status": "stopped",
                "reason": "another worker holds the edition now",
                "recipients": run.sent_now}
    if sent:
        # The first delivery's time, when the heartbeat already stamped it.
        Newsletter.objects.filter(pk=nl.pk, sent_at__isnull=True).update(
            sent_at=now)

    if counts["failed"] or counts["unknown"]:
        logger.warning("[newsletter] %s: %d deliver%s failed, %d outcome%s "
                       "unknown (%s)", nl.pk, counts["failed"],
                       "y" if counts["failed"] == 1 else "ies",
                       counts["unknown"],
                       "" if counts["unknown"] == 1 else "s",
                       delivery_words(counts))
    if status == "failed":
        logger.warning("[newsletter] %s failed: %s", nl.pk,
                       fields["last_error"])
    logger.info("[newsletter] %s: %s; %d attempted this run, %d sent",
                nl.pk, delivery_words(counts), run.attempted, run.sent_now)
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

    READY with its slot (weekly_slot: the next Sunday 08:00 Paris, or the
    next quarter hour on a Sunday past 08:00), origin "weekly_review".
    An earlier review still waiting is superseded (review, 2026-09-29)
    only when it is scheduled no later than the new slot and no person
    approved, edited, rescheduled or queued it: a human's decision is
    never undone by the machine. The staff are told at once
    (announce_draft), with every edition cancelled named. An empty review
    is recorded "failed", scheduled for nothing, and the staff are told
    that instead.
    """
    from alerts.models import Newsletter
    now = now or timezone.now()
    title = week_title(now)
    text = str(review_text or "")
    if not text.strip():
        nl = Newsletter.objects.create(
            title=title, frequency="weekly", status="failed",
            origin="weekly_review", content_markdown="", ai_prompt=prompt,
            last_error="The weekly review came back empty: nothing is "
                       "scheduled this week.")
        logger.warning("[newsletter] the weekly review was empty: edition "
                       "%s recorded failed, nothing scheduled", nl.pk)
        return nl, announce_draft(nl)
    when, late = weekly_slot(now)
    nl = Newsletter.objects.create(
        title=title, frequency="weekly", status="ai_generated",
        origin="weekly_review", content_markdown=text, ai_prompt=prompt,
        scheduled_for=when)
    superseded = list(
        Newsletter.objects.filter(
            origin="weekly_review", status__in=("ai_generated", "approved"),
            scheduled_for__isnull=False, scheduled_for__lte=when,
            touched_at__isnull=True, send_requested_at__isnull=True)
        .exclude(pk=nl.pk).order_by("scheduled_for"))
    if superseded:
        Newsletter.objects.filter(pk__in=[s.pk for s in superseded]).update(
            status="cancelled", scheduled_for=None,
            last_error=f"Superseded by the edition of {date_words(now)}.")
    return nl, announce_draft(nl, superseded=[plain_title(s.title)
                                              for s in superseded],
                              late=late)


def announce_draft(nl, *, superseded=(), late=False) -> dict:
    """Tell the staff the week's edition is ready (or that it failed): a
    bell row ("newsletter") for every active staff user, and one house-
    style message to each staff Telegram chat (bot_program.morgul.
    recipients, the chats the Eye and the Monday plan use; the platform
    chat when none is configured). `superseded`: the editions it
    cancelled, named; `late`: the Sunday slot had passed and it goes out
    today. {"bell", "telegram"}."""
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
        local = _paris(nl.scheduled_for)
        if local is None:
            title = "Weekly letter ready · goes out when sent"
        elif late:
            title = ("Weekly letter ready · goes out today "
                     + local.strftime("%H:%M") + " Paris time")
        else:
            title = ("Weekly letter ready · goes out "
                     + local.strftime("%A %H:%M") + " Paris time")
        lines = [f"Edition: {name}",
                 f"Goes out: {when}" if when else "Goes out: when sent"]
        body = f"{name} goes out {when or 'when sent'} unless cancelled."
        if late:
            late_words = ("The Sunday 08:00 slot had passed when the review "
                          "was written: it goes out today at the next "
                          "quarter hour instead.")
            lines.append(late_words)
            body += " " + late_words
        lines.append("Audience: " + reach_words(counts))
        for old in superseded:
            lines.append(f"Cancelled, superseded by this one: {old}")
        if superseded:
            body += (" It cancelled the earlier edition"
                     f"{'s' if len(superseded) > 1 else ''} still waiting: "
                     + "; ".join(superseded) + ".")
        lines.append(page_line(ADMIN_PATH, "Read, edit or cancel it"))
        body += (f" It {reach_words(counts)}. Read, edit or cancel it on "
                 f"the Newsletters page.")
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
