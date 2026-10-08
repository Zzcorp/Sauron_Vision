"""THE WALL, served at /wall/: the public front door, and the login gateway.

Anyone may read it; a signed-in visitor is sent to the dashboard. Every
figure on it is a count out of core.wall_facts (cached, fenced, never
raising), the session pills are clock arithmetic, the ring is the beat
schedule read at render time and the latest steps are the Book's newest
milestones. Nothing here reads the database on a warm request.

The page renders WITHOUT the request's context processors (2026-10-08).
Rendered through `render()`, the front door paid for every panel of the
dashboard's shell: forty-odd queries per visit, most of them on live
quotes an anonymous visitor is never shown. The Book has rendered this
way since 2026-09-27; the Wall now does too. The template receives the
request as a plain value, for the absolute address of its card image
({% static_abs %}) and the og:url, and the CSRF token by name, for the
three login forms it carries ({% csrf_token %} reads `csrf_token`, and
get_token() is what makes the middleware set the cookie).

Every reader this view calls is fenced on its own, so one of them failing
costs its part of the page and never the door: a schedule that cannot be
read draws an empty ring, a session clock that throws leaves the pill row
empty, and a road the Book cannot read shows the door to the Book alone.

Read-only: no write, no broker, no order, no secret.
"""
import logging

from django.http import HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect
from django.template.loader import render_to_string

from core.day_of_sauron import safe_page_scheme
from core.views_book import latest_steps
from core.wall_facts import market_sessions, wall_facts

logger = logging.getLogger(__name__)


def _fenced(name, reader, default):
    """`reader()`, or `default` when it raises, with one warning that
    names the part of the page and the exception's class, never its
    words: the front door's logs must not carry what a reader choked on."""
    try:
        return reader()
    except Exception as exc:  # noqa: BLE001 — the front door stays open
        logger.warning("the Wall's %s could not be read (%s); rendered "
                       "without it", name, type(exc).__name__)
        return default


def the_wall(request):
    """/wall/ — the public front door. A signed-in visitor goes home."""
    if request.user.is_authenticated:
        return redirect("dashboard")
    wall = wall_facts()
    context = {
        "wall": wall,
        # Not cached with the facts: session state is clock arithmetic, and a
        # five-minute-stale "OPEN" is the kind of small lie this page forbids.
        "sessions": _fenced("session clock", market_sessions, []),
        # The day of Sauron (2026-09-29): the beat schedule read into seven
        # stages for the ring scheme, with the counts above as its facts.
        # Only what the drawing reads reaches an anonymous visitor.
        "day": safe_page_scheme(wall),
        # The latest steps (2026-10-08): the Book's newest four milestones,
        # read off core.book_content at render time and never raising.
        "latest": latest_steps(4),
        # For {% static_abs %} and og:url alone: no context processor runs.
        "request": request,
        # For the three {% csrf_token %} of the login and PIN forms.
        "csrf_token": get_token(request),
    }
    return HttpResponse(render_to_string("landing/the_wall.html", context))
