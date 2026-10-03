"""A day of Sauron: the beat schedule read into seven stages.

The Wall and the home page draw the same picture — the loop the platform
turns every day: SEE, THINK, DECIDE, ACT, WATCH, TELL, LEARN, around one
heartbeat, with the markets flowing in and the venues and the people
flowing out. The picture's numbers are NOT typed here. Every task and every
cadence on it is read from `config.celery`'s beat_schedule at render time,
so a cadence changed in celery.py changes on the page with the next
request, and an entry added to the beat appears on the page the same way,
even before this module has heard of it (it lands in `unplaced`, counted
and named, never dropped in silence — the digest's rule, 2026-09-26).

What IS typed here is the grouping: which stage each beat entry belongs
to, and how each is worded for a reader. tests/test_day_of_sauron.py pins
that every entry of the real schedule has a stage, so a new beat entry
fails the suite until someone places it.

Nothing here reads the database. The home page's live layer
(dashboard.views_day) adds the state of each stage on top of this map.
"""
from __future__ import annotations

import fnmatch
from itertools import groupby

#: The seven stages, in the order the ring turns. Key, title, and the one
#: sentence a hover shows first.
STAGES = (
    ("see", "SEE", "Prices, news, the calendar and the macro tape come in."),
    ("think", "THINK", "Indicators, setups and signals; the brain reads its own market."),
    ("decide", "DECIDE", "The bots tick; the desk and the allocators size the money."),
    ("act", "ACT", "An order goes to one venue, with its stop and its target."),
    ("watch", "WATCH", "The guards read the book; the brake cuts the bots."),
    ("tell", "TELL", "Two Telegram voices, the dashboard, the public Wall."),
    ("learn", "LEARN", "The night grades, prunes, promotes and plans."),
)

#: What each stage feeds, for the hover's last line.
NEXT_OF = {
    "see": "Feeds THINK: indicators and signals read these bars.",
    "think": "Feeds DECIDE: a candidate entry per symbol, or a named reason to hold.",
    "decide": "Feeds ACT: one order per candidate that passed, with its stop and target.",
    "act": "Feeds WATCH: fills and positions read back from the venue.",
    "watch": "Feeds TELL: findings, faults and fills become messages.",
    "tell": "Feeds PEOPLE: the operator, and the two words back — /status, /stopall.",
    "learn": "Feeds THINK the next morning: the rules that survived the night.",
}

