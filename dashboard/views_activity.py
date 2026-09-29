"""GET /api/activity/feed/ — Sauron's activity log, for the drawer under
the signals rail (templates/_partials/activity_drawer.html, polled by
static/js/sv-activity.js while it is open and the tab is visible).

Staff only, as dashboard.views_day.day_live is: the log prints every
pipeline's last message, every agent call's cost and the gate's reasons,
which is what /health/, the system map and the audit page keep from a
non-staff login. base.html renders the drawer, and so this URL, for staff
alone; a non-staff caller who finds the door anyway gets the same 403 JSON
day_live answers.

Under /api/ on purpose: the idle lock answers a locked tab's poll with 423
JSON (core.idle_lock) instead of redirecting a fetch() to the lock page,
and the drawer stops polling on it until the PIN comes back.
"""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from dashboard.activity_feed import (
    DEFAULT_LIMIT, MAX_LIMIT, activity_events, iso, parse_since)


@login_required
@never_cache
@require_GET
def activity_feed(request):
    """{"now": ISO, "events": [...]} — newest first.

    ?since=<ISO-8601> keeps only events strictly newer than it (the drawer
    passes the newest line it holds, less a small overlap, and drops the
    ids it has already painted); ?limit= caps the answer (1–200, default
    60). A since that is not a timestamp is a 400, not a silent full read."""
    if not request.user.is_staff:
        return JsonResponse({"staff_only": True}, status=403)
    raw = request.GET.get("since") or ""
    since = parse_since(raw) if raw else None
    if raw and since is None:
        return JsonResponse(
            {"error": "since must be an ISO-8601 timestamp"}, status=400)
    try:
        limit = int(request.GET.get("limit") or DEFAULT_LIMIT)
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    limit = max(1, min(MAX_LIMIT, limit))
    return JsonResponse({
        "now": iso(timezone.now()),
        "events": activity_events(request.user, since=since, limit=limit),
    })
