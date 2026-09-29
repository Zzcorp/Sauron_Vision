"""The home page's live layer: a day of Sauron, right now.

core.day_of_sauron reads the beat schedule into seven stages (SEE, THINK,
DECIDE, ACT, WATCH, TELL, LEARN) and never touches the database. This
module adds what the database knows about each stage at this minute —
which of its beat entries ran, when, whether it failed, and the counts a
stage produced today — and serves it as JSON for static/js/sv-day-live.js
to paint over the ring (window.SVDay.current.setLive), the seven tiles and
the 24-hour strip on /command/.

State per beat entry comes from the PlatformComponent row the task gate
wraps it in (core.day_of_sauron.beat_components), judged against THAT
ENTRY's cadence the way the system map judges a component
(dashboard.views_topology._component_state, whose thresholds are reused
here): off / broken / silent / idle / stale / live, stale at 2.5x the
cadence. An entry the gate does not wrap (the brain loop, the Saxo session
keeper, the digest) is 'quiet': nothing records its runs, and the page says
so rather than inventing a dot. One query reads every component row.

Every metric group is fenced on its own: a missing table, an empty one or a
builder that raises reads 0 / "unknown" and logs at WARNING — never a 500
on the home page, and never a silent blank. The rule
tests/test_command_metrics.py pins for the tab bar, kept here.

Under /api/ on purpose: the idle lock answers 423 to a locked tab's poll
(core.idle_lock._wants_json) instead of redirecting a fetch() to the lock
page, and the page stops polling on it until the tab is visible again.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from types import SimpleNamespace

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Max, Q, Sum
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from core.day_of_sauron import STAGES, beat_components, day_scheme

logger = logging.getLogger(__name__)

#: The vocabulary a stage, a cluster and the beat speak on the page.
STAGE_STATES = ("live", "stale", "off", "quiet", "broken")

#: A quote younger than this is "a live price" for the SEE tile.
FRESH_QUOTE_S = 15 * 60
#: The bot tick beats every 5 min; a heartbeat older than this is the
#: DECIDE tile's stale reading (bot_program/asset_engine/safety.py
#: HEARTBEAT_STALE_SECONDS reads the same 30 min).
HEARTBEAT_STALE_S = 1800
#: A broker reading older than this is stale (capital_truth's own
#: TRACKING_FRESH_SECONDS, the freeze the entry path applies).
BROKER_STALE_S = 3600
#: The two bands the 24-hour strip shades, in minutes of the UTC day. The
#: US band is read from core.constants.MARKET_SESSIONS (us_session());
#: this is only its fallback.
US_SESSION = (13 * 60 + 30, 20 * 60)
NIGHT_OF_LEARNING = (2 * 60, 7 * 60)

_COMPONENT_FIELDS = ("key", "is_enabled", "last_run_at", "last_status",
                     "last_message", "run_count", "error_count")

#: Beat entries whose pass can be IDLE: with nothing to do they return
#: {"idle": ...} and the gate writes nothing on the row they share
#: (core.task_gate.guarded_task, bot_program.alarm.alarm_task). The row's
#: rhythm is then its other writer's, and judging it against the idle
#: writer's 15 s read the alarm's row stale 93% of the time (review,
#: 2026-09-29). The IBKR and Saxo walks go idle with no account or no
#: session; the alarm's poll with nothing to read.
IDLE_WRITERS = frozenset({"poll-telegram-alarm", "sync-broker-account",
                          "sync-saxo-accounts"})

#: A row judged against a beat this short or shorter is still given this
#: long before it reads stale: a 15 s poller on a busy fast queue can lag
#: a minute without being stopped.
STALE_FLOOR_S = 5 * 60


# ── words ────────────────────────────────────────────────────────────────

def _ago(seconds) -> str:
    """'just now', '2 min ago', '3 h ago', '2 d ago' — the Eye's tenses
    (bot_program.telegram_eye.ago), on a number of seconds."""
    if seconds is None:
        return "never"
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 48 * 3600:
        return f"{int(seconds // 3600)} h ago"
    return f"{int(seconds // 86400)} d ago"


def _age(at, now):
    return None if at is None else max(0.0, (now - at).total_seconds())


def _start_of_today(now):
    """00:00 UTC — settings.TIME_ZONE is UTC, and every 'today' here is
    the operator's UTC day, the clock the beat and the strip read."""
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _group(name, builder, fallback):
    """One metric group inside its own fence. A group that cannot be
    measured reads its fallback AND says so in the log; the page never
    500s over one table and never prints a confident zero in silence."""
    try:
        return builder()
    except Exception as e:  # noqa: BLE001 — the fence is the point
        logger.warning("day live: %s unavailable: %s", name, e, exc_info=True)
        return fallback


