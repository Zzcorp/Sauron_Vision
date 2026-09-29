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
    "scan-funding-signals": ("see", "funding rates"),
    # ── THINK: indicators, signals, the brain ───────────────────────────
    "ai-process-new-news": ("think", "news analysed"),
    "recalculate-technicals-watchlist": ("think", "watchlist indicators"),
    "run-signal-engine": ("think", "the signal scan"),
    "signal-lifecycle-pass": ("think", "signal lifecycle"),
    "smc-lifecycle-pass": ("think", "SMC lifecycle"),
    "smc-universe-scan": ("think", "SMC universe"),
    "sauron-anomaly-scanner": ("think", "anomaly scanner"),
    "ai-anomaly-scan": ("think", "AI anomaly detection"),
    "sauron-position-review": ("think", "open-position review"),
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
    "propose-share-plans": ("decide", "share plans proposed"),
    "propose-rule-actions": ("decide", "the rule actuator proposes"),
    "grade-capital-desk": ("decide", "the capital desk grades itself"),
    "propose-strategy-evolutions": ("decide", "strategy evolutions proposed"),
    # ── ACT: the venue ──────────────────────────────────────────────────
    "retry-pending-closes": ("act", "pending closes retried, confirmed by the venue"),
    "refresh-saxo-sessions": ("act", "Saxo sessions refreshed"),
    "reconcile-asset-bot-trades": ("act", "trades reconciled against the venue"),
    "refresh-option-chains": ("act", "option chains refreshed"),
    "ibkr-data-feed": ("act", "IBKR market data refreshed"),
    # ── WATCH: the guards, the syncs ────────────────────────────────────
    "run-morgul-guards": ("watch", "Morgul's ten guards"),
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
    "ai-daily-briefing": ("tell", "the daily briefing"),
    "send-morning-digest": ("tell", "the morning digest"),
    "component-digest": ("tell", "the component digest"),
    "send-eod-digest": ("tell", "the end-of-day digest"),
    "daily-market-commentary": ("tell", "the daily commentary"),
    # ── LEARN: the night and the weekend ────────────────────────────────
    "investigate-decaying-rules": ("learn", "decaying rules investigated"),
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
_DAY = 86400.0
_WEEK = 7 * _DAY
_MONTH = 30 * _DAY


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


def crontab_words(cron) -> tuple[str, float, int]:
    """(words, period in seconds, minute of day of the first fire).

    A crontab says WHEN; the words say it the way the operator reads a
    clock: '03:00', 'Sat 10:00', '1st 04:45', 'every 4 h at :05',
    'hourly 13:15–20:15', 'every 15 min, 13:00–21:45'. The period is the
    typical gap, for sorting beside the interval entries.
    """
    minutes = sorted(cron.minute)
    hours = sorted(cron.hour)
    dows = sorted(cron.day_of_week)
    doms = sorted(cron.day_of_month)
    first = (hours[0] * 60 + minutes[0]) if hours and minutes else 0
    prefix, period = "", _DAY
    if len(dows) < 7:
        prefix = " · ".join(_DOW.get(d, str(d)) for d in dows) + " "
        period = _WEEK
        # Sorted Monday-first inside the week, so Saturday's entries come
        # before Sunday's on the picture (celery counts Sunday as 0).
        first += ((dows[0] + 6) % 7) * 1440
    if len(doms) < 31:
        prefix = ("1st " if doms == [1] else
                  "day " + ", ".join(str(d) for d in doms) + " ")
        period = _MONTH
    if len(hours) == 1 and len(minutes) == 1:
        return prefix + _time(hours[0], minutes[0]), period, first
    if len(minutes) == 1:
        m = minutes[0]
        if len(hours) == 24:
            return f"hourly at :{m:02d}", 3600.0, first
        step = _step(hours)
        if step and step > 1 and len(hours) * step == 24:
            return f"every {step} h at :{m:02d}", step * 3600.0, first
        if step == 1:
            return (f"hourly {_time(hours[0], m)}–{_time(hours[-1], m)}",
                    3600.0, first)
        return ("at " + ", ".join(_time(h, m) for h in hours),
                _DAY / max(len(hours), 1), first)
    step = _step(minutes)
    if step and len(minutes) * step == 60:
        every = f"every {step} min"
        if len(hours) == 24:
            return every, step * 60.0, first
        if len(hours) == 1 or _step(hours) == 1:
            return (f"{every}, {_time(hours[0], minutes[0])}"
                    f"–{_time(hours[-1], minutes[-1])}", step * 60.0, first)
    fires = [_time(h, m) for h in hours for m in minutes]
    return "at " + ", ".join(fires[:6]) + (" …" if len(fires) > 6 else ""), _DAY, first


def schedule_words(schedule) -> tuple[str, float, str, int]:
    """(words, period seconds, kind 'interval'|'cron'|'other', first minute)."""
    from datetime import timedelta

    from celery.schedules import crontab
    from celery.schedules import schedule as interval

    if isinstance(schedule, bool) or schedule is None:
        return "unscheduled", float("inf"), "other", 0
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
    return str(schedule), float("inf"), "other", 0


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
                "when": words, "seconds": period, "kind": kind,
                "first": first, "queue": queue_of(task_path, routes)}
        every.append(task)
        if stage is None:
            unplaced.append(task)
        else:
            stages[stage]["tasks"].append(task)

    def order(t):
        return (t["seconds"], t["first"], t["when"], t["label"])

    for st in stages.values():
        st["tasks"].sort(key=order)
        st["rows"] = _rows(st["tasks"])
        st["count"] = len(st["tasks"])
        st["fastest"] = st["tasks"][0]["when"] if st["tasks"] else ""
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