#: Beat entry key -> (stage, the words a reader sees). One line per entry
#: of config/celery.py's beat_schedule. Keys the schedule does not carry
#: (a branch not yet merged) are harmless here; keys it carries and this
#: table lacks are reported in `unplaced`.
STAGE_OF = {
    # ── SEE: what comes in ──────────────────────────────────────────────
    "fetch-live-quotes-watchlist": ("see", "live quotes"),
    "fetch-forex-live": ("see", "forex quotes"),
    "fetch-commodity-live": ("see", "commodity quotes"),
    "fetch-index-live": ("see", "index quotes"),
    "fetch-crypto-prices": ("see", "crypto quotes"),
    "fetch-crypto-news": ("see", "crypto news"),
    "fetch-breaking-news": ("see", "breaking news"),
    "fetch-news-bodies": ("see", "news bodies"),
    "fetch-social-sentiment": ("see", "social sentiment"),
    "check-economic-calendar": ("see", "economic calendar"),
    "fetch-fred-macro": ("see", "FRED macro series"),
    "fetch-tradingview-ideas": ("see", "TradingView ideas"),
    "fetch-eod-prices-full-universe": ("see", "end-of-day prices, every instrument"),
    "fetch-sec-filings": ("see", "SEC filings"),
    "fetch-cot-reports": ("see", "COT reports"),
    "refresh-bot-bars": ("see", "the bots' bars"),
    # Market data, not orders (review, 2026-09-29): the IBKR feed upserts
    # klines and tickers into PriceData/LiveQuote, the chains are Greeks
    # and quotes.
    "refresh-option-chains": ("see", "option chains"),
    "ibkr-data-feed": ("see", "IBKR market data (legacy)"),
    # ── THINK: indicators, signals, the brain ───────────────────────────
    "ai-process-new-news": ("think", "news analysed"),
    "recalculate-technicals-watchlist": ("think", "watchlist indicators"),
    "run-signal-engine": ("think", "the signal scan"),
    "signal-lifecycle-pass": ("think", "signal lifecycle"),
    "smc-lifecycle-pass": ("think", "SMC lifecycle"),
    "smc-universe-scan": ("think", "SMC universe"),
    "sauron-anomaly-scanner": ("think", "anomaly scanner"),
    "ai-anomaly-scan": ("think", "AI anomaly detection"),
    "sauron-mind-synthesize": ("think", "Sauron's mind"),
    "sauron-mind-resolve-predictions": ("think", "brain predictions resolved"),
    "aggregate-sentiment-scores": ("think", "sentiment aggregated"),
    "sauron-critic-pass": ("think", "the critic"),
    "sauron-earnings-reviewer": ("think", "earnings review"),
    "ai-strategy-review": ("think", "active strategies reviewed"),
    "scan-opportunities": ("think", "opportunity scan"),
    "recalculate-all-technicals": ("think", "all indicators"),
    "run-full-signal-scan": ("think", "full universe scan"),
    # ── DECIDE: the bots, the desk, the allocators ──────────────────────
    "tick-asset-bots": ("decide", "every asset bot ticks: entries, exits, stops"),
    # The crisis mode's eyes and Aragorn (2026-10-02): the posture is
    # read before the bots decide; Aragorn decides which pairs may.
    "read-market-stress": ("decide", "the market's stress sets the posture"),
    "run-aragorn": ("decide", "Aragorn moves rule/class pairs between paper and real money"),
    "propose-share-plans": ("decide", "share plans proposed"),
    # ── ACT: the venue ──────────────────────────────────────────────────
    "retry-pending-closes": ("act", "pending closes retried, confirmed by the venue"),
    "refresh-saxo-sessions": ("act", "Saxo sessions refreshed"),
    "reconcile-asset-bot-trades": ("act", "trades reconciled against the venue"),
    # ── WATCH: the guards, the syncs ────────────────────────────────────
    # No typed count of guards here: the Wall's numbers are counted, and
    # "ten" would drift the day an eleventh guard lands.
    "run-morgul-guards": ("watch", "Morgul's guards"),
    "sauron-position-review": ("watch", "open positions reviewed"),
    "sync-broker-account": ("watch", "IBKR account synced"),
    "sync-etoro-accounts": ("watch", "eToro account synced"),
    "sync-saxo-accounts": ("watch", "Saxo account synced"),
    "update-portfolio-exposure": ("watch", "portfolio exposure"),
    "track-record-decay-check": ("watch", "track-record decay"),
    "watch-evidence-chain": ("watch", "the evidence chain watched"),
    "alarm-sentinel": ("watch", "the alarm sentinel"),
    # ── TELL: the voices ────────────────────────────────────────────────
    "poll-telegram-eye": ("tell", "the Eye reads its Telegram group"),
    "poll-telegram-alarm": ("tell", "the alarm bot reads its group"),
    "check-price-alerts": ("tell", "price alerts"),
    # It reads the funding rows already stored and raises notifications
    # on a squeeze or extreme crowding: a voice, not a feed.
    "scan-funding-signals": ("tell", "funding squeeze alerts"),
    "ai-daily-briefing": ("tell", "the daily briefing"),
    "send-morning-digest": ("tell", "the morning digest"),
    "component-digest": ("tell", "the component digest"),
    "send-eod-digest": ("tell", "the end-of-day digest"),
    "daily-market-commentary": ("tell", "the daily commentary"),
    # Not "when one is due": tests/test_day_of_sauron.py refuses a count
    # word in a label ("one" reads as a typed number).
    "send-due-newsletters": ("tell", "the newsletter, when an edition is due"),
    # ── LEARN: the night and the weekend ────────────────────────────────
    "aragorn-daily-report": ("tell", "Aragorn's daily report"),
    "proving-ground-rules": ("think", "The proving ground judges every live rule and its mirror on all history"),
    "proving-ground-generate": ("think", "The proving ground judges the generator's shortlist"),
    "investigate-decaying-rules": ("learn", "decaying rules investigated"),
    # The night's governance and grading, not the tick's sizing (review,
    # 2026-09-29): the actuator reads the decay investigations, the
    # evolutions mutate decaying rules, the desk scores its own plans.
    "propose-rule-actions": ("learn", "the rule actuator proposes"),
    "grade-capital-desk": ("learn", "the capital desk graded"),
    "propose-strategy-evolutions": ("learn", "strategy evolutions proposed"),
    "sauron-consolidation-nightly": ("learn", "brain consolidation"),
    "resolve-pending-calibrations": ("learn", "calibrations resolved"),
    "nightly-cleanup": ("learn", "nightly cleanup"),
    "auto-evaluate-promotions": ("learn", "promotions and demotions"),
    "sauron-auto-demoter-daily": ("learn", "the auto-demoter"),
    "sauron-horizon-monthly": ("learn", "Horizon"),
    "sauron-strategist-daily": ("learn", "the strategist"),
    "resolve-opportunity-flags": ("learn", "opportunity flags resolved"),
    "daily-portfolio-snapshot": ("learn", "the daily snapshot"),
    "ai-weekly-review": ("learn", "the weekly review"),
    "ai-strategy-optimization": ("learn", "strategy optimisation"),
    "propose-meta-allocation": ("learn", "meta-allocation proposed"),
    "sauron-strategy-generator-weekly": ("learn", "the strategy generator"),
    "mine-patterns": ("learn", "patterns mined"),
    "weekly-portfolio-rebalance-suggestions": ("learn", "rebalancing suggested"),
    "ai-monday-game-plan": ("learn", "the Monday plan"),
}