# ── the state of one entry, one stage, the beat ──────────────────────────

def _stale_after_s(widest):
    """Seconds of quiet after which a row reads stale, from the WIDEST gap
    of the beat that writes it (core.day_of_sauron.widest_gap, the digest's
    own reading of a schedule).

    The tighter of the system map's 2.5 periods and the daily digest's
    silence window (core.component_digest.silent_window_hours: 26 h for a
    beat of a day or less, 1.2 periods plus 2 h beyond), with a five-minute
    floor. A daily snapshot 31 h old read green under 2.5 periods (60 h)
    while the digest called it stopped at 26 (review, 2026-09-29).
    None — nothing schedules the row — means it cannot be late."""
    if not widest:
        return None
    from core.component_digest import (SILENT_AFTER_HOURS, SILENT_PERIODS,
                                       SILENT_SLACK_HOURS)
    if widest <= 86400:
        silent = SILENT_AFTER_HOURS * 3600.0
    else:
        silent = max(SILENT_AFTER_HOURS * 3600.0,
                     SILENT_PERIODS * widest + SILENT_SLACK_HOURS * 3600.0)
    return max(STALE_FLOOR_S, min(2.5 * widest, silent))


def _row_state(row, widest, now, paused):
    """(state, age seconds) of ONE component row, in the page's five words.

    A missing row is off: the gate skips a task whose row does not exist
    (core.platform_control.is_component_enabled answers False). `paused` —
    the master switch off or missing — is off too for every row the master
    gates: the gate skips those tasks without touching their rows, which
    then only age, and an operator's deliberate pause read amber on six
    stages (review, 2026-09-29). A warning (ran and stored nothing) reads
    stale, a row that never ran reads quiet, and a row nothing schedules
    can be off or broken but never late."""
    if row is None:
        return "off", None
    age = _age(row["last_run_at"], now)
    if not row["is_enabled"] or paused:
        return "off", age
    status = (row["last_status"] or "").lower()
    if status == "error":
        return "broken", age
    if status == "warning":
        return "stale", age
    if age is None:
        return "quiet", None
    limit = _stale_after_s(widest)
    if limit is not None and age > limit:
        return "stale", age
    return "live", age


def _stage_state(states) -> str:
    """'broken' if any entry is broken, else 'stale' if any is stale or
    silent, else 'off' if every judged entry is off, else 'live' if any is
    live, else 'quiet'. Quiet entries (not gated, or sharing a record
    another entry owns) are not judged; 'idle' — switched on and never ran —
    is judged, so it keeps a stage from reading all-off."""
    judged = [s for s in states if s != "quiet"]
    if "broken" in judged:
        return "broken"
    if any(s in ("stale", "silent") for s in judged):
        return "stale"
    if judged and all(s == "off" for s in judged):
        return "off"
    if "live" in judged:
        return "live"
    return "quiet"


def _run_words(state, newest_age) -> str:
    if state == "off":
        return "switched off"
    if newest_age is None:
        return "never ran"
    return f"ran {_ago(newest_age)}"


# ── the metric groups: today, cheap, fenced ──────────────────────────────

