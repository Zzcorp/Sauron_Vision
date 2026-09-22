"""probe_routes — walk every argument-free URL as a logged-in superuser and
say, in three states, which pages answer.

WHY THIS EXISTS. On 2026-09-13 two pages answered 404 for a day and "the only
way to discover it was probing the public site route by route from outside"
(dashboard/oculus._cycle_forge). On 2026-09-23 the operator asked whether
every page was "fully operational", and the honest answer was a measurement
instead of an opinion: 305 URL patterns, 277 named routes, 34 of them touched
by any test, 243 never. The suite proves the consistency of what it covers.
It cannot see a page that renders 500.

WHAT IT DOES. GETs every route whose pattern takes no argument, as the first
active superuser, with the host the settings already allow, and buckets each
answer:

    ok         2xx, 3xx, or 405 — the page rendered, redirected, or is
               POST-only (a GET on a require_POST view answers 405, which
               proves the route exists and refuses the method: a pass)
    forbidden  403 — reachable, refused to this user; a fact, not a fault
    missing    404 — the route is wired to nothing that answers
    broken     5xx — the page raised

and two it does NOT probe, counted rather than hidden:

    skipped    patterns with a converter (<int:pk>) — need a fixture
    excluded   routes whose NAME says they mutate (run, toggle, save,
               delete, arm, flatten, ...) — a GET must never be the thing
               that finds out a view has side effects. The names are
               printed so the exclusion can be audited.

It stores the tally in the cache under PROBE_KEY so the forge can show it,
with the time it ran; the forge reads "never run" as a dash, not a zero.

WHAT IT REFUSES. To run when ALLOWED_HOSTS is empty (every GET would be a
400 that says nothing about the page), or when no active superuser exists
(every page would redirect to login and the tally would be 270 "ok"s that
mean nothing). Both are reported as "could not probe", the third state.

READ-ONLY BY CONSTRUCTION — GET only, no external service, no balance
printed — and therefore web-runnable on the ops lane.

    python manage.py probe_routes
    python manage.py probe_routes --show
"""
from __future__ import annotations

import re
import time

from django.core.management.base import BaseCommand

PROBE_KEY = "forge:route_probe"
PROBE_TTL = 7 * 24 * 3600

#: A route whose name contains one of these is not GET-probed. The list is
#: a net, not a proof: a GET view with side effects and an innocent name is
#: exactly the defect this command would otherwise trip, so the skipped
#: names are printed for a human to check against the view code.
MUTATING = re.compile(
    r"(run|toggle|disconnect|logout|delete|reset|arm|kill|flatten|forget|"
    r"clear|save|create|update|set_|apply|rollback|close|cancel|withdraw|"
    r"deposit|transfer|promote|demote|activate|execute|preview)")

OK_STATUSES = frozenset({200, 201, 202, 204, 301, 302, 303, 304, 307, 308,
                         405})


def free_routes():
    """[(name, path)] for every pattern with no converter, in URL order.

    Walks the resolver the way Django itself does; a nested include is
    flattened with its prefix. Websocket routing lives in a different
    resolver and is not a page.
    """
    from django.urls import URLPattern, URLResolver, get_resolver
    out = []

    def walk(patterns, prefix):
        for p in patterns:
            if isinstance(p, URLResolver):
                walk(p.url_patterns, prefix + str(p.pattern))
            elif isinstance(p, URLPattern):
                route = prefix + str(p.pattern)
                if p.pattern.converters or "<" in route or "(" in route:
                    out.append((p.name or "", route, False))
                else:
                    out.append((p.name or "", route, True))

    walk(get_resolver().url_patterns, "")
    return out


def probe(client, host: str):
    """Walk and bucket. Returns the tally dict the command prints and stores."""
    tally = {"ok": [], "forbidden": [], "missing": [], "broken": [],
             "skipped": [], "excluded": []}
    for name, route, probeable in free_routes():
        label = name or route
        if not probeable:
            tally["skipped"].append(label)
            continue
        if MUTATING.search(name or ""):
            tally["excluded"].append(label)
            continue
        path = "/" + route.lstrip("^").lstrip("/")
        try:
            status = client.get(path, HTTP_HOST=host, follow=False).status_code
        except Exception as exc:  # noqa: BLE001 — a raise IS the finding
            tally["broken"].append(f"{label} ({type(exc).__name__}: {exc})")
            continue
        if status in OK_STATUSES:
            tally["ok"].append(label)
        elif status == 403:
            tally["forbidden"].append(label)
        elif status == 404:
            tally["missing"].append(label)
        elif status >= 500:
            tally["broken"].append(f"{label} ({status})")
        else:
            tally["ok"].append(f"{label} ({status})")
    return tally


class Command(BaseCommand):
    help = ("GET every argument-free route as a superuser and report which "
            "pages answer, which are missing, and which raise. Read-only.")

    def add_arguments(self, parser):
        parser.add_argument("--show", action="store_true",
                            help="List every route in every bucket, not only "
                                 "the failing ones.")

    def handle(self, *args, **opts):
        from django.conf import settings
        from django.contrib.auth.models import User
        from django.core.cache import cache
        from django.test import Client

        w = self.stdout.write
        hosts = list(getattr(settings, "ALLOWED_HOSTS", []) or [])
        host = next((h for h in hosts if h and not h.startswith(".")), "")
        if not host:
            w("COULD NOT PROBE — ALLOWED_HOSTS names no host, so every GET "
              "would answer 400 and say nothing about the page.")
            cache.set(PROBE_KEY, {"state": "could_not", "why": "no host",
                                  "at": time.time()}, PROBE_TTL)
            return
        user = (User.objects.filter(is_superuser=True, is_active=True)
                .order_by("pk").first())
        if user is None:
            w("COULD NOT PROBE — no active superuser exists, so every page "
              "would redirect to login and 270 'ok's would mean nothing.")
            cache.set(PROBE_KEY, {"state": "could_not",
                                  "why": "no superuser", "at": time.time()},
                      PROBE_TTL)
            return

        client = Client()
        client.force_login(user)
        started = time.time()
        tally = probe(client, host)
        took = time.time() - started

        w("=" * 70)
        w(f"ROUTE PROBE — as {user.username} — host {host} — {took:.1f}s")
        w("=" * 70)
        for bucket in ("ok", "forbidden", "missing", "broken", "skipped",
                       "excluded"):
            rows = tally[bucket]
            w(f"  {bucket:<10} {len(rows):>4}")
            if rows and (opts["show"] or bucket in ("missing", "broken")):
                for r in rows:
                    w(f"      {r}")
        w("=" * 70)
        n_probed = (len(tally["ok"]) + len(tally["forbidden"])
                    + len(tally["missing"]) + len(tally["broken"]))
        if tally["broken"] or tally["missing"]:
            w(f"{len(tally['broken'])} page(s) raise and "
              f"{len(tally['missing'])} answer 404, out of {n_probed} probed.")
        else:
            w(f"Every one of the {n_probed} probed routes answers. "
              f"{len(tally['skipped'])} parameterised and "
              f"{len(tally['excluded'])} mutating routes were NOT probed — "
              f"that is a count, not a pass.")
        cache.set(PROBE_KEY, {
            "state": "ran", "at": started, "host": host, "as": user.username,
            "counts": {k: len(v) for k, v in tally.items()},
            "missing": tally["missing"][:50], "broken": tally["broken"][:50],
        }, PROBE_TTL)
