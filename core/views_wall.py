"""THE WALL, served at /wall/: the public front door, and the login gateway.

Anyone may read it; a signed-in visitor is sent to the dashboard. Every
figure on it is a count out of core.wall_facts (cached, fenced, never
raising), the session pills are clock arithmetic, the ring is the beat
schedule read at render time, and the latest steps and the bench are the
Book's own: its newest milestones and the titles of its work in progress.
Nothing here reads the database on a warm request.

The page renders WITHOUT the request's context processors (2026-10-08).
Rendered through `render()`, the front door paid for every panel of the
dashboard's shell: forty-odd queries per visit, most of them on live
quotes an anonymous visitor is never shown. The Book has rendered this
way since 2026-09-27; the Wall now does too. The template receives the
request as a plain value, for the absolute address of its card image
({% static_abs %}), the canonical URL for its og:url (the path alone:
the og:url once printed request.build_absolute_uri, path AND query
string, so any visitor could put words of their choosing on the public
page — 2026-10-14, review), and the CSRF token by name, for the three
login forms it carries ({% csrf_token %} reads `csrf_token`, and
get_token() is what makes the middleware set the cookie).

Every reader this view calls is fenced on its own, so one of them failing
costs its part of the page and never the door: a schedule that cannot be
read draws an empty ring, a session clock that throws leaves the pill row
empty, and a road or a bench the Book cannot read shows the door to the
Book alone.

Read-only: no write, no broker, no order, no secret.
"""
import logging

from django.http import HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect
from django.template.loader import render_to_string

from core import leak_walk
from core.day_of_sauron import safe_page_scheme
from core.views_book import bench_titles, latest_steps
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
    """/wall/ — the public front door. A signed-in visitor goes home.

    A Telegram button's link (2026-10-24) reaches the Wall as `next` when
    its reader is not signed in: the login form carries it back, and a
    signed-in visitor goes straight to it. Only the two id-only shapes of
    alerts.links.DEEP_LINK_PATHS are echoed; any other `next` is dropped,
    so no word of the query string reaches this public page, and the
    leak walk reads the page without the one that is."""
    from alerts.links import deep_link_next
    login_next = deep_link_next(request.GET.get("next"))
    if request.user.is_authenticated:
        return redirect(login_next or "dashboard")
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
        # The bench (2026-10-31): the Book's work in progress, by title,
        # read at render time and never raising.
        "bench": bench_titles(),
        # For {% static_abs %} alone: no context processor runs.
        "request": request,
        # The og:url: the page's own path, never the visitor's query string.
        "canonical_url": request.build_absolute_uri(request.path),
        # For the three {% csrf_token %} of the login and PIN forms.
        "csrf_token": get_token(request),
        # Where the login form returns (2026-10-24): a Telegram button's
        # page, id-only, or "" for the intro.
        "login_next": login_next,
    }
    body = render_to_string("landing/the_wall.html", context)
    # THE LEAK WALK (2026-10-14, core/leak_walk.py): an answer that carries
    # one of the operator's private terms is not sent; a placeholder goes
    # out and staff is told. The request goes along so the host the visitor
    # typed is not read as the page's. Fenced: a walk that raises publishes
    # the page.
    #
    # The `next` echoed into the login form is the visitor's too (review,
    # 2026-10-31): its digits are whatever the address carried, so it is
    # blanked from the text walked, never from the page served. Read as the
    # page's, a guessed digit run put there came back as the placeholder or
    # as the page: a verdict on the guess, and a staff incident anyone
    # could raise.
    walked = body.replace(login_next, " ") if login_next else body
    held = leak_walk.withhold_if_private("wall", walked, request)
    if held is not None:
        return held
    return HttpResponse(body)