def _see_metrics(now, start):
    from market_data.models import LiveQuote
    from scraping.models import NewsArticle
    news = NewsArticle.objects.filter(scraped_at__gte=start).count()
    fresh = LiveQuote.objects.filter(
        updated_at__gte=now - timedelta(seconds=FRESH_QUOTE_S)).count()
    # The newest quote, off LiveQuote: one row per instrument, a small
    # table. This read MAX(timestamp) over every stored bar before
    # (review, 2026-09-29): PriceData carries no lone timestamp index, so
    # that was a full scan of the bar table per poll per open tab.
    newest = LiveQuote.objects.aggregate(m=Max("updated_at"))["m"]
    age = _age(newest, now)
    out = [[news, "news items scraped today"],
           [fresh, "instruments with a price under 15 min old"]]
    if age is None:
        out.append([0, "live quotes stored — none yet"])
    else:
        out.append([int(age // 60), "min since the newest live quote"])
    return out


def _think_metrics(now, start):
    from scraping.models import NewsArticle
    from signals.models import Signal
    out = [[Signal.objects.filter(created_at__gte=start).count(),
            "signals raised today"],
           [Signal.objects.filter(is_active=True).count(),
            "signals active now"],
           [NewsArticle.objects.filter(ai_processed_at__gte=start).count(),
            "news items analysed today"]]
    try:
        from brain.models import BrainReport
        out.append([BrainReport.objects.filter(created_at__gte=start).count(),
                    "brain reports today"])
    except Exception as e:  # noqa: BLE001 — the brain is optional here
        logger.warning("day live: brain reports unavailable: %s", e)
    return out


def _decide_metrics(user, now, start):
    from bot_program.asset_models import AssetBotConfig
    from bot_program.asset_engine.safety import heartbeat_age_seconds
    from bot_program.orchestrator_models import OrchestratorEvent
    configs = list(AssetBotConfig.objects.filter(user=user)
                   .values("enabled", "extras"))
    n_on = sum(1 for c in configs if c["enabled"])
    # The freshest tick stamp across the operator's bots (safety
    # .write_heartbeat writes extras["last_tick_at"] every tick).
    ages = []
    for c in configs:
        age = heartbeat_age_seconds(SimpleNamespace(extras=c["extras"]))
        if age is not None:
            ages.append(age)
    # Rejects are exact; allows are SAMPLED (bot_program.orchestrator
    # ._log_decision), so no accept rate is ever derived from these rows.
    rejects = OrchestratorEvent.objects.filter(
        user=user, decision="reject", created_at__gte=start).count()
    out = [[n_on, f"of {len(configs)} bot configs enabled"],
           [rejects, "entries the gate refused today (allows are sampled)"]]
    if ages:
        out.append([int(min(ages) // 60), "min since the freshest bot tick"])
    else:
        out.append([0, "bot ticks recorded — no heartbeat yet"])
    return out


def _act_metrics(user, now, start):
    from bot_program.asset_models import AssetBotTrade
    open_now = Q(status__in=("OPEN", "CLOSE_PENDING"))
    agg = AssetBotTrade.objects.filter(config__user=user).aggregate(
        opened=Count("id", filter=Q(opened_at__gte=start)),
        closed=Count("id", filter=Q(status="CLOSED", closed_at__gte=start)),
        open_live=Count("id", filter=open_now & Q(paper=False)),
        open_paper=Count("id", filter=open_now & Q(paper=True)),
        pending=Count("id", filter=Q(status="CLOSE_PENDING")),
        errors=Count("id", filter=Q(status="ERROR", opened_at__gte=start)),
        graded=Count("id", filter=Q(status="CLOSED", closed_at__gte=start,
                                    realized_r__isnull=False)),
    )
    return agg


def _watch_metrics(user, now, comp_states):
    from django.core.cache import cache
    from bot_program.capital_truth import account_equity
    from bot_program.morgul import SUMMARY_KEY
    out = []
    summary = None
    try:
        summary = cache.get(SUMMARY_KEY)
    except Exception as e:  # noqa: BLE001 — a dead cache is "no run yet"
        logger.warning("day live: morgul summary unreadable: %s", e)
    if isinstance(summary, dict):
        findings = [f for f in summary.get("findings") or []
                    if isinstance(f, dict)]
        out.append([int(summary.get("guards") or 0), "Morgul guards ran"])
        out.append([len(findings), "guard findings standing"])
    else:
        out.append([0, "Morgul guards ran — no run recorded"])
        out.append([0, "guard findings standing"])
    reading = account_equity(user)
    if reading is None:
        out.append([0, "broker readings — none landed yet"])
    else:
        out.append([int(reading["age_seconds"] // 60),
                    "min since the broker's reading"])
    out.append([sum(1 for s in comp_states.values() if s in ("stale", "silent")),
                "components stale"])
    out.append([sum(1 for s in comp_states.values() if s == "broken"),
                "components broken"])
    return out


def _tell_metrics(user, now, start):
    from alerts.models import Notification
    agg = Notification.objects.filter(user=user).aggregate(
        today=Count("id", filter=Q(created_at__gte=start)),
        unread=Count("id", filter=Q(read=False)))
    return agg


def _learn_metrics(now, start):
    from ai_agents.models import AgentTask
    agg = AgentTask.objects.filter(created_at__gte=start).aggregate(
        n=Count("id"), ok=Count("id", filter=Q(success=True)),
        cost=Sum("cost_usd"))
    return [[int(agg["n"] or 0), "AI calls today"],
            [int(agg["ok"] or 0), "of them succeeded"],
            [round(float(agg["cost"] or 0), 4), "USD spent on AI today"]]


def _markets_metrics(now):
    from market_data.feeds import feed_states
    feeds = feed_states(now)
    ok = sum(1 for f in feeds if f["state"] == "green")
    red = sum(1 for f in feeds if f["state"] in ("red", "yellow"))
    off = sum(1 for f in feeds if f["state"] in ("off", "never"))
    return ok, red, off, len(feeds)


def _venues_view(user):
    from bot_program.capital_truth import broker_view
    return broker_view(user)


# ── the payload ──────────────────────────────────────────────────────────

def day_live_payload(user, now=None) -> dict:
    """Everything the home page's live layer paints, JSON-serialisable.

    {"now", "beat", "stages" (seven), "clusters" (three), "tasks" (one per
    beat entry), "clock" (the minute of the UTC day and the daily crontab
    marks), "counts"} — the shape static/js/sv-day-scheme.js's setLive()
    reads for beat/stages/clusters, plus what the tiles and the strip need.
    """
    now = now or timezone.now()
    start = _start_of_today(now)
    scheme = _group("beat schedule", day_scheme, {"stages": [], "total": 0})
    mapping = _group("beat components", beat_components, {})

    # ONE query for every component row; every entry and every count below
    # reads this dict, never the table.
    def _rows():
        from core.platform_control import PlatformComponent
        return {r["key"]: r for r in
                PlatformComponent.objects.values(*_COMPONENT_FIELDS)}
    rows = _group("component rows", _rows, {})

    # The master switch: off, or MISSING (the gate reads a missing row as
    # off), pauses every row it gates. The alarm bot's row is its own
    # switch and nothing else (bot_program.alarm.alarm_task): the pause is
    # one of the things it reports.
    master = rows.get("platform_master")
    paused = master is None or not master["is_enabled"]
    try:
        from bot_program.alarm import COMPONENT_KEY as ALARM_KEY
    except Exception:  # noqa: BLE001 — no alarm module, no exemption
        ALARM_KEY = "telegram_alarm"

    # ONE OWNER PER ROW. Several beat entries write one component row (the
    # bot tick, the reconcile, the chains, the IBKR feed and the daily
    # decay check all write pipeline_asset_bots), so the row says only
    # when ANY of them last ran and whether THAT run failed. Judged once,
    # against its most frequent writer that always writes — the digest's
    # rule (core.component_digest.beat_periods) — and handed to that
    # writer alone. The other writers are "shared": off when the row is
    # off, else quiet, never a green "ran 2 min ago" borrowed from the
    # tick, never five broken entries for one failed row (review,
    # 2026-09-29).
    all_tasks = [t for st in scheme.get("stages") or [] for t in st.get("tasks") or []]
    writers = {}
    for t in all_tasks:
        comp = mapping.get(t["key"])
        if comp:
            writers.setdefault(comp, []).append(t)
    owner = {}
    for comp, ts in writers.items():
        cands = [t for t in ts if t["key"] not in IDLE_WRITERS] or ts
        owner[comp] = min(cands, key=lambda t: (t.get("widest") or float("inf"), t["key"]))

    # Every row judged once: against its owner's widest gap when the beat
    # writes it; a row nothing schedules (a switch, a per-event gate) can
    # be off or broken but never late.
    comp_states = {}
    for key, row in rows.items():
        widest = owner[key].get("widest") if key in owner else None
        comp_states[key] = _row_state(row, widest, now,
                                      paused and key not in ("platform_master", ALARM_KEY)
                                      )[0]

    tasks, stages, marks = {}, {}, []
    counts = {"live": 0, "stale": 0, "off": 0, "broken": 0, "quiet": 0,
              "total": 0}
    for st in scheme.get("stages") or []:
        states, newest = [], None
        n_ungated = n_norow = n_shared = 0
        for task in st.get("tasks") or []:
            comp_key = mapping.get(task["key"])
            row = rows.get(comp_key) if comp_key else None
            shared_with = None
            if comp_key is None:
                # Not wrapped by the task gate: nothing records its runs.
                state, age = "quiet", None
                n_ungated += 1
            elif row is None:
                # Wrapped, and the registry has no row for it: the gate
                # skips it on every beat (a missing row reads OFF by design,
                # core.platform_control), so it IS off, and says why.
                state, age = "off", None
                n_norow += 1
            else:
                row_state, age = _row_state(
                    row, owner[comp_key].get("widest"), now,
                    paused and comp_key != ALARM_KEY)
                if owner[comp_key]["key"] == task["key"]:
                    state = row_state
                else:
                    shared_with = owner[comp_key]["key"]
                    state = "off" if row_state == "off" else "quiet"
                    age = None
                    n_shared += 1
            # The stage's own judgement hears "idle" for an owner that is
            # switched on and never ran (the page shows it quiet): one off
            # entry beside it must not make the whole stage read off.
            states.append("idle" if (state == "quiet" and row is not None
                                     and shared_with is None) else state)
            last = row["last_run_at"] if (row and shared_with is None) else None
            tasks[task["key"]] = {
                "state": state,
                "component": comp_key,
                "shared_with": shared_with,
                "ago": ("shared record" if shared_with
                        else _ago(age) if last is not None else "never"),
                "last": last.isoformat() if last is not None else None,
            }
            counts["total"] += 1
            counts[state] = counts.get(state, 0) + 1
            if last is not None and (newest is None or last > newest):
                newest = last
            if task.get("kind") == "cron" and task.get("seconds") == 86400.0:
                marks.append({"m": int(task.get("first") or 0),
                              "label": task.get("label") or task["key"],
                              "key": task["key"], "state": state,
                              "shared": bool(shared_with)})
        stage_state = _stage_state(states)
        notes = []
        if paused and stage_state == "off":
            notes.append("The master switch is off: the gate skips every "
                         "task it guards.")
        if n_ungated:
            notes.append(f"{n_ungated} of {len(states)} entries run outside "
                         f"the task gate and record no runs.")
        if n_norow:
            notes.append(f"{n_norow} wrapped by the gate have no component "
                         f"row yet, so the gate skips them (seed_components).")
        if n_shared:
            notes.append(f"{n_shared} share their record with a more frequent "
                         f"task, which alone the record speaks for.")
        stages[st["key"]] = {
            "state": stage_state,
            "words": _run_words(stage_state, _age(newest, now)),
            "metrics": [],
            "note": " ".join(notes),
        }
    marks.sort(key=lambda m: (m["m"], m["label"]))

    # ── the metrics, one fenced group per stage ──────────────────────
    # Seven keys whatever the schedule read said: the page's tiles are
    # rendered from the same STAGES and each looks itself up here.
    for key, _title, _job in STAGES:
        stages.setdefault(key, {"state": "quiet", "words": "never ran",
                                "metrics": [], "note": ""})

    stages["see"]["metrics"] = _group(
        "SEE metrics", lambda: _see_metrics(now, start),
        [[0, "news items scraped today"],
         [0, "instruments with a price under 15 min old"]])
    stages["think"]["metrics"] = _group(
        "THINK metrics", lambda: _think_metrics(now, start),
        [[0, "signals raised today"], [0, "signals active now"]])
    stages["decide"]["metrics"] = _group(
        "DECIDE metrics", lambda: _decide_metrics(user, now, start),
        [[0, "of 0 bot configs enabled"],
         [0, "entries the gate refused today (allows are sampled)"]])

    act = _group("ACT metrics", lambda: _act_metrics(user, now, start), None)
    if act is None:
        stages["act"]["metrics"] = [[0, "trades opened today"],
                                    [0, "trades closed today"]]
        graded_today = 0
    else:
        stages["act"]["metrics"] = [
            [act["opened"], "trades opened today"],
            [act["closed"], "trades closed today"],
            [act["open_live"], "open now, live money"],
            [act["open_paper"], "open now, paper"],
            [act["pending"], "closes pending at the venue"],
            [act["errors"], "orders in ERROR today"],
        ]
        graded_today = int(act["graded"] or 0)
        if act["pending"]:
            stages["act"]["note"] = (
                f"{act['pending']} close(s) the venue has not confirmed — "
                f"retried every 5 min, counted as exposure until it does.")

    stages["watch"]["metrics"] = _group(
        "WATCH metrics", lambda: _watch_metrics(user, now, comp_states),
        [[0, "Morgul guards ran"], [0, "guard findings standing"]])

    tell = _group("TELL metrics", lambda: _tell_metrics(user, now, start),
                  {"today": 0, "unread": 0})
    eye_state = comp_states.get("telegram_eye", "quiet")
    alarm_state = comp_states.get("telegram_alarm", "quiet")
    stages["tell"]["metrics"] = [[int(tell["today"] or 0), "notifications today"],
                                 [int(tell["unread"] or 0), "unread now"]]
    stages["tell"]["note"] = (f"The Eye's group poll is {eye_state}; "
                              f"the alarm bot's is {alarm_state}.")

    learn = _group("LEARN metrics", lambda: _learn_metrics(now, start),
                   [[0, "AI calls today"], [0, "of them succeeded"],
                    [0.0, "USD spent on AI today"]])
    stages["learn"]["metrics"] = learn + [[graded_today, "trades graded today"]]

    # ── the beat ─────────────────────────────────────────────────────
    n_on = sum(1 for r in rows.values() if r["is_enabled"])
    n_stale = sum(1 for s in comp_states.values() if s in ("stale", "silent"))
    n_broken = sum(1 for s in comp_states.values() if s == "broken")
    newest_any = max((r["last_run_at"] for r in rows.values()
                      if r["last_run_at"] is not None), default=None)
    if master is None:
        beat_state, beat_words = "off", "master switch has no row: the gate skips everything"
    elif not master["is_enabled"]:
        beat_state, beat_words = "off", "master switch off"
    elif n_broken:
        beat_state = "broken"
        beat_words = f"last task ran {_ago(_age(newest_any, now))}"
    elif newest_any is None:
        beat_state, beat_words = "quiet", "no task has recorded a run"
    else:
        age = _age(newest_any, now)
        beat_state = "live" if age <= HEARTBEAT_STALE_S else "stale"
        beat_words = f"last task ran {_ago(age)}"
    beat = {"state": beat_state, "words": beat_words,
            "metrics": [[n_on, "components switched on"],
                        [max(len(rows) - n_on, 0), "components switched off"],
                        [n_stale, "components stale"],
                        [n_broken, "components broken"]]}

    # ── the clusters ─────────────────────────────────────────────────
    feeds = _group("MARKETS feeds", lambda: _markets_metrics(now), None)
    if feeds is None:
        markets = {"state": "quiet", "words": "feeds unknown",
                   "metrics": [[0, "of 0 quote feeds delivering"]]}
    else:
        ok, red, off, total = feeds
        markets = {
            "state": ("live" if ok else "stale" if red else "quiet"),
            "words": f"{ok} of {total} feeds delivering",
            "metrics": [[ok, f"of {total} quote feeds delivering"],
                        [red, "feeds stale or slow"],
                        [off, "feeds not configured or never delivered"]],
        }

    book = _group("VENUES book", lambda: _venues_view(user), None)
    if not book:
        venues = {"state": "quiet", "words": "paper book only",
                  "metrics": [[0, "broker accounts interfaced"]],
                  "note": "No keyed broker row carries the book; orders "
                          "land on the paper venue."}
    else:
        reading = book.get("equity")
        age = reading["age_seconds"] if reading else None
        if age is None:
            v_state, v_words = "quiet", f"{book['name']} · no reading yet"
        elif age > BROKER_STALE_S:
            v_state, v_words = "stale", f"{book['name']} · read {_ago(age)}"
        else:
            v_state, v_words = "live", f"{book['name']} · read {_ago(age)}"
        held = book.get("positions")
        venues = {
            "state": v_state, "words": v_words,
            "metrics": [[1, f"broker account interfaced ({book['kind']}"
                            f"{' · ' + book['env'] if book.get('env') else ''})"],
                        [int(age // 60) if age is not None else 0,
                         "min since the equity reading"],
                        [len(held["rows"]) if held else 0,
                         "positions the broker reports holding"]],
        }

    people = {
        "state": _stage_state([eye_state, alarm_state]),
        "words": f"the Eye {eye_state} · the alarm {alarm_state}",
        "metrics": [[int(tell["unread"] or 0), "unread notifications"],
                    [int(tell["today"] or 0), "notifications today"]],
        "note": "The two Telegram voices read their groups every 15 s "
                "while their switches are on.",
    }

    return {
        "now": now.strftime("%H:%M UTC"),
        "beat": beat,
        "stages": stages,
        "clusters": {"markets": markets, "venues": venues, "people": people},
        "tasks": tasks,
        "clock": {"minute": now.hour * 60 + now.minute, "marks": marks,
                  "us_session": list(us_session()),
                  "night": list(NIGHT_OF_LEARNING)},
        "counts": counts,
    }


def us_session():
    """(open, close) of the New York session in minutes of the UTC day,
    off core.constants.MARKET_SESSIONS — the table the Wall's session pills
    read. The strip typed 13:30–21:00 while the table says 13:30–20:00
    (review, 2026-09-29)."""
    try:
        from core.constants import MARKET_SESSIONS
        ny = MARKET_SESSIONS["new_york"]
        oh, om = (int(x) for x in ny["open"].split(":"))
        ch, cm = (int(x) for x in ny["close"].split(":"))
        return (oh * 60 + om, ch * 60 + cm)
    except Exception:  # noqa: BLE001 — a band is decoration, never a 500
        return US_SESSION


@login_required
@never_cache
@require_GET
def day_live(request):
    """GET /api/day/live/ — the live layer, for staff.

    Staff only (review, 2026-09-29): every component's state and last run,
    the master switch, Morgul's findings and the two Telegram voices are
    what /health/, the system map and oculus keep from a non-staff login.
    A non-staff reader's home page draws the ring from the schedule, as
    the public Wall does, and never asks this door."""
    if not request.user.is_staff:
        return JsonResponse({"staff_only": True}, status=403)
    return JsonResponse(day_live_payload(request.user))
