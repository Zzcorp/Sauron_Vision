"""The weekly letter's pages (2026-09-29; alerts/newsletter_service.py).

  /admin-dashboard/newsletters/        the editions, superuser only: each
                                       one's status, schedule, reach,
                                       preview, edit form and actions
  /newsletters/                        the archive: every edition sent
  /newsletters/<id>/                   one edition (a draft is a 404 for
                                       anyone but staff)
  /newsletter/unsubscribe/<token>/     the one-click unsubscribe, no login

Every admin action finds its edition with get_object_or_404: a stale id
(an edition deleted in another tab) is a 404, never a 500. Nothing here
sends inside the request: "Send now" and "Generate with AI" queue their
Celery task and return.
"""
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import (Http404, HttpResponseForbidden,
                         HttpResponseNotAllowed)
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

logger = logging.getLogger(__name__)

#: The badge each status wears on the admin page.
STATUS_BADGE = {
    "draft": ("DRAFT", "neutral"),
    "generating": ("GENERATING", "medium"),
    "ai_generated": ("READY", "high"),
    "approved": ("APPROVED", "proposed"),
    "sending": ("SENDING", "medium"),
    "sent": ("SENT", "active"),
    "failed": ("FAILED", "bearish"),
    "cancelled": ("CANCELLED", "low"),
}
EDITABLE = ("draft", "ai_generated", "approved", "cancelled", "failed")
CANCELLABLE = ("draft", "generating", "ai_generated", "approved")
APPROVABLE = ("draft", "ai_generated")
RESCHEDULABLE = ("draft", "ai_generated", "approved", "cancelled", "failed")
#: What "Send now" starts from (newsletter_service.SENDABLE).
SENDABLE_NOW = ("draft", "ai_generated", "approved", "cancelled", "failed")


def _edition(request):
    """The edition the POST names, or a 404 (a stale or malformed id)."""
    from alerts.models import Newsletter
    try:
        pk = int(request.POST.get("newsletter_id", ""))
    except (TypeError, ValueError):
        raise Http404("no such edition")
    return get_object_or_404(Newsletter, pk=pk)


def _lease_free(nl):
    """True when a "sending" edition is not being worked on right now (its
    retries are waiting, or its worker died): Send now may resume it."""
    from datetime import timedelta

    from alerts.newsletter_service import SEND_LEASE_MINUTES
    lease = nl.send_started_at
    return lease is None or lease <= timezone.now() - timedelta(
        minutes=SEND_LEASE_MINUTES)


def _queue(task, *args, **kwargs):
    """task.delay(...), or the reason it could not be queued."""
    try:
        task.delay(*args, **kwargs)
        return ""
    except Exception as e:  # noqa: BLE001 — said on the page
        from core.secret_scrub import scrub
        logger.warning("[newsletter] %s could not be queued: %s",
                       task.name, e)
        return scrub(e)[:200]


# ── the admin actions ─────────────────────────────────────────────────────

def _create(request):
    from alerts.models import Newsletter
    from alerts.tasks import generate_newsletter_task
    frequency = request.POST.get("frequency", "adhoc")
    if frequency not in ("adhoc", "weekly"):
        frequency = "adhoc"
    title = " ".join(request.POST.get("title", "").split())[:200]
    by_email = "send_email" in request.POST
    by_telegram = "send_telegram" in request.POST
    if not (by_email or by_telegram):
        messages.error(request, "Pick at least one channel: email or "
                                "Telegram.")
        return
    nl = Newsletter.objects.create(
        title=title or "Special edition", frequency=frequency,
        status="generating", origin="admin", send_email=by_email,
        send_telegram=by_telegram, send_whatsapp=False,
        created_by=request.user)
    why = _queue(generate_newsletter_task, nl.pk)
    if why:
        nl.status = "failed"
        nl.last_error = f"The writer could not be queued: {why}"[:500]
        nl.save(update_fields=["status", "last_error", "updated_at"])
        messages.error(request, f"“{nl.title}” could not be queued for "
                                f"writing: {why}")
        return
    messages.success(request, f"“{nl.title}” is being written. It shows "
                              f"GENERATING until the model is done; "
                              f"reload the page to see it.")


