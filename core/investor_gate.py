"""The investor gate — the narrowest citizenship on the platform.

An investor login exists to SEE one funded account's book, never to
touch anything. This middleware is where that promise is kept, and it is
written as a DENY-BY-DEFAULT allowlist on purpose: a blocklist of
today's dangerous routes rots the day a new page ships, and the pages
this platform ships next are trading pages. An investor session may
reach exactly:

    /investor/           the panel
    /investor/live/      the panel's own live refresh
    /logout/             the way out

Everything else — the dashboard, the APIs, the admin, the static of an
idea — answers with a redirect to the panel. Not a 403: an investor who
pastes a dashboard URL from an email is not an attacker, they are lost,
and the panel is where lost investors go.

A REVOKED access (is_active=False) is logged out at the gate itself. No
half-revoked state exists: the row's boolean is the entire story.

Placement: after AuthenticationMiddleware (needs request.user), before
the idle lock (an investor has no PIN and no business meeting one).
Static files never reach this — WhiteNoise sits far earlier in the
stack.
"""
import logging

from django.contrib.auth import logout
from django.shortcuts import redirect

logger = logging.getLogger(__name__)

ALLOWED_PREFIXES = ("/investor/",)
ALLOWED_EXACT = ("/logout/",)

# The answer when the row itself cannot be read. Distinguishable from
# None on purpose: None means "not an investor, wave them through", and
# a database hiccup must never be promoted into full platform access for
# a login that might be an outsider. Unreadable fails CLOSED.
UNREADABLE = object()


def investor_access_for(user):
    """The InvestorAccess row for this user, None, or UNREADABLE.

    None for anonymous users and regular operators; the row (active or
    revoked) for investors; UNREADABLE when the question itself failed —
    the three cases the gate treats differently are separated by the
    CALLER, not here.
    """
    if not getattr(user, "is_authenticated", False):
        return None
    try:
        return getattr(user, "investor_access", None)
    except Exception:  # noqa: BLE001 — an unreadable row must not 500 auth
        logger.error("investor access unreadable for %s", user.pk,
                     exc_info=True)
        return UNREADABLE


class InvestorGateMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        access = investor_access_for(request.user)
        if access is None:
            return self.get_response(request)
        if access is UNREADABLE:
            # Fail CLOSED, without logout: the session store may be the
            # very thing that is failing, and this login might be an
            # outsider. The wall is the one page that owes nobody data.
            return redirect("/wall/")

        if not access.is_active:
            # Revoked is revoked: the session ends at the gate, and the
            # landing is the public wall like any signed-out visitor.
            logout(request)
            return redirect("/wall/")

        path = request.path
        if path in ALLOWED_EXACT or any(
                path.startswith(p) for p in ALLOWED_PREFIXES):
            return self.get_response(request)
        return redirect("/investor/")
