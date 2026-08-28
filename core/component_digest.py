"""The daily "what is quietly broken" digest.

`PlatformComponent` has recorded every task's outcome since the day it was
written — `last_status`, `last_message`, `error_count`, `last_run_at` — and
nothing has ever sent that anywhere. Every fault found on 2026-08-28 was
already written down in this table and was discovered by a human opening a
page:

  * `scraper_calendar` had said `not configured: no_api_key` for months.
    The earnings blackout in the stock bot cannot fire without that data.
  * The OANDA streamer had never started, so the forex lane was trading on
    fifteen-minute-delayed marks.
  * `FINNHUB_API_KEY` was set to the empty string, which is not the same as
    unset and reads as configured to anything doing a bare presence check.

None of those is subtle. All three were invisible because nothing looks at
the table unless a person does.

WHAT THIS SENDS, AND WHAT IT DELIBERATELY DOES NOT
--------------------------------------------------
A digest that reports everything is a digest nobody reads by week three, so
this reports only what an operator could act on today:

  error      the task raised, or told the gate it failed
  warning    it ran and did not do its job — parsed rows and stored none,
             or was starved of a credential. This is the state that hid the
             calendar for months, and it is the whole reason `warning`
             exists as a third outcome beside success and error.
  silent     enabled, and has not run in `SILENT_AFTER_HOURS`. A beat that
             stopped firing leaves `last_status` frozen at whatever it was
             the last time it worked, so a healthy-looking green row can be
             three weeks stale — the failure mode a status column cannot
             express by itself.
  feeds      any declared quote feed in `never` or `red` (see
             `market_data/feeds.py`). `off` and `idle` are excluded: a feed
             nobody configured, or one whose market is shut, is the system
             working.

NOT reported: components that are switched off. An operator who disabled
something does not need telling about it daily, and a digest that nags
about deliberate choices trains its reader to skip it — which is exactly
how the three real faults above would survive this change too.

Sent through the existing notification path, so it obeys the operator's own
channel preferences rather than inventing a second one.
"""
from __future__ import annotations

import logging

from django.utils import timezone

logger = logging.getLogger(__name__)

#: An enabled component that has not run in this long has stopped, whatever
#: its last_status still says. Twenty-six hours rather than twenty-four so a
#: daily task that drifts by an hour is not reported every morning.
SILENT_AFTER_HOURS = 26

#: Components whose cadence is longer than the digest's own window. Reporting
#: a weekly task as "silent" every day it does not run is noise, and noise is
#: how a digest stops being read.
LONG_CADENCE_KEYS = ("scraper_cot", "brain_consolidation", "backup")


def collect_faults(now=None) -> dict:
    """What is wrong right now, grouped by kind. Never raises.

    Returns {"errors": [...], "warnings": [...], "silent": [...],
             "feeds": [...], "checked": int} where each entry is a small
    dict the renderer can print without knowing which table it came from.
    """
    from datetime import timedelta

    now = now or timezone.now()
    out = {"errors": [], "warnings": [], "silent": [], "feeds": [],
           "checked": 0}

    try:
        from core.platform_control import PlatformComponent
        rows = list(PlatformComponent.objects.filter(is_enabled=True))
    except Exception as e:  # noqa: BLE001 — a digest must never break a beat
        logger.warning("[digest] components unreadable: %s", e)
        rows = []

    out["checked"] = len(rows)
    cutoff = now - timedelta(hours=SILENT_AFTER_HOURS)

    for row in rows:
        entry = {"key": row.key, "name": row.name,
                 "message": (row.last_message or "").strip(),
                 "last_run": row.last_run_at,
                 "errors": row.error_count}
        status = (row.last_status or "").lower()

        # Silence is checked FIRST and reported instead of the status, not
        # beside it. A component that stopped a week ago still carries
        # whatever verdict it earned on its last successful pass, and
        # printing "success — last run 8 days ago" under a heading that
        # says errors is how a digest teaches its reader to distrust it.
        if row.key not in LONG_CADENCE_KEYS and (
                row.last_run_at is None or row.last_run_at < cutoff):
            entry["message"] = (
                "has never run" if row.last_run_at is None
                else f"last ran {_ago(now - row.last_run_at)} ago")
            out["silent"].append(entry)
            continue

        if status == "error":
            out["errors"].append(entry)
        elif status == "warning":
            out["warnings"].append(entry)

    out["feeds"] = _feed_faults(now)
    return out


