"""Idle PIN lock — the session-side lock and its PIN-verified release.

The lock itself is a SERVER session flag (`pin_locked`), enforced by
core.idle_lock.IdleLockMiddleware. These two endpoints are the only ways
the flag moves: the client (or the middleware's backstop) sets it, and
only a server-verified PIN clears it. The overlay in base.html is just
paint over this flag — deleting the overlay from devtools changes
nothing, because every JSON endpoint keeps answering 423 until the PIN
has been checked here.

There is deliberately no "forgot PIN" endpoint on the lock: the recovery
path is a logout, then the login-time flow (password re-entry →
force_pin_reset) owned by dashboard/auth_views.py.
"""
import time

from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from core.audit import AuditLog
from core.presence import client_ip
from portfolio.trader_profile import get_or_create_profile

# One session, five guesses. A 4-digit PIN is 10,000 combinations; an
# unlimited-attempt lock screen would be the weakest gate on the platform.
MAX_ATTEMPTS = 5
ATTEMPTS_KEY = "pin_lock_attempts"


@login_required
def locked_page(request):
    """The screen a locked session gets when it asks for a page.

    Deliberately standalone and dataless: the app shell paints its own
    gate over itself, but /admin/ and the PDF report views extend
    nothing and would have rendered in full behind a lock that was
    supposed to be covering the screen. `next` is where the operator
    lands once the PIN checks out.
    """
    nxt = request.GET.get("next") or "/"
    if not nxt.startswith("/") or nxt.startswith("//"):
        nxt = "/"          # never bounce off-site on a query parameter
    if not request.session.get("pin_locked"):
        return HttpResponseRedirect(nxt)
    return render(request, "dashboard/locked.html", {"next_url": nxt})


@login_required
@require_POST
def session_lock(request):
    """Engage the lock. Idempotent — a second POST changes nothing.

    Only engages for users who actually have a PIN: a PIN-less user
    locked behind a PIN prompt could never unlock, so the flag would be
    a self-inflicted denial of service, not a security feature.
    """
    if get_or_create_profile(request.user).has_pin:
        request.session["pin_locked"] = True
        # A socket opened before the lock never meets the middleware, so
        # cut the per-user feed from the server side too — the browser's
        # own close is paint, and paint is not a lock.
        try:
            from dashboard.consumers import push_eye_event
            push_eye_event(request.user, "session_locked", {})
        except Exception:  # noqa: BLE001 — announcing must not fail the lock
            pass
    return HttpResponse(status=204)


@login_required
@require_POST
def session_ping(request):
    """Tell the server the operator is still here.

    Reading a chart, scrolling a table or moving the mouse sends no HTTP
    request at all, so the server's activity clock would go stale while
    the operator is plainly working — and the next click would land on a
    lock screen. The tab posts here while it sees local activity; the
    stamp itself is the middleware's (any non-health request refreshes
    `sv_last_seen`), so this view only has to exist and answer.

    Not exempt from the lock: once the flag is set this path answers 423
    like any other, which is how a second tab discovers the lock.
    """
    return HttpResponse(status=204)


@login_required
@require_POST
def session_unlock(request):
    """Release the lock — the PIN is verified HERE, never client-side."""
    pin = request.POST.get("pin", "")
    profile = get_or_create_profile(request.user)

    if profile.check_pin(pin):
        request.session.pop("pin_locked", None)
        request.session.pop(ATTEMPTS_KEY, None)
        request.session["sv_last_seen"] = int(time.time())
        AuditLog.log(
            request.user, "login", "Idle lock released with PIN",
            target_type="Session", ip_address=client_ip(request))
        return JsonResponse({"status": "ok"})

    attempts = request.session.get(ATTEMPTS_KEY, 0) + 1
    if attempts >= MAX_ATTEMPTS:
        # Log while request.user is still the user — logout() clears it.
        AuditLog.log(
            request.user, "login",
            f"Idle lock: {MAX_ATTEMPTS} failed PIN attempts — session terminated",
            target_type="Session", ip_address=client_ip(request))
        logout(request)  # flushes the session, attempt counter included
        return JsonResponse({"status": "logged_out"})

    request.session[ATTEMPTS_KEY] = attempts
    return JsonResponse({
        "status": "error",
        "error": "Incorrect PIN.",
        "attempts_left": MAX_ATTEMPTS - attempts,
    })
