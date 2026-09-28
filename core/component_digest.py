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
  silent     enabled, and quiet for longer than its own beat allows. A beat
             that stopped firing leaves `last_status` frozen at whatever it
             was the last time it worked, so a healthy-looking green row can
             be three weeks stale — the failure mode a status column cannot
             express by itself. "Longer than its beat allows" is read off
             config/celery.py (beat_periods), a crontab's period being the
             widest gap between two of its fire times: anything that beats
             at least once a day keeps `SILENT_AFTER_HOURS`, as before; a
             longer beat gets 1.2 periods plus two hours — a weekly one
             eight and a half days, a monthly one 37. A component no beat
             entry writes — a switch, a per-event gate — is never
             "stopped"; it is still reported the day it fails or warns. A
             beat entry the map cannot place (a renamed task left on the
             schedule) is reported itself, as the "Digest cadence map",
             since the component behind it can no longer be judged. A row
             that has never run is judged from the day it was seeded, as
             if that were its last run, so a monthly task seeded mid-month
             is not called stopped before its first beat has had its
             chance.
  feeds      any declared quote feed in `never` or `red` (see
             `market_data/feeds.py`). `off` and `idle` are excluded: a feed
             nobody configured, or one whose market is shut, is the system
             working.

NOT reported: components that are switched off. An operator who disabled
something does not need telling about it daily, and a digest that nags
about deliberate choices trains its reader to skip it — which is exactly
how the three real faults above would survive this change too.