def _approve(request):
    nl = _edition(request)
    if nl.status not in APPROVABLE:
        messages.error(request, f"“{nl.title}” is {nl.get_status_display()}"
                                f": nothing to approve.")
        return
    nl.status = "approved"
    nl.touched_at = timezone.now()
    nl.save(update_fields=["status", "touched_at", "updated_at"])
    messages.success(request, f"“{nl.title}” approved.")


def _queued(nl) -> bool:
    """A "Send now" is waiting in the queue for this edition."""
    return nl.send_requested_at is not None and nl.status in SENDABLE_NOW


def _send(request):
    from alerts.tasks import send_newsletter_task
    nl = _edition(request)
    resumable = nl.status == "sending" and _lease_free(nl)
    if nl.status not in SENDABLE_NOW and not resumable:
        messages.error(request, f"“{nl.title}” is "
                                f"{nl.get_status_display()}: it cannot be "
                                f"sent now.")
        return
    if not (nl.content_markdown or "").strip():
        messages.error(request, f"“{nl.title}” is empty: nothing to send.")
        return
    # The request is recorded before the task is queued, and the task
    # carries it (review, 2026-09-29): Cancel and Reschedule clear it, and
    # a task whose request is gone sends nothing.
    requested = timezone.now()
    nl.send_requested_at = requested
    nl.save(update_fields=["send_requested_at", "updated_at"])
    why = _queue(send_newsletter_task, nl.pk, scheduled=False,
                 requested=requested.isoformat())
    if why:
        nl.send_requested_at = None
        nl.save(update_fields=["send_requested_at", "updated_at"])
        messages.error(request, f"The send could not be queued: {why}")
        return
    messages.success(request, f"“{nl.title}” is queued to go out. Cancel "
                              f"stops it until a worker starts sending; "
                              f"the page then shows the deliveries.")


def _cancel(request):
    nl = _edition(request)
    if nl.status not in CANCELLABLE and not _queued(nl):
        messages.error(request, f"“{nl.title}” is "
                                f"{nl.get_status_display()}: it cannot be "
                                f"cancelled.")
        return
    was_queued = _queued(nl)
    nl.status = "cancelled"
    nl.scheduled_for = None
    nl.send_requested_at = None
    nl.save(update_fields=["status", "scheduled_for", "send_requested_at",
                           "updated_at"])
    messages.success(request, f"“{nl.title}” cancelled: it will not be "
                              f"sent" + (", and the queued send is stopped."
                                         if was_queued else "."))


def _reschedule(request):
    from alerts.newsletter_service import (MAX_SCHEDULE_DAYS, paris_words,
                                           parse_paris_input)
    nl = _edition(request)
    if nl.status not in RESCHEDULABLE:
        messages.error(request, f"“{nl.title}” is "
                                f"{nl.get_status_display()}: it cannot be "
                                f"rescheduled.")
        return
    # Paris time as the input sends it, in the future, within a year
    # (review, 2026-09-29): an offset, a year 9999 or a year 1 is refused
    # here instead of being saved and breaking the page.
    when = parse_paris_input(request.POST.get("scheduled_for"))
    if when is None:
        messages.error(request, f"Pick a date and time in Paris time, in the "
                                f"future and within {MAX_SCHEDULE_DAYS} "
                                f"days.")
        return
    if not (nl.content_markdown or "").strip():
        messages.error(request, f"“{nl.title}” is empty: nothing to "
                                f"schedule.")
        return
    nl.scheduled_for = when
    if nl.status not in ("ai_generated", "approved"):
        nl.status = "approved"
    nl.last_error = ""
    nl.touched_at = timezone.now()
    # A "Send now" still queued is replaced by the new time.
    nl.send_requested_at = None
    nl.save(update_fields=["scheduled_for", "status", "last_error",
                           "touched_at", "send_requested_at", "updated_at"])
    messages.success(request, f"“{nl.title}” goes out {paris_words(when)}.")


