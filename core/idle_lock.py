"""Idle PIN lock — server-authoritative enforcement.

The platform already treats the PIN as a server-verified second factor
everywhere it matters: login, arming a bot live, the kill switch. An
idle-lock overlay that only existed in the browser would be the one PIN
gate dismissible from devtools, so the lock is a SESSION FLAG
(`pin_locked`) and this middleware is what the flag means:

* JSON/XHR traffic answers 423 while locked — data stops flowing to a
  locked tab no matter what its DOM says.
* Page GETs still render (the shell paints itself pre-locked via the
  `pin_locked` context flag), but non-exempt POSTs are bounced back to
  the same URL as a GET: no state changes from behind the lock.
* The flag is set client-side (POST /api/session/lock/) when the tab
  notices idleness — and HERE as a backstop when the server-side gap
  exceeds the profile's window, so a tab whose JS died still locks.

Deliberately a flag, not a logout: the session, its CSRF token and the
page state all survive, and the lock composes with normal session expiry.

Cost discipline: the TraderProfile is only fetched once the session's
activity gap exceeds the smallest configurable window (5 minutes) — on
an active session this middleware does no queries at all. The profile is
NOT cached in the session because the PIN can be set or changed through
several endpoints (profile modals, change_pin, admin); a session cache
would go stale exactly when it matters and need refresh hooks in code
this module has no business touching. The activity stamp itself is
throttled so it does not force a session write on every request.
"""
from __future__ import annotations

import time
from urllib.parse import quote

from django.core.cache import cache
from django.http import HttpResponseRedirect, JsonResponse

# Smallest selectable idle window (minutes choice 5). Below this gap no
# profile lookup can change the outcome, so none is made.
MIN_LOCK_SECONDS = 5 * 60

# Re-stamp sv_last_seen at most this often. Every stamp marks the session
# modified and costs a session-store write; 30s of slack against a >=5min
# window is invisible to the operator and keeps the hot path write-free.
STAMP_GRANULARITY = 30

LAST_SEEN_KEY = "sv_last_seen"
LOCKED_KEY = "pin_locked"

# Paths the lock must never sit in front of: the unlock/lock endpoints
# themselves, every way OUT (logout, login, the wall), infrastructure
# probes, and static assets. Matched by prefix.
EXEMPT_PREFIXES = (
    "/api/session/lock/",
    "/api/session/unlock/",
    "/logout/",
    "/login/",
    "/wall/",
    "/locked/",
    "/healthz/",
    "/static/",
    "/media/",
    "/favicon",
)

# The one request that means "a human is still here". Everything else a
# page fires — the health poll, the WebSocket-driven partial refreshes —
# is machinery, and machinery must never hold a session open: an
# unattended tab on a busy market would otherwise re-stamp itself awake
# on every incoming signal and never lock at all.
PING_PATH = "/api/session/ping/"

# Where a locked session is sent when it asks for a page. NOT a
# pass-through: the Django admin and the PDF report views render no
# overlay (they don't extend base.html), so "the page paints itself
# locked" is only true for the app shell.
LOCKED_URL = "/locked/"

# Re-reading the lock config on every request during a long idle would be
# one query per health poll. Cached briefly instead: a PIN or setting
# changed elsewhere takes effect within this window, which is nothing
# against a 5-60 minute lock.
CONFIG_TTL = 60


def _wants_json(request) -> bool:
    """XHR/JSON traffic gets 423 instead of an HTML page it can't parse.

    /api/, /htmx/ and /partials/ are included by path: several fetch()
    callers (the health poll, the signal rail, the ticker and the panel
    counters) send neither X-Requested-With nor an Accept header worth
    reading, and a live-data endpoint answering normally while locked
    would be a data leak, not a courtesy.
    """
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return True
    if request.headers.get("HX-Request"):
        return True
    if "application/json" in (request.headers.get("Accept") or ""):
        return True
    return request.path.startswith(("/api/", "/htmx/", "/partials/"))


class IdleLockMiddleware:
    """Stamp activity, engage the lock on idleness, enforce it while set."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is None or not getattr(user, "is_authenticated", False):
            return self.get_response(request)
        if request.path.startswith(EXEMPT_PREFIXES):
            return self.get_response(request)

        session = request.session
        now = int(time.time())

        if not session.get(LOCKED_KEY):
            last = session.get(LAST_SEEN_KEY)
            if last is None:
                # First sighting of this session: seed the clock.
                session[LAST_SEEN_KEY] = now
            elif now - last > MIN_LOCK_SECONDS and self._should_lock(user, now - last):
                # Backstop: the tab's JS never asked for the lock (crashed,
                # killed, laptop lid), but the server-side gap says idle.
                session[LOCKED_KEY] = True
            elif self._is_human(request) and now - last >= STAMP_GRANULARITY:
                session[LAST_SEEN_KEY] = now

        if session.get(LOCKED_KEY):
            # Never stamp while locked — a locked tab's polling must not
            # "un-idle" the session.
            if _wants_json(request):
                return JsonResponse({"pin_locked": True}, status=423)
            # Everything else goes to the lock screen. Passing pages
            # through would have been fine for the app shell (it paints
            # its own gate) and a data leak everywhere else: /admin/ and
            # the PDF reports render no overlay at all. A POST's payload
            # is lost, but the operator SEES why instead of receiving a
            # silently blank form back.
            return HttpResponseRedirect(
                f"{LOCKED_URL}?next={quote(request.get_full_path())}")

        return self.get_response(request)

    @staticmethod
    def _is_human(request) -> bool:
        """Only a human's own traffic may hold the session open.

        The page fires plenty of requests nobody asked for — the 10s
        health poll, and the partial refreshes the WebSocket triggers on
        every incoming signal, fill or news item. Counting those as
        activity meant an unattended tab renewed itself all day on a busy
        market and never locked. The tab reports real activity (mouse,
        keys, scroll) explicitly by POSTing PING_PATH.
        """
        if request.path == PING_PATH:
            return True
        return not _wants_json(request)

    @staticmethod
    def _should_lock(user, gap_seconds: int) -> bool:
        """One profile fetch per CONFIG_TTL, made only when the gap matters.

        Fenced: enforcement must never 500 a page over a missing profile
        table mid-migration. No PIN or lock disabled = never lock — a
        PIN-less session locked behind a PIN prompt could not be released.
        Without the cache this ran on every request for the whole idle
        stretch (six a minute from the health poll alone), and forever for
        anyone who had switched the feature off.
        """
        key = f"idlelock:cfg:{user.pk}"
        config = cache.get(key)
        if config is None:
            try:
                from portfolio.trader_profile import TraderProfile
                profile = TraderProfile.objects.filter(user=user).only(
                    "access_pin_hash", "idle_lock_enabled",
                    "idle_lock_minutes",
                ).first()
            except Exception:  # noqa: BLE001
                return False
            config = (
                (False, 0) if profile is None
                else (bool(profile.has_pin and profile.idle_lock_enabled),
                      int(profile.idle_lock_minutes or 0))
            )
            try:
                cache.set(key, config, CONFIG_TTL)
            except Exception:  # noqa: BLE001 — a dead cache must not lock or unlock
                pass
        armed, minutes = config
        return bool(armed and minutes and gap_seconds > minutes * 60)