WHERE IT GOES
-------------
The bell of every active staff user, and the Telegram chat in
TELEGRAM_CHAT_ID when TELEGRAM_BOT_TOKEN is set too — the two places it was
always addressed to (until 2026-09-26 a TypeError kept every copy out of the
bell: see send_component_digest). It is not a bot event, so neither the bot-alert switch nor
quiet hours hold it back, exactly as before 2026-09-26. (This paragraph used
to say it obeyed the operator's channel preferences; it never read them.)

WHAT THE MORNING DIGEST OF 2026-09-26 TAUGHT
--------------------------------------------
It sent nineteen items and one of them was a fault: the calendar's macro
half, FMP answering 402. The rest were this module's own false alarms:

  * five WEEKLY beats judged on the daily window — the weekly review, the
    optimizer, the Monday plan, the meta-allocator and the pattern miner
    read "stopped" five or six mornings out of seven. Each component is now judged
    against its own beat.
  * switches and per-event gates — the master switch, the AI pre-trade
    gate, generator auto-research, the event engine — read "has never run",
    which is true of a switch forever. Nothing schedules them, so nothing
    can be late.
  * the broker sync, the one row of three walks, read "ran and produced
    nothing" from the IBKR and Saxo walks that had nothing to read. An idle
    pass writes nothing now (core.task_gate.guarded_task).

A digest wrong eighteen times in nineteen is a digest nobody reads, and the
nineteenth goes unread with it. It now speaks the house style: one emoji and
a bold title on Telegram, one fault per line, English words, names not keys.
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

#: How long past its own beat a component may be quiet before it is called
#: stopped. Anything that beats at least once a day keeps the daily floor,
#: SILENT_AFTER_HOURS, exactly as before 2026-09-26: a task at 03:00 UTC
#: that misses one run is in the next 07:00 digest, 28 hours on. A longer
#: beat gets SILENT_PERIODS of its period plus SILENT_SLACK_HOURS — a
#: weekly one 203.6 hours (eight and a half days), a monthly one 894.8 (37
#: days). The fifth of a period is one late beat; the two hours are one
#: slow run.
SILENT_PERIODS = 1.2
SILENT_SLACK_HOURS = 2.0

#: The house Telegram style: a message stops near twenty-five lines and
#: points at the page that lists everything.
MAX_LINES = 25

#: One fault's words are cut here, so a runaway traceback cannot push every
#: other fault off the phone screen.
MESSAGE_CHARS = 140

#: The sections, in the order an operator can act on them soonest: a dead
#: feed, a failing task, one that ran and did nothing, one that stopped.
#: (bucket, heading, the words when a fault carries none of its own)
SECTIONS = (
    ("feeds", "Not delivering quotes", "no quotes"),
    ("errors", "Failing", "the last run raised"),
    ("warnings", "Ran but did nothing", "stored nothing"),
    ("silent", "Stopped running", "no recent run"),
)

#: The one emoji the Telegram title leads with. The bell keeps the
#: platform's own ⊙, which a phone's font may draw as a box.
TELEGRAM_MARK = "⚠️"


def beat_periods(unresolved=None):
    """{component key: hours between its beat runs}, off config/celery.py.

    The schedule already states how often every component should move;
    this reads it rather than keeping a second list that drifts. Each beat
    entry's task is resolved to the function celery runs, and the key is
    the one `core.task_gate.guarded_task` stamped on it (`component_key`).
    Where several entries write one row (the three broker walks, the bot
    tick and the reconcile), the most frequent beat sets the period — the
    row moves whenever any of them runs. An entry whose task the gate does
    not wrap (this digest, the brain loop, the Saxo session keeper) names
    no component and is skipped.

    A component that appears nowhere here is a switch, a per-event gate or
    a step another task calls: nothing schedules it, so nothing can be
    late, and collect_faults never calls it stopped.

    AN ENTRY THE MAP CANNOT PLACE IS NEVER DROPPED IN SILENCE (2026-09-26):
    a task no worker knows — a function renamed with its old name left on
    the beat, which the beat keeps sending and the worker keeps discarding
    while the row it wrote freezes at its last verdict — an entry that
    raised, or a gated task whose schedule states no period this can read.
    The component behind such an entry falls out of the map, so it can no
    longer be called stopped; the entry itself is the fault. Each one is
    logged at WARNING and, when a list is passed as `unresolved`, added to
    it in words for collect_faults to report.

    None when the schedule itself cannot be read — collect_faults says so
    out loud rather than judging nobody in silence.
    """
    try:
        from config.celery import app
        schedule = dict(app.conf.beat_schedule or {})
    except Exception as e:  # noqa: BLE001 — a digest must never break a beat
        logger.warning("[digest] beat schedule unreadable: %s", e)
        return None

    def unplaced(entry_name, why):
        logger.warning("[digest] beat entry %s %s", entry_name, why)
        if unresolved is not None:
            unresolved.append(f"beat entry {entry_name} {why}")

    out = {}
    for entry_name, entry in schedule.items():
        try:
            task_name = str(entry.get("task") or "")
            task = _beat_task(app, task_name)
            key = _component_key_of(task) if task is not None else None
            hours = _period_hours(entry.get("schedule"))
        except Exception as e:  # noqa: BLE001 — one odd entry is not the map
            unplaced(entry_name, f"could not be read ({e})")
            continue
        if task is None:
            unplaced(entry_name, f"names a task no worker knows ({task_name})")
        elif key and not hours:
            unplaced(entry_name, "states no period the digest can read")
        elif key:
            out[key] = min(hours, out.get(key, hours))
    return out


def _beat_task(app, name: str):
    """The task a beat entry names, or None when nothing answers to that
    name. Through the module path first — a task imported from its module
    is celery's proxy, whose `.__wrapped__` and `.run` are the gate's
    wrapper — then the app's registry for a name that is not one."""
    import importlib

    task = None
    module, _, attr = name.rpartition(".")
    if module:
        try:
            task = getattr(importlib.import_module(module), attr, None)
        except Exception as e:  # noqa: BLE001
            logger.warning("[digest] %s not importable: %s", name, e)
    if task is None and name:
        task = app.tasks.get(name)
    return task


def _component_key_of(task):
    """The component a beat task writes, or None when the gate does not
    wrap it (this digest, the brain loop, the Saxo session keeper)."""
    for fn in (task, getattr(task, "__wrapped__", None),
               getattr(task, "run", None)):
        key = getattr(fn, "component_key", None)
        if isinstance(key, str) and key:
            return key
    return None


def _period_hours(schedule):
    """Hours between two runs of one beat entry — the WIDEST gap, so an
    uneven beat is judged by its slowest stretch — or None for a schedule
    that states no period this can read (a solar event, say).

    A number or a timedelta is its own period. A crontab says WHEN, not
    how often, so its fire times are laid out over one week and the widest
    gap between two of them, round the week's end, is the period
    (2026-09-26): hour="*/4" is four hours, minute="*/15"
    fifteen minutes, 03:00 daily 24 hours, Saturday 10:00 168, a weekday
    22:00 72 (Friday night to Monday night). A restricted day of the month
    is read in whole days over a 31-day month, the 1st alone being 744
    hours; a restricted month is a year.
    """
    from datetime import timedelta

    if schedule is None or isinstance(schedule, bool):
        return None
    if isinstance(schedule, (int, float)):
        return float(schedule) / 3600.0 if schedule > 0 else None
    if isinstance(schedule, timedelta):
        secs = schedule.total_seconds()
        return secs / 3600.0 if secs > 0 else None
    from celery.schedules import crontab
    from celery.schedules import schedule as interval
    if isinstance(schedule, crontab):
        if len(schedule.month_of_year) < 12:
            return 8784.0
        if len(schedule.day_of_month) < 31:
            days = sorted(schedule.day_of_month)
            gaps = [b - a for a, b in zip(days, days[1:])]
            return 24.0 * max(gaps + [31 - days[-1] + days[0]])
        week = 7 * 24 * 60
        marks = sorted(d * 1440 + h * 60 + m
                       for d in schedule.day_of_week
                       for h in schedule.hour
                       for m in schedule.minute)
        if not marks:
            return None
        gaps = [b - a for a, b in zip(marks, marks[1:])]
        return max(gaps + [week - marks[-1] + marks[0]]) / 60.0
    if isinstance(schedule, interval):
        secs = schedule.run_every.total_seconds()
        return secs / 3600.0 if secs > 0 else None
    return None


def silent_window_hours(key, periods):
    """Hours of quiet after which an enabled component is reported as
    stopped — or None when it cannot be: nothing on the beat writes it, or
    it is one of LONG_CADENCE_KEYS, which stays an explicit override.

    A beat of a day or less keeps SILENT_AFTER_HOURS. The 1.2 periods plus
    two hours of a longer beat would give a daily task 30.8 hours, and a
    daily task that runs between midnight and five and misses one run
    would then reach the operator a morning later than before
    (2026-09-26)."""
    if key in LONG_CADENCE_KEYS:
        return None
    period = (periods or {}).get(key)
    if not period:
        return None
    if period <= 24:
        return float(SILENT_AFTER_HOURS)
    return max(float(SILENT_AFTER_HOURS),
               SILENT_PERIODS * period + SILENT_SLACK_HOURS)


def _cadence_words(hours) -> str:
    """The beat in the operator's words, so a "stopped" line shows the
    rhythm it was judged against."""
    if hours >= 24 * 28:
        return "monthly"
    if hours >= 168 * 0.9:
        return "weekly"
    if hours >= 24 * 0.9:
        return "daily"
    if hours >= 1:
        n = round(hours)
        return "hourly" if n == 1 else f"every {n} hours"
    n = max(1, round(hours * 60))
    return "every minute" if n == 1 else f"every {n} minutes"


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
    unplaced = []
    periods = beat_periods(unresolved=unplaced) if rows else {}
    if periods is None:
        # The beat could not be read, so no row could be judged for
        # silence. Said out loud: a digest that quietly lost its silence
        # check reads exactly like a healthy platform.
        out["warnings"].append({
            "key": "beat_schedule", "name": "Digest cadence map",
            "message": ("the beat schedule could not be read, so no "
                        "component was checked for silence today"),
            "last_run": None, "errors": 0})
        periods = {}
    for why in unplaced:
        # One beat entry the map could not place (beat_periods): the
        # component behind it can no longer be judged for silence, so the
        # entry itself is reported — a renamed task left on the beat is
        # sent and discarded every time it fires.
        out["warnings"].append({
            "key": "beat_schedule", "name": "Digest cadence map",
            "message": why, "last_run": None, "errors": 0})

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
        #
        # Judged against the component's OWN beat (2026-09-26), and only
        # when a beat entry writes it: a switch or a per-event gate has no
        # rhythm to fall behind. A row that has never run is judged from
        # the day it was seeded, as if that were its last run.
        window = silent_window_hours(row.key, periods)
        since = row.last_run_at or getattr(row, "created_at", None)
        if window is not None and (
                since is None or since < now - timedelta(hours=window)):
            how = _cadence_words(periods[row.key])
            entry["message"] = (
                f"has never run ({how})" if row.last_run_at is None
                else f"last ran {_ago(now - row.last_run_at)} ago ({how})")
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
        # The SAME verdict the health page renders — see
        # market_data.feeds.feed_states. When these were separate loops the
        # digest could report a feed as dead and the page it links to
        # reported it as fine, which is worse than either being wrong alone.
        from market_data.feeds import feed_states

        bad = []
        for row in feed_states(now):
            if row["state"] in ("never", "red"):
                bad.append({"key": row["source"], "name": row["label"],
                            "state": row["state"], "message": row["note"],
                            "last_run": row["latest"], "errors": 0})
        return bad
    except Exception as e:  # noqa: BLE001
        logger.warning("[digest] feeds unreadable: %s", e)
        return []


def _ago(delta) -> str:
    hours = int(delta.total_seconds() // 3600)
    if hours < 48:
        return f"{hours}h"
    return f"{hours // 24}d"


def _clip(text, limit: int = MESSAGE_CHARS) -> str:
    """One line, at most `limit` characters, an ellipsis where it was cut."""
    one = " ".join(str(text or "").split())
    return one if len(one) <= limit else one[:limit - 1].rstrip() + "…"


def render_digest(faults: dict) -> tuple:
    """(title, body) for the digest, or (None, None) when all is well.

    None rather than a cheerful "all clear": a daily message that is
    usually empty is a daily message that gets filtered, and then the one
    that matters is filtered with it. Silence means healthy here, and the
    health page is where an operator goes to confirm that.

    THE HOUSE STYLE (2026-09-26), in English: the title counts the faults
    in words ("⊙ Sauron — 1 thing needs attention"); each section names
    its count; one fault per line, "• <name> — <what it said>", the words
    on one line and cut at MESSAGE_CHARS (mark_run scrubbed them of
    secrets when it stored them); the component's NAME, never its key,
    where a name exists; at most MAX_LINES lines, the rest counted on one
    "+N more on /health/" line; and a closing line that says how much was
    checked. Telegram gets this same text, escaped, under one emoji
    (_send_telegram).
    """
    n = sum(len(faults.get(bucket) or []) for bucket, _h, _w in SECTIONS)
    if not n:
        return None, None

    lines, hidden = [], 0
    room = MAX_LINES - 3  # the blank, a "+N more" and the closing line
    for bucket, heading, fallback in SECTIONS:
        items = faults.get(bucket) or []
        if not items:
            continue
        head = ([""] if lines else []) + [f"{heading} ({len(items)})"]
        if len(lines) + len(head) >= room:
            hidden += len(items)
            continue
        lines.extend(head)
        for i, it in enumerate(items):
            if len(lines) >= room:
                hidden += len(items) - i
                break
            name = it.get("name") or it.get("key") or "?"
            lines.append(f"• {name} — {_clip(it.get('message') or fallback)}")

    lines.append("")
    if hidden:
        lines.append(f"+{hidden} more on /health/")
    checked = int(faults.get("checked") or 0)
    lines.append(f"All other checks passed ({checked} enabled "
                 f"component{'' if checked == 1 else 's'}).")
    title = (f"⊙ Sauron — {n} thing needs attention" if n == 1
             else f"⊙ Sauron — {n} things need attention")
    return title, "\n".join(lines)


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

    from alerts.models import Notification

    # `alerts.links.page_url` takes a route AND an argument, and this called
    # it with the route alone: the TypeError landed in the per-recipient
    # except below, and not one digest ever reached the bell — only
    # Telegram (found 2026-09-26). The health page takes no argument.
    url = _health_url()
    for user in User.objects.filter(is_active=True, is_staff=True):
        try:
            Notification.create_for_user(user, "system", title, body,
                                         url=url)
            result["sent"] += 1
        except Exception as e:  # noqa: BLE001 — one bad recipient must not
            logger.warning("[digest] could not notify %s: %s",
                           getattr(user, "username", "?"), e)

    # Telegram too, when the operator has it wired: the whole point is that
    # the fault finds them rather than waiting on the inbox.
    try:
        result["telegram"] = _send_telegram(title, body)
    except Exception as e:  # noqa: BLE001
        logger.warning("[digest] telegram send failed: %s", e)
        result["telegram"] = False

    logger.info("[digest] %d fault(s) reported to %d operator(s)",
                result["faults"], result["sent"])
    return result


def _health_url() -> str:
    """The health page's path — where every digest row links."""
    try:
        from django.urls import reverse
        return reverse("system_health")
    except Exception:  # noqa: BLE001
        return "/health/"


def _send_telegram(title: str, body: str) -> bool:
    """The digest on Telegram, to TELEGRAM_CHAT_ID — the chat it has always
    gone to — as escaped HTML under one emoji.

    Not alerts.channels.telegram_alert.send_telegram, which posted legacy
    Markdown until the house-style batch of 2026-09-26: there a single
    underscore in a fault's own words
    ("platform_disabled", "no_api_key") is a 400 "can't parse entities"
    and the whole digest is dropped — the failure that kept the bot's
    fills off Telegram for a month (bot_program.notifications, fixed
    2026-09-26). The same rendering as that fix: a bold title led by the
    mark, every field escaped; the bell's ⊙ stays in the bell. A refusal
    is logged at WARNING with Telegram's own words.
    """
    import os
    from html import escape

    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not (token and chat_id):
        logger.info("[digest] Telegram not configured "
                    "(TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID unset)")
        return False
    import requests

    head = escape(title.lstrip("⊙").strip())
    text = f"<b>{TELEGRAM_MARK} {head}</b>\n\n{escape(body or '')}"
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
              "disable_web_page_preview": True},
        timeout=10,
    )
    if not r.ok:
        logger.warning("[digest] telegram refused (%s): %s",
                       getattr(r, "status_code", "?"),
                       str(getattr(r, "text", ""))[:200])
    return bool(r.ok)