def _edit(request):
    nl = _edition(request)
    if nl.status not in EDITABLE:
        messages.error(request, f"“{nl.title}” is "
                                f"{nl.get_status_display()}: it can no "
                                f"longer be edited.")
        return
    title = " ".join(request.POST.get("title", "").split())[:200]
    nl.title = title or nl.title
    nl.content_markdown = request.POST.get("content", nl.content_markdown)
    nl.touched_at = timezone.now()
    nl.save(update_fields=["title", "content_markdown", "touched_at",
                           "updated_at"])
    messages.success(request, f"“{nl.title}” saved.")


def _test(request):
    from alerts.newsletter_service import send_test
    nl = _edition(request)
    if not (nl.content_markdown or "").strip():
        messages.error(request, f"“{nl.title}” is empty: nothing to test.")
        return
    ok, words = send_test(nl, request.user)
    (messages.success if ok else messages.error)(request, words)


def _delete(request):
    nl = _edition(request)
    if nl.status == "sending" and not _lease_free(nl):
        messages.error(request, f"“{nl.title}” is being sent right now: "
                                f"wait for the run to end.")
        return
    title = nl.title
    nl.delete()
    messages.success(request, f"“{title}” deleted.")


ACTIONS = {
    "create": _create, "approve": _approve, "send": _send,
    "cancel": _cancel, "reschedule": _reschedule, "edit": _edit,
    "test": _test, "delete": _delete,
}


def _rows(request, newsletters):
    """What the page shows of each edition."""
    from alerts import newsletter_service as ns
    recipients = ns.audience()
    reach = {}

    def reach_for(nl):
        key = (bool(nl.send_email), bool(nl.send_telegram))
        if key not in reach:
            scoped = [r._replace(skip=r.skip or (
                "" if (r.channel == "email" and key[0])
                or (r.channel == "telegram" and key[1]) else "channel off"))
                for r in recipients]
            reach[key] = ns.audience_counts(scoped)
        return reach[key]

    ledger = ns.ledger_counts([nl.pk for nl in newsletters])
    rows = []
    for nl in newsletters:
        label, tone = STATUS_BADGE.get(nl.status, (nl.status.upper(),
                                                   "neutral"))
        counts = ledger.get(nl.pk)
        delivered = sum(counts.values()) if counts else 0
        waiting = (nl.status in ("ai_generated", "approved")
                   and nl.scheduled_for is not None)
        queued = _queued(nl)
        has_content = bool((nl.content_markdown or "").strip())
        can_send = has_content and not queued and (
            nl.status in SENDABLE_NOW
            or (nl.status == "sending" and _lease_free(nl)))
        preview = ""
        if has_content:
            try:
                # preview=True: the page writes nothing (review,
                # 2026-09-29), not even the reader's unsubscribe token.
                preview = ns.render_email(nl, request.user, preview=True)[1]
            except Exception:  # noqa: BLE001 — a row, not the page
                logger.warning("[newsletter] preview of %s failed", nl.pk,
                               exc_info=True)
        rows.append({
            "nl": nl,
            "badge": label,
            "tone": tone,
            "queued": queued,
            "queued_words": ns.paris_words(nl.send_requested_at)
            if queued else "",
            "title": ns.plain_title(nl.title),
            "subject": ns.email_subject(nl),
            # Never raises, whatever was stored (review, 2026-09-29: a
            # year 9999 made every GET of this page a 500).
            "scheduled_words": ns.paris_words(nl.scheduled_for)
            if waiting else "",
            "schedule_input": (ns.paris_input(nl.scheduled_for)
                               or ns.paris_input(ns.next_send_time())),
            "reach": ns.reach_words(reach_for(nl))
            if nl.status not in ("sent", "sending") else "",
            "delivery": ns.delivery_words(counts) if delivered else "",
            "preview": preview,
            "has_content": has_content,
            "can_send": can_send,
            "can_cancel": nl.status in CANCELLABLE or queued,
            "can_approve": nl.status in APPROVABLE and has_content,
            "can_edit": nl.status in EDITABLE,
            "can_reschedule": nl.status in RESCHEDULABLE and has_content,
            "can_delete": not (nl.status == "sending"
                               and not _lease_free(nl)),
            "archived": nl.status in ("sent", "sending")
            and nl.sent_at is not None,
        })
    return rows