def _feed_faults(now) -> list:
    """Declared quote feeds that are configured and not delivering.

    `off` and `idle` are excluded deliberately — see the module docstring.
    A feed nobody switched on, and a feed whose market is shut, are both
    the system working as designed.
    """
    try:
        from django.db.models import Max

        from market_data.feeds import FEEDS, state_for
        from market_data.models import LiveQuote

        seen = {}
        for row in (LiveQuote.objects.values("source")
                    .annotate(latest=Max("updated_at"))):
            key = (row["source"] or "").strip()
            if key:
                seen[key] = row["latest"]

        def fresh(key):
            from market_data.feeds import BY_KEY
            spec, stamp = BY_KEY.get(key), seen.get(key)
            if not spec or stamp is None:
                return False
            return (now - stamp).total_seconds() < spec["ages"][0]

        bad = []
        for feed in FEEDS:
            latest = seen.get(feed["key"])
            age = (now - latest).total_seconds() if latest else None
            state, note = state_for(
                feed, latest=latest, age_seconds=age,
                superseder_ok=fresh(feed.get("superseded_by")), now=now)
            if state in ("never", "red"):
                bad.append({"key": feed["key"], "name": feed["label"],
                            "state": state, "message": note,
                            "last_run": latest, "errors": 0})
        return bad
    except Exception as e:  # noqa: BLE001
        logger.warning("[digest] feeds unreadable: %s", e)
        return []


def _ago(delta) -> str:
    hours = int(delta.total_seconds() // 3600)
    if hours < 48:
        return f"{hours}h"
    return f"{hours // 24}d"


def render_digest(faults: dict) -> tuple:
    """(title, body) for the digest, or (None, None) when all is well.

    None rather than a cheerful "all clear": a daily message that is
    usually empty is a daily message that gets filtered, and then the one
    that matters is filtered with it. Silence means healthy here, and the
    health page is where an operator goes to confirm that.
    """
    n = (len(faults["errors"]) + len(faults["warnings"])
         + len(faults["silent"]) + len(faults["feeds"]))
    if not n:
        return None, None

    lines = []

    def section(label, items, verb):
        if not items:
            return
        lines.append(f"{label} ({len(items)})")
        for it in items:
            msg = it["message"] or verb
            lines.append(f"  · {it['name']} — {msg[:140]}")
        lines.append("")

    # Ordered by what an operator can do something about soonest.
    section("NOT DELIVERING", faults["feeds"], "no quotes")
    section("FAILING", faults["errors"], "last run raised")
    section("RAN BUT DID NOTHING", faults["warnings"], "stored nothing")
    section("STOPPED", faults["silent"], "no recent run")

    lines.append(f"{faults['checked']} enabled component(s) checked.")
    title = f"⊙ Sauron: {n} thing(s) need you"
    return title, "\n".join(lines).strip()


def send_component_digest(now=None) -> dict:
    """Send the digest to every operator who has notifications configured.

    Returns a dict the task gate can judge: `sent` counts recipients, and
    `faults` is reported even when nothing was sent, so a run that found
    problems but could not deliver them is distinguishable from a quiet day.
    """
    from django.contrib.auth.models import User

    faults = collect_faults(now)
    title, body = render_digest(faults)
    result = {"faults": (len(faults["errors"]) + len(faults["warnings"])
                         + len(faults["silent"]) + len(faults["feeds"])),
              "checked": faults["checked"], "sent": 0}
    if not title:
        return result

    from alerts.links import page_url
    from alerts.models import Notification

    for user in User.objects.filter(is_active=True, is_staff=True):
        try:
            Notification.create_for_user(
                user, "system", title, body,
                url=page_url("system_health") or "/health/")
            result["sent"] += 1
        except Exception as e:  # noqa: BLE001 — one bad recipient must not
            logger.warning("[digest] could not notify %s: %s",
                           getattr(user, "username", "?"), e)

    # Telegram too, when the operator has it wired: the whole point is that
    # the fault finds them rather than waiting on the inbox.
    try:
        from alerts.channels.telegram_alert import send_telegram
        send_telegram(title, body)
    except Exception as e:  # noqa: BLE001
        logger.debug("[digest] telegram unavailable: %s", e)

    logger.info("[digest] %d fault(s) reported to %d operator(s)",
                result["faults"], result["sent"])
    return result