#: The counts each stage shows off the Wall's own facts (core.wall_facts):
#: (fact key, words). A missing fact reads 0, never a typed number.
FACTS_OF = {
    "see": (("instruments", "instruments followed"),
            ("news_24h", "news items read in the last 24 h")),
    "think": (("evaluators", "signal evaluators"),
              ("signals_graded", "signals graded against what followed")),
    "decide": (("bots", "bot configurations"),
               ("strategies", "strategies")),
    "act": (("trades_graded", "trades graded"),
            ("broker_adapters", "broker adapters")),
    "watch": (("components", "components behind a switch"),
              ("chain_length", "links in the audit chain")),
    "tell": (("shell_commands", "operator commands"),),
    "learn": (("agent_calls_graded", "AI calls graded"),
              ("rules_governed", "rules under governance")),
}

_DOW = {0: "Sun", 1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat"}
_MON = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
        7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"}
_DAY = 86400.0
_WEEK = 7 * _DAY
_MONTH = 30 * _DAY
_YEAR = 365 * _DAY


def _time(h: int, m: int) -> str:
    return f"{h:02d}:{m:02d}"


def _step(values) -> int | None:
    """The one gap between consecutive sorted ints, or None when uneven."""
    if len(values) < 2:
        return None
    gaps = {b - a for a, b in zip(values, values[1:])}
    return gaps.pop() if len(gaps) == 1 else None


def interval_words(seconds: float) -> str:
    """'15 s', '5 min', '1 h', '2 d' — the way the operator says it."""
    s = float(seconds)
    if s <= 60:
        return f"{int(s)} s"
    if s < 3600:
        return f"{s / 60:g} min"
    if s < _DAY:
        return f"{s / 3600:g} h"
    return f"{s / _DAY:g} d"


def _dow_words(dows) -> tuple[str, int]:
    """('Mon–Fri' | 'Sat · Sun' | 'Tue', Monday-first index of the first).
    Celery counts Sunday as 0; a reader's week starts on Monday."""
    order = sorted(dows, key=lambda d: (d + 6) % 7)
    idx = [(d + 6) % 7 for d in order]
    if len(order) >= 3 and idx == list(range(idx[0], idx[0] + len(idx))):
        return f"{_DOW[order[0]]}–{_DOW[order[-1]]}", idx[0]
    return " · ".join(_DOW.get(d, str(d)) for d in order), idx[0]


def _time_words(minutes, hours) -> tuple[str, float, int]:
    """(words, typical gap in seconds, fires per day) for the hour and
    minute fields alone."""
    n = len(minutes) * len(hours)
    if n == 1:
        return _time(hours[0], minutes[0]), _DAY, 1
    hstep = _step(hours)
    if len(minutes) == 1:
        m = minutes[0]
        if len(hours) == 24:
            return f"hourly at :{m:02d}", 3600.0, n
        if hstep and hstep > 1 and len(hours) * hstep == 24:
            return f"every {hstep} h at :{m:02d}", hstep * 3600.0, n
        if hstep == 1:
            return f"hourly {_time(hours[0], m)}–{_time(hours[-1], m)}", 3600.0, n
        return "at " + ", ".join(_time(h, m) for h in hours), _DAY / n, n
    mstep = _step(minutes)
    if mstep:
        every = f"every {mstep} min"
        # A step that does not divide the hour (*/7) restarts at :00 each
        # hour: say which minutes, or the words promise an even beat.
        if len(minutes) * mstep != 60:
            every += f" (:{minutes[0]:02d}–:{minutes[-1]:02d} each hour)"
        if len(hours) == 24:
            return every, mstep * 60.0, n
        if len(hours) == 1 or hstep == 1:
            return (f"{every}, {_time(hours[0], minutes[0])}"
                    f"–{_time(hours[-1], minutes[-1])}", mstep * 60.0, n)
        return (f"{every} during " + ", ".join(f"{h:02d}h" for h in hours),
                mstep * 60.0, n)
    fires = [_time(h, m) for h in hours for m in minutes]
    return ("at " + ", ".join(fires[:6]) + (" …" if len(fires) > 6 else ""),
            _DAY / n, n)


def crontab_words(cron) -> tuple[str, float, int]:
    """(words, period in seconds, minute of the week of the first fire).

    A crontab says WHEN; the words say it the way the operator reads a
    clock: '03:00', 'Sat 10:00', '1st 04:45', 'every 4 h at :05',
    'hourly 13:15–20:15', 'every 15 min, 13:00–21:45', 'Mon–Fri every
    15 min, 13:00–21:45', 'Jan 09:00'. Every calendar restriction (month,
    day of the month, day of the week) is said in front of every shape
    (review, 2026-09-29: a weekday restriction survived only on a single
    daily fire, and the month was never read). The period is the typical
    gap, for sorting beside the interval entries: the time-of-day gap when
    the entry fires more than once a day, else the calendar's.
    """
    minutes = sorted(cron.minute)
    hours = sorted(cron.hour)
    if not minutes or not hours:
        return "never", _YEAR, 0
    words, gap, per_day = _time_words(minutes, hours)
    first = hours[0] * 60 + minutes[0]
    period = gap
    prefix = []
    moys = sorted(cron.month_of_year)
    doms = sorted(cron.day_of_month)
    dows = sorted(cron.day_of_week)
    if len(moys) < 12:
        prefix.append(" · ".join(_MON.get(m, str(m)) for m in moys))
        if per_day == 1:
            period = max(period, _YEAR / len(moys))
    if len(doms) < 31:
        prefix.append("1st" if doms == [1] else
                      "day " + ", ".join(str(d) for d in doms))
        if per_day == 1:
            period = max(period, _MONTH / len(doms))
    if len(dows) < 7:
        dw, monday_index = _dow_words(dows)
        prefix.append(dw)
        # Sorted Monday-first inside the week, so Saturday's entries come
        # before Sunday's on the picture.
        first += monday_index * 1440
        if per_day == 1:
            period = max(period, _WEEK / len(dows))
    if prefix:
        words = " · ".join(prefix) + " " + words
    return words, period, first


def schedule_words(schedule) -> tuple[str, float | None, str, int]:
    """(words, period seconds, kind 'interval'|'cron'|'other', first minute).

    A schedule this cannot read (a solar event, a custom BaseSchedule,
    nothing) has period None, never infinity: the result goes into a
    json_script, and `Infinity` is not JSON — the ring's JSON.parse threw
    and the whole drawing stayed blank (review, 2026-09-29)."""
    from datetime import timedelta

    from celery.schedules import crontab
    from celery.schedules import schedule as interval

    if isinstance(schedule, bool) or schedule is None:
        return "unscheduled", None, "other", 0
    if isinstance(schedule, (int, float)):
        return interval_words(schedule), float(schedule), "interval", 0
    if isinstance(schedule, timedelta):
        secs = schedule.total_seconds()
        return interval_words(secs), secs, "interval", 0
    if isinstance(schedule, crontab):
        words, period, first = crontab_words(schedule)
        return words, period, "cron", first
    if isinstance(schedule, interval):
        secs = schedule.run_every.total_seconds()
        return interval_words(secs), secs, "interval", 0
    return type(schedule).__name__, None, "other", 0


def widest_gap(schedule) -> float | None:
    """The WIDEST gap between two runs, in seconds — what a staleness
    judgement must use (a 13:00–21:45 entry is silent all night by design,
    and a weekday one all weekend). The digest's own reading
    (core.component_digest._period_hours), so the two never disagree."""
    try:
        from core.component_digest import _period_hours
        hours = _period_hours(schedule)
    except Exception:  # noqa: BLE001 — an odd schedule has no period
        return None
    return hours * 3600.0 if hours else None


def queue_of(task_path: str, routes: dict) -> str:
    """The queue Celery's MapRoute picks: the exact name first, then the
    first glob that matches, else the default queue."""
    exact = routes.get(task_path)
    if isinstance(exact, dict) and exact.get("queue"):
        return str(exact["queue"])
    for pattern, cfg in routes.items():
        if "*" in pattern and fnmatch.fnmatchcase(task_path, pattern):
            if isinstance(cfg, dict) and cfg.get("queue"):
                return str(cfg["queue"])
    return "default"


def _rows(tasks: list) -> list:
    """The hover's list: one row per cadence, its tasks joined by ' · '."""
    out = []
    for when, group in groupby(tasks, key=lambda t: t["when"]):
        out.append({"when": when, "what": " · ".join(t["label"] for t in group)})
    return out


def read_schedule():
    """(beat_schedule dict, task_routes dict) off the live Celery app."""
    from config.celery import app
    return dict(app.conf.beat_schedule or {}), dict(app.conf.task_routes or {})


def day_scheme(wall: dict | None = None) -> dict:
    """The picture's data: seven stages, each with its beat entries read
    from the schedule, the totals, and the counts the Wall already shows.

    Pure and JSON-serialisable; the template hands it to the page through
    json_script and static/js/sv-day-scheme.js draws it.
    """
    schedule, routes = read_schedule()
    wall = wall or {}
    stages = {key: {"key": key, "n": i + 1, "title": title, "job": job,
                    "next": NEXT_OF[key], "tasks": []}
              for i, (key, title, job) in enumerate(STAGES)}
    unplaced = []
    every = []
    for entry_key in sorted(schedule):
        entry = schedule[entry_key] or {}
        task_path = str(entry.get("task") or "")
        words, period, kind, first = schedule_words(entry.get("schedule"))
        stage, label = STAGE_OF.get(entry_key, (None, entry_key))
        task = {"key": entry_key, "label": label, "task": task_path,
                "when": words, "seconds": period,
                "widest": widest_gap(entry.get("schedule")), "kind": kind,
                "first": first, "queue": queue_of(task_path, routes)}
        every.append(task)
        if stage is None:
            unplaced.append(task)
        else:
            stages[stage]["tasks"].append(task)

    def order(t):
        secs = t["seconds"] if t["seconds"] is not None else float("inf")
        return (secs, t["first"], t["when"], t["label"])

    for st in stages.values():
        st["tasks"].sort(key=order)
        st["rows"] = _rows(st["tasks"])
        st["count"] = len(st["tasks"])
        st["fastest"] = st["tasks"][0]["when"] if st["tasks"] else ""
        # "fastest 15 s" for a beat, "first at 02:30" for a stage whose
        # quickest entry is a clock time (review, 2026-09-29: "fastest
        # 02:30" read a time of day as a speed).
        lead = st["tasks"][0] if st["tasks"] else None
        if lead is None:
            st["pace"] = ""
        elif lead["seconds"] is not None and lead["seconds"] < _DAY and lead["kind"] == "interval":
            st["pace"] = f"fastest {lead['when']}"
        elif lead["kind"] == "cron" and lead["seconds"] is not None and lead["seconds"] >= _DAY:
            st["pace"] = f"first at {lead['when']}"
        else:
            st["pace"] = lead["when"]
        st["facts"] = [[int(wall.get(k) or 0), words]
                       for k, words in FACTS_OF.get(st["key"], ())]
    every.sort(key=order)
    queues = {}
    for t in every:
        queues[t["queue"]] = queues.get(t["queue"], 0) + 1
    return {
        "stages": [stages[k] for k, _, _ in STAGES],
        "total": len(schedule),
        "queues": dict(sorted(queues.items())),
        "fastest": every[0]["when"] if every else "",
        "slowest": every[-1]["when"] if every else "",
        "unplaced": unplaced,
        "adapters": int(wall.get("broker_adapters") or 0),
    }


#: What the drawing reads off a stage — and so all a page is handed.
_DRAWN = ("key", "n", "title", "job", "next", "rows", "count", "fastest",
          "pace", "facts")


def page_scheme(scheme: dict) -> dict:
    """The copy a page carries in its json_script: what
    static/js/sv-day-scheme.js draws and nothing else. The full scheme
    names every task's import path, beat key and queue; the public Wall
    shipped all of it to every visitor while the drawing read none of it
    (review, 2026-09-29). Unplaced entries become a count."""
    return {
        "stages": [{k: st[k] for k in _DRAWN if k in st}
                   for st in scheme.get("stages") or []],
        "total": scheme.get("total", 0),
        "queues": scheme.get("queues", {}),
        "fastest": scheme.get("fastest", ""),
        "slowest": scheme.get("slowest", ""),
        "unplaced": len(scheme.get("unplaced") or []),
        "adapters": scheme.get("adapters", 0),
    }


def beat_components() -> dict:
    """{beat entry key: component key} for the entries the task gate
    wraps — the home page's live layer reads each stage's state off the
    PlatformComponent rows those keys name. Entries the gate does not
    wrap (the brain loop, the Saxo session keeper, this digest) are absent."""
    from core.component_digest import _beat_task, _component_key_of
    from config.celery import app

    schedule = dict(app.conf.beat_schedule or {})
    out = {}
    for entry_key, entry in schedule.items():
        try:
            task = _beat_task(app, str((entry or {}).get("task") or ""))
            key = _component_key_of(task) if task is not None else None
        except Exception:  # noqa: BLE001 — one odd entry is not the map
            key = None
        if key:
            out[entry_key] = key
    return out