@login_required
def admin_newsletters(request):
    """The editions, and every action on them (superuser only)."""
    if not request.user.is_superuser:
        return HttpResponseForbidden()

    from alerts.models import Newsletter

    if request.method == "POST":
        action = ACTIONS.get(request.POST.get("action", ""))
        if action is None:
            messages.error(request, "Unknown action.")
        else:
            action(request)
        return redirect("admin_newsletters")

    from alerts import newsletter_service as ns
    from core.platform_control import is_component_enabled
    newsletters = list(Newsletter.objects.all()[:30])
    return render(request, "dashboard/admin_newsletters.html", {
        "page_id": "admin_newsletters",
        "rows": _rows(request, newsletters),
        "auto_send_on": is_component_enabled("newsletter_send"),
        "next_sunday": ns.paris_words(ns.next_send_time()),
        "email_unconfigured": ns.email_unconfigured(),
        "requester_email": (request.user.email or "").strip(),
    })


# ── the archive ───────────────────────────────────────────────────────────

@login_required
def newsletter_archive(request):
    """Every edition that went out, newest first."""
    from alerts import newsletter_service as ns
    editions = list(ns.published().order_by("-sent_at", "-pk")[:100])
    items = [{"nl": nl, "title": ns.plain_title(nl.title),
              "edition": ns.edition_words(nl),
              "date_words": ns.date_words(nl.sent_at)} for nl in editions]
    return render(request, "dashboard/newsletter_archive.html", {
        "page_id": "newsletters",
        "items": items,
    })


@login_required
def newsletter_detail(request, pk):
    """One edition as it was sent. Only an edition that went out is a
    page for a reader; staff may open any (the admin's preview link)."""
    from alerts import newsletter_service as ns
    from alerts.models import Newsletter
    from core.templatetags.sauron_tags import newsletter_md
    nl = get_object_or_404(Newsletter, pk=pk)
    if not request.user.is_staff and not ns.published().filter(
            pk=nl.pk).exists():
        raise Http404("no such edition")
    return render(request, "dashboard/newsletter_detail.html", {
        "page_id": "newsletters",
        "nl": nl,
        "title": ns.plain_title(nl.title),
        "edition": ns.edition_words(nl),
        "date_words": ns.date_words(nl.sent_at or nl.created_at),
        "body_html": newsletter_md(ns.letter_prose(nl.content_markdown)),
        "published": nl.sent_at is not None
        and nl.status in ("sent", "sending"),
    })


# ── unsubscribe ───────────────────────────────────────────────────────────

@csrf_exempt
def newsletter_unsubscribe(request, token):
    """The link in every letter's footer and List-Unsubscribe header.

    GET: a small page that asks, with one button (a mail client's link
    preview or a security scanner GETs links: a GET never unsubscribes).
    POST: the button, and the RFC 8058 one-click POST a mail client sends
    by itself ("List-Unsubscribe=One-Click", no cookie, no CSRF token —
    hence csrf_exempt, on this view alone): "Weekly newsletter" off.
    The signed token is the authority, not a session: no login. A token
    that does not verify is a 400 page, never a 500."""
    from alerts import newsletter_service as ns
    from alerts.models import UserNotificationPrefs
    if request.method not in ("GET", "HEAD", "POST"):
        return HttpResponseNotAllowed(["GET", "POST"])
    user = ns.user_for_token(token)
    # The token names a preferences row (it holds the signed value): read,
    # never created here.
    prefs = (UserNotificationPrefs.objects.filter(user=user).first()
             if user is not None else None)
    if prefs is None:
        return render(request, "newsletter/unsubscribe.html",
                      {"state": "bad"}, status=400)
    if request.method == "POST":
        if prefs.receive_weekly_newsletter:
            prefs.receive_weekly_newsletter = False
            prefs.save(update_fields=["receive_weekly_newsletter"])
            logger.info("[newsletter] user %s unsubscribed", user.pk)
        return render(request, "newsletter/unsubscribe.html",
                      {"state": "done", "email": user.email})
    return render(request, "newsletter/unsubscribe.html", {
        "state": "off" if not prefs.receive_weekly_newsletter else "ask",
        "email": user.email,
    })
