"""THE OCULUS — every cycle this platform runs, on one screen (2026-09-13).

Thirty dashboards existed before this one and each answered its own
question well. None answered the operator's: *is the machine turning, and
which of its wheels is actually engaged?* That question is not a
thirty-first subsystem, so this page owns no data. It reads what the
subsystems already record and does one thing they cannot do individually
— put them side by side without letting the comparison lie.

WHY A COUNT IS THE HARD PART HERE
---------------------------------

The recurring failure in this codebase is not a wrong number. It is a
right number that reads as its opposite:

* "26 rules registered" sounds like coverage. A rule at `research` stage
  cannot place an order AND its signals are dropped from decide()'s vote,
  so registering a rule DEMOTES it relative to never registering one.
* "N configs wear scalp" sounds like adoption. A wearing config may be
  disabled, or on an asset class whose bars nothing writes.
* "the desk chose 40 entries" sounds like allocation. In shadow — the
  default — every candidate executes at full size anyway and 'displaced'
  displaced nothing.
* "0.0R" sounds like breakeven. Below the evidence floor it means nobody
  has measured anything.

So every fact here carries its qualifier in the same breath, and three
values are kept strictly apart:

    a number   — measured
    None       — NOT measurable (no rows, table absent, counter fenced)
    the gate   — whether the component that writes it is even switched on

`core/wall_facts.py` collapses everything to 0 because it is the public
login gateway and must never raise. The Oculus is behind auth and has the
opposite duty: 0 and "unmeasured" are different answers and it prints
them differently. A 0 where None belongs is the exact fabrication
wall_facts exists to abolish, moved one page inward.

FENCING
-------

`oculus()` cannot raise. Every counter runs in its own fence, and a
counter that fails reports None and names itself in `degraded` — with its
reason, in `not_measured` — rather than taking the page, or worse its nine
healthy neighbours, down. A failure is logged at WARNING once per process
per fact, so a dead table is seen in the log without flooding it.

COST AND TRUTH (O0, 2026-11-06)
-------------------------------

The page read 81 queries per call and walked the source tree on every
staff GET. Now:

* ONE COMPONENT READ PER RENDER. `_gate` and the switches read the
  PlatformComponent rows once (`_Render`); `_gate` called alone still
  queries for itself. A viewer, who gets no switch state, reads none.
* ONE AGGREGATE PER TABLE, STILL ONE FENCE PER FACT. Each table's facts
  read one shared `aggregate(Count(filter=Q(...)))` (`_Once`); if it fails,
  each fact's own fence reports it and each is named.
* THE FORGE ONCE PER BUILD. The guard scan is stored per image (no sha:
  ten minutes), the migration plan ten minutes, and both print how old
  they are; the probe prints its own stored time, and a tally older than
  the image is a dash. Every stored reading is keyed by the build (sha and
  build time, `_build_id`): Redis keeps its data across a deploy.
* EVERY COUNT NAMES ITS WINDOW (`WINDOWS`), every code constant says so,
  a stored reading prints its age where its window would read "now",
  money keeps its cents, and amber is data (`alert_when`): a value is
  painted only past its stated threshold, read on the value as computed
  (never the rounded one), with its words, and a dash never.
* LATE MEANS PAST THE LAST PASS. A flag or a call that fell due since its
  resolver's last scheduled pass waits for the next one and is not late
  (`_last_pass`); only what fell due before it and is still open is.
* THE BOOK IN THREE WORLDS. REAL, DEMO and PAPER by the platform's one
  world rule (dashboard.position_summary.world_of) with the desk's own
  risk arithmetic, never summed; the desk's two venues stay beside them,
  labelled as the desk's, with how many demo rows the desk still counts.
  The desk itself is not asked anything new and nothing in it changed.

No broker call and no model call is made to draw this page.
"""
import logging
import math
import operator
import time
from contextvars import ContextVar
from datetime import (datetime, time as dtime, timedelta,
                      timezone as dt_timezone)

from django.db.models import (Case, Count, DateTimeField, DurationField,
                              ExpressionWrapper, F, IntegerField, Max, Min,
                              Q, Value, When)
from django.utils import timezone

from .views_ops import STAFF_ONLY

logger = logging.getLogger(__name__)

#: Days of history in the evolution strips.
WINDOW_DAYS = 30

#: A fact whose builder failed, or whose table holds nothing to measure.
UNMEASURED = None

#: WHAT EVERY COUNT IS COUNTED OVER (2026-11-06). A lifetime total printed
#: without its window reads as current state: "graded: stopped out 1,204"
#: beside "live signals 13" looks like today's figure. "today" starts at
#: 00:00 UTC. A code constant is not counted over anything and says
#: `constant` instead (CONSTANT).
WINDOWS = ("now", "today", "24 h", "7 d", "30 d", "all time")
CONSTANT = "constant"

#: How long a stored reading is kept, in seconds: ten minutes. The forge's
#: migration plan (`migrate` can run on the same image), a guard scan on an
#: unstamped checkout, and the backtests' tolerant Python sum.
STORED_TTL = 10 * 60

#: EVERY STORED READING IS KEYED BY THE BUILD (2026-11-07, review): its
#: `{build}` is `_build_id()`, the image's sha and build time. Redis keeps
#: its data across a deploy (deploy/docker-compose.yml runs it with an
#: appendonly volume), so a key without the build handed the next image
#: the previous one's readings — a dict the new code could not read, or
#: an old counting rule's number under a new label.
#:
#: Where the forge keeps its two readings. With a stamped image the guard
#: scan never expires — the code cannot change without a new image — and
#: the migration plan lasts STORED_TTL. An unstamped checkout uses
#: FORGE_UNSTAMPED in place of the build and both last STORED_TTL.
FORGE_GUARDS_KEY = "oculus:forge:guards:{build}"
FORGE_MIGRATIONS_KEY = "oculus:forge:migrations:{build}"
FORGE_UNSTAMPED = "unstamped"

#: Where `manage.py probe_routes` leaves its tally (PROBE_KEY there), for
#: seven days (its PROBE_TTL).
PROBE_KEY = "forge:route_probe"

#: The backtests' "signals a run could not simulate", kept STORED_TTL and
#: re-counted at once when the set of complete runs changes.
UNSIMULATED_KEY = "oculus:slow:unsimulated:{build}"

#: THE TWO ALL-TIME AGGREGATES KEPT TEN MINUTES (§7.2 point 6, 2026-11-06):
#: the tables this page reads whole with no index for its filter —
#: AgentPrediction (prediction_type) and DeskPlan (mode). Measured at the
#: six-month scale, the page missed its budget without them. Each prints
#: when it was counted; their strips stay live.
PREDICTIONS_KEY = "oculus:slow:predictions:{build}"
DESK_PASSES_KEY = "oculus:slow:desk_passes:{build}"

#: What each stored aggregate holds. A stored dict that lacks one of these
#: keys was written by other code and is counted again, never read into a
#: KeyError dash.
_CALLS_KEYS = ("right", "wrong", "awaiting", "not_due", "open_at_pass",
               "unsettled", "agents")
_PASSES_KEYS = ("shadow", "live")

#: The cycles a login that is not staff reads as a header and the
#: STAFF_ONLY caveat, never as numbers (2026-09-28). /health/'s rule, as
#: the cockpit applies it to its switches and queues (views_ops): THE
#: SWITCHES are every component's state, which /ops/ and /health/ keep
#: from any other login; THE FORGE is the image's sha, the migrations not
#: applied on this database, and a read of every guarded_task in the
#: source tree — the page's two costly reads, which are not made for a
#: reader who may not see the answer. The gate chips on every other
#: panel are switch states too, and go the same way (see oculus()).
STAFF_ONLY_CYCLES = ("forge", "gates")

#: WHERE EACH CYCLE IS ANSWERED IN FULL (2026-09-13).
#:
#: A panel that reports a count and offers no way into it is a report, not
#: a command post: the operator reads "12 setups blind", nods, and still
#: has to remember which of thirty pages explains why. These are the
#: drill-downs — the existing pages, unchanged, reached from the cycle
#: that summarises them.
#:
#: SEVERAL DESTINATIONS PER CYCLE, ON PURPOSE. Picking one would be a
#: judgement this map has no business making: the ladder is answered by
#: three pages at three zooms, and allocation by three that size three
#: different things — the account's share per pool, one tick's entries,
#: and per-rule multipliers. One row named "allocator" once hid the
#: second (2026-09-12), and collapsing them here would repeat that.
#:
#: Names only, never paths: a hard-coded "/setups/" survives a route
#: rename and 404s in silence. tests/test_oculus.py reverses every one.
CYCLE_PAGES = {
    "forge": [("ops_dashboard", "Ops"),
              ("system_health", "System Health"),
              ("audit_dashboard", "Audit Log")],
    "book": [("portfolio_overview", "Portfolio"),
             ("positions_list", "Positions"),
             ("desk_dashboard", "Capital Desk")],
    "gates": [("ops_dashboard", "Ops"),
              ("system_health", "System Health")],
    "scan": [("setups_dashboard", "Setups"),
             ("opportunities_dashboard", "Opportunities")],
    "ladder": [("strategies_list", "Strategies"),
               ("promotions_dashboard", "Promotion Ladder"),
               ("rule_control_dashboard", "Rule Controls")],
    "signals": [("signals_list", "Signals"),
                ("performance_dashboard", "Signal Performance")],
    "evolution": [("evolution_dashboard", "Strategy Evolution"),
                  ("generated_dashboard", "Generated Strategies"),
                  ("discoveries_dashboard", "Discoveries")],
    "personas": [("personas_dashboard", "Personalities")],
    "allocation": [("shares_dashboard", "Share Allocator"),
                   ("desk_dashboard", "Capital Desk"),
                   ("allocator_dashboard", "Risk Allocator")],
    "horizon": [("horizon_dashboard", "Horizon"),
                ("calibration_dashboard", "Agent Calibration")],
    "backtests": [("backtest_list", "Backtesting"),
                  ("bot_backtest_list", "Bot Backtest"),
                  ("bot_performance_dashboard", "Bot Performance")],
    "trust": [("calibration_dashboard", "Agent Calibration"),
              ("brain_dashboard", "Sauron's Mind"),
              ("evidence_ledger", "Evidence Ledger")],
}


def _pages_for(key):
    """Resolve a cycle's drill-downs, dropping any that no longer exist.

    A dead url name in a template raises at RENDER — on this page and on
    nothing else, but completely. A cycle losing a link is a smaller
    failure than the page losing itself, so this resolves rather than
    trusts, and a route that has been renamed simply stops being offered.
    """
    from django.urls import NoReverseMatch, reverse

    out = []
    for name, label in CYCLE_PAGES.get(key, ()):
        try:
            out.append({"name": name, "label": label, "href": reverse(name)})
        except NoReverseMatch:
            logger.warning("oculus: cycle %s links to %r, which reverses to "
                           "nothing — link dropped", key, name)
    return out


# ── one render, read once ───────────────────────────────────────────────

class _Once:
    """One read shared by every fact that asks for it.

    The first call runs the read; every later call returns its answer. A
    read that FAILS is kept failed too: each fact that asks re-raises the
    same exception inside its own fence, so each is a dash and each is
    named, and a table that is not there is not asked a second time for
    the same "no such table".
    """

    __slots__ = ("_read", "_done", "_value", "_error")

    def __init__(self, read):
        self._read = read
        self._done = False
        self._value = None
        self._error = None

    def __call__(self):
        if not self._done:
            try:
                self._value = self._read()
            except Exception as exc:  # noqa: BLE001 — re-raised to each fence
                self._error = exc
            self._done = True
        if self._error is not None:
            raise self._error
        return self._value


class _Render:
    """What one call of oculus() reads once and shares (2026-11-06).

    The component rows behind every gate chip and the switches' four
    counts were fourteen queries; the desk's two budgets are read by the
    book's columns and by the desk block beside them. Outside a render
    each helper reads for itself, exactly as before.
    """

    def __init__(self, staff):
        self.staff = staff
        self.components = _Once(_read_components)
        self.budgets = {}
        self.equity = {}


_RENDER = ContextVar("oculus_render", default=None)


# ── words ───────────────────────────────────────────────────────────────

def _ago(seconds):
    """'just now', '4 min ago', '3 h ago', '2 d ago' — the Eye's tenses,
    as /command/ prints them (views_day._ago)."""
    seconds = max(0.0, float(seconds))
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 48 * 3600:
        return f"{int(seconds // 3600)} h ago"
    return f"{int(seconds // 86400)} d ago"


def money_text(value):
    """Money as it is printed here: grouped, two decimals, its sign. Never
    int(): 473.8 is "473.80" and -0.6 is "-0.60", not 473 and 0."""
    return f"{float(value):,.2f}"


def _rows_word(n, one="row", many="rows"):
    return f"{n} {one if n == 1 else many}"


# ── one fact, one fence ─────────────────────────────────────────────────

class _Unmeasured(Exception):
    """Raised by a builder that knows WHY it has no number: the dash it
    becomes carries these words to the footer instead of an exception's
    type (the probe that has not run since the cache was cleared)."""

    def __init__(self, why, fix=""):
        super().__init__(why)
        self.why = why
        self.fix = fix


class _Reading:
    """A stored figure and when it was stored (§5.1). A builder returns one
    instead of a bare number when what it reports was written by someone
    else, earlier: the page prints the figure WITH its age, or not at all.
    `stale` marks a reading past its writer's own freshness bound.
    """

    __slots__ = ("value", "at", "words", "stale")

    def __init__(self, value, at, words, stale=False):
        self.value = value
        self.at = at
        self.words = words
        self.stale = stale


#: alert_when's comparisons, as data: ("<", 0) reads "below zero".
_ALERT_OPS = {"<": operator.lt, "<=": operator.le,
              ">": operator.gt, ">=": operator.ge}

#: Failures already logged at WARNING by this process, by fact.
_WARNED = set()


def _warn_once(name, exc):
    """WARNING the first time a fact fails in this process, DEBUG after:
    a dead table is seen in the log without one line per GET."""
    key = (name, type(exc).__name__)
    if key in _WARNED:
        logger.debug("oculus: %s unavailable (%s)", name, exc)
        return
    _WARNED.add(key)
    logger.warning("oculus: %s not measurable (%s: %s)", name,
                   type(exc).__name__, exc)


def _why(exc):
    """(reason, fix) in words for a builder that raised.

    The exception's TYPE only, never its message: a message can carry a
    query, a path or a value, and the page is not a log. A table or column
    that is not there is the one cause worth naming, because it has a
    one-line fix.
    """
    name = type(exc).__name__
    text = str(exc).lower()
    if name in ("OperationalError", "ProgrammingError") and any(
            s in text for s in ("no such table", "no such column",
                                "does not exist")):
        return "table missing (migration not applied)", "manage.py migrate"
    return f"the builder raised {name}", ""


def _coerce(value, kind):
    if value is None:
        return None
    if kind == "money":
        return round(float(value), 2)
    return int(value)


def _fact(label, builder, *, note="", qualifier="", tone="plain",
          kind="count", window="now", alert_when=None, alert_words="",
          alert_level="warn", none_why="", fix="", currency=""):
    """Run one counter inside its own fence.

    `tone` is for the template only and never changes a number:
      plain    — a count
      caution  — a count the operator should read twice (see `qualifier`)
      inert    — a count of things that cannot act (research, shadow, off)

    `kind` says what the number is: a `count`, `money` (kept to two
    decimals, never int(), printed with its `currency`), `days`, `hours`,
    or a code `constant` — which is not counted over anything and says so
    in place of a window.
    `window` is one of WINDOWS (§5.4).

    `alert_when`, e.g. ("<", 0), is the threshold past which the value is
    painted (§5.3): amber for "warn" (⚠), coral for "danger" (⨯), always
    with `alert_words`. It is data, never template logic, and a dash never
    crosses it. It reads the value as the builder computed it, never the
    rounded one (2026-11-07, review): a budget of -0.004 is past the
    ceiling though it prints at the cent, and the cell keeps the sign the
    threshold saw ("-0.00" beside its amber; a zero that is not below zero
    prints no sign).

    `when` is what the page prints after the label: the window, or — for
    a stored reading counted "now" — the reading's age in its place,
    since "now" above "probed 6 d ago" says two things at once (§5.1).
    """
    age = None
    why = hint = ""
    raw = None
    try:
        value = builder()
        if isinstance(value, _Reading):
            age = {"seconds": max(0, int(time.time() - value.at)),
                   "words": value.words, "stale": bool(value.stale)}
            value = value.value
        raw = value
        value = _coerce(value, kind)
        if value is None:
            why, hint = (none_why or "nothing to measure yet"), fix
    except _Unmeasured as gap:
        value, why, hint = UNMEASURED, gap.why, gap.fix or fix
    except Exception as exc:  # noqa: BLE001 — a dead table must not take the page
        _warn_once(label, exc)
        value = UNMEASURED
        why, hint = _why(exc)
        hint = hint or fix
    alert = bool(value is not None and alert_when is not None
                 and _ALERT_OPS[alert_when[0]](
                     float(raw) if kind == "money" else raw, alert_when[1]))
    display = ""
    if kind == "money" and value is not None:
        if value == 0:
            value = -0.0 if float(raw) < 0 else 0.0
        display = money_text(value)
    shown = CONSTANT if kind == "constant" else window
    return {"label": label, "value": value, "display": display,
            "note": note, "qualifier": qualifier, "tone": tone,
            "kind": kind, "currency": currency, "window": shown,
            "when": (age["words"] if age is not None and shown == "now"
                     else shown),
            "alert_when": alert_when, "alert": alert,
            "alert_level": alert_level if alert else "",
            "alert_words": alert_words if alert else "",
            "age": age, "why": why, "fix": hint}


def _text_fact(label, builder, *, note="", qualifier="", tone="plain",
               none_why="", fix=""):
    """A fact whose answer is a word, not a count.

    `_fact` coerces to int because nearly everything on this page is a
    count and an accidental string would sort and compare wrongly. A
    commit sha is the exception: it is an identifier, and rounding it to
    an integer is not a category error anyone would catch later. Same
    fence, same None-is-not-zero rule — an unstamped build renders an em
    dash rather than the word "unknown", which reads like data.
    """
    why = hint = ""
    try:
        value = builder()
        value = None if value in (None, "") else str(value)
        if value is None:
            why, hint = (none_why or "nothing to measure yet"), fix
    except Exception as exc:  # noqa: BLE001
        _warn_once(label, exc)
        value = None
        why, hint = _why(exc)
    return {"label": label, "value": value, "display": "", "note": note,
            "qualifier": qualifier, "tone": tone, "text": True,
            "kind": "text", "currency": "", "window": "now", "when": "now",
            "alert_when": None,
            "alert": False, "alert_level": "", "alert_words": "",
            "age": None, "why": why, "fix": hint}


# ── the strips ──────────────────────────────────────────────────────────

def _day_starts(days):
    """The first instant of each of the last `days` days, today last, in
    the current time zone (UTC here)."""
    tz = timezone.get_current_timezone()
    today = timezone.localdate()
    return [timezone.make_aware(datetime.combine(today - timedelta(days=i),
                                                 dtime.min), tz)
            for i in range(days - 1, -1, -1)]


def _series(model, field, *, days=WINDOW_DAYS, extra=None):
    """A per-day count over the last `days` days, bucketed on `field`.

    Always `created_at`-shaped, never a settlement stamp: `completed_at`,
    `resolved_at` and `evaluated_at` are NULL on exactly the rows a
    stalled cycle would show, so bucketing on them hides the stall.

    ONE GROUPED READ OVER THE WINDOW, DAY BY CASE (2026-11-06). TruncDate
    is a Python function per row on SQLite (47-70 ms per strip at the
    six-month scale); a CASE over the thirty day starts is plain SQL on
    every backend and gives the same buckets (13-33 ms). Raises on failure:
    the caller's fence decides (`_spark` omits the strip, a fact read from
    it becomes a dash).
    """
    starts = _day_starts(days)
    qs = model.objects.filter(**{f"{field}__gte": starts[0]})
    if extra:
        qs = qs.filter(**extra)
    rows = (qs.annotate(oculus_day=_day_of(field, starts)).values("oculus_day")
              .annotate(n=Count("id")).order_by())
    by_day = {r["oculus_day"]: r["n"] for r in rows}
    return [{"d": start.date().isoformat(), "n": int(by_day.get(i, 0))}
            for i, start in enumerate(starts)]


def _day_of(field, starts):
    """The index of the day a row's `field` falls in (0 the oldest of
    `starts`, the last one today), or -1 before the first: a CASE over the
    day starts, newest first."""
    return Case(*[When(**{f"{field}__gte": start}, then=Value(i))
                  for i, start in reversed(list(enumerate(starts)))],
                default=Value(-1), output_field=IntegerField())


def _tally(model, field, by, *, days=WINDOW_DAYS):
    """A SMALL table's strip and its all-time counts by `by`, in one
    grouped read (2026-11-06): {"series": as _series gives it, "by":
    {value: rows, all time}}. Bucketed on `field`, which is creation-shaped
    for the same reason as _series. On a large table the grouped read
    costs more than an aggregate plus a strip, so it is used only where the
    rows are few (the generator's proposals)."""
    starts = _day_starts(days)
    rows = (model.objects.annotate(oculus_day=_day_of(field, starts))
            .values("oculus_day", by).annotate(n=Count("id")).order_by())
    by_day, counts = {}, {}
    for r in rows:
        counts[r[by]] = counts.get(r[by], 0) + r["n"]
        if r["oculus_day"] >= 0:
            by_day[r["oculus_day"]] = by_day.get(r["oculus_day"], 0) + r["n"]
    return {"series": [{"d": start.date().isoformat(),
                        "n": int(by_day.get(i, 0))}
                       for i, start in enumerate(starts)],
            "by": counts}


def _spark(read):
    """The strip, or no strip: a failed read omits it (never a flat line
    of zeros, which would read as a measured quiet month)."""
    try:
        return read()
    except Exception as exc:  # noqa: BLE001
        _warn_once("strip", exc)
        return []


def _spark_total(read):
    """Rows in the strip's thirty days, for a fact that counts them: the
    same read as the strip, so the fact and the bars always agree. A failed
    read is a dash, never 0."""
    return sum(p["n"] for p in read())


# ── the switches behind the cycles ──────────────────────────────────────

_COMPONENT_FIELDS = ("key", "name", "is_enabled", "last_run_at",
                     "last_status", "last_message", "run_count",
                     "error_count")


def _read_components():
    from core.platform_control import PlatformComponent
    return {r["key"]: r for r in
            PlatformComponent.objects.values(*_COMPONENT_FIELDS)}


def _component_rows():
    """Every component row: the render's one read, or a read of its own
    when called outside oculus()."""
    render = _RENDER.get()
    if render is not None:
        return render.components()
    return _read_components()


def _gate(*keys):
    """The switch state behind a cycle.

    A count written by a task nobody has switched on is not a measurement
    of the market, it is a measurement of the switch — so the switch is
    rendered beside the count, never inferred from it. A key with no row
    reads False, which is what `is_component_enabled` returns and what
    the gate actually does (see tests/test_component_registry.py).

    Within a render it reads the render's one component read; called
    alone it queries for itself. For a viewer who is not staff it reads
    nothing: the chips are switch states and are withheld whole.
    """
    render = _RENDER.get()
    if render is not None and not render.staff:
        return []
    out = []
    try:
        if render is not None:
            rows = render.components()
        else:
            from core.platform_control import PlatformComponent
            rows = {r["key"]: r for r in PlatformComponent.objects.filter(
                key__in=keys).values(*_COMPONENT_FIELDS)}
        for key in keys:
            row = rows.get(key)
            out.append({
                "key": key,
                "on": bool(row and row["is_enabled"]),
                "known": row is not None,
                "last_run": row["last_run_at"] if row else None,
                "last_status": (row["last_status"] if row else "") or "",
            })
    except Exception as exc:  # noqa: BLE001
        _warn_once(f"gate {','.join(keys)}", exc)
        return [{"key": k, "on": False, "known": False,
                 "last_run": None, "last_status": ""} for k in keys]
    return out


def _withheld(key, title, question):
    """A STAFF_ONLY_CYCLES panel, for a login that is not staff.

    The panel stays — a vanished panel reads as "there is no such cycle",
    the lie of omission this page refuses — with its title, its question
    and its ways out, which apply their own rule. Its builder is not run:
    nothing is counted, scanned or planned for a reader who does not get
    the count.
    """
    return {"key": key, "title": title, "question": question, "gate": [],
            "facts": [], "caveat": STAFF_ONLY, "series": [],
            "staff_only": True}


# ── stored readings ─────────────────────────────────────────────────────

def _build_id():
    """The image this process runs, as every stored reading is keyed
    (2026-11-07, review): its sha and its build time — a rebuild of the
    same sha (a pull that brought nothing, an uncommitted edit) is another
    image — or FORGE_UNSTAMPED for a checkout nobody stamped."""
    from core.build_stamp import built_at, git_sha
    sha = git_sha()
    if not sha:
        return FORGE_UNSTAMPED
    return f"{sha}@{built_at() or 'unknown'}"


def _epoch(stamp_text):
    """The build stamp's ISO instant as seconds since the epoch, or None
    when there is none or it cannot be read (core.build_stamp's parse)."""
    if not stamp_text:
        return None
    try:
        when = datetime.fromisoformat(str(stamp_text).replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt_timezone.utc)
    return when.timestamp()


def _holds(value, keys):
    """Does a stored aggregate carry every key this code reads from it?"""
    return not keys or (isinstance(value, dict)
                        and all(k in value for k in keys))


def _stored(key, compute, timeout, verb, *, at_build=False, fingerprint=None,
            expect=()):
    """A reading kept in the cache, returned with its age (§5.1).

    The value under `key` if it is there (and, with `fingerprint`, if it
    was stored for the same one, and, with `expect`, if it is a dict that
    carries each of those keys); otherwise `compute()` is run and stored
    for `timeout` seconds (None: until the cache is cleared). A cache that
    cannot be read or written never costs the page: the value is computed
    and printed as counted now. A compute that raises is not stored and
    becomes the fact's dash.
    """
    from django.core.cache import cache
    try:
        hit = cache.get(key)
    except Exception as exc:  # noqa: BLE001 — a dead cache is not a dead page
        _warn_once(f"cache {key}", exc)
        hit = None
    if (isinstance(hit, dict) and "value" in hit
            and isinstance(hit.get("at"), (int, float))
            and (fingerprint is None or hit.get("fp") == fingerprint)
            and _holds(hit["value"], expect)):
        value, at = hit["value"], hit["at"]
    else:
        value, at = compute(), time.time()
        try:
            cache.set(key, {"value": value, "at": at, "fp": fingerprint},
                      timeout)
        except Exception as exc:  # noqa: BLE001
            _warn_once(f"cache {key}", exc)
    words = f"{verb} {_ago(time.time() - at)}"
    if at_build:
        words = f"{verb} at this build, {_ago(time.time() - at)}"
    return _Reading(value, at, words)


def _part(read, key, minus=None):
    """One figure out of a stored aggregate, carrying the aggregate's age;
    with `minus`, that figure less another of the same read."""
    stored = read()
    value = stored.value[key]
    if minus is not None:
        value -= stored.value[minus]
    return _Reading(value, stored.at, stored.words)


# ── the cycles ──────────────────────────────────────────────────────────

def _desk_budget(user, venue):
    from bot_program.capital_desk import budget_for
    return budget_for(user, venue)


def _budget(user, venue):
    """capital_desk.budget_for(user, venue), read once per render: the
    venue's column and the desk block beside it print the same answer."""
    render = _RENDER.get()
    if render is None:
        return _desk_budget(user, venue)
    key = (getattr(user, "pk", None), venue)
    once = render.budgets.get(key)
    if once is None:
        once = render.budgets[key] = _Once(lambda: _desk_budget(user, venue))
    return once()


def _read_equity(user):
    """When the broker's equity cell was read: {"at" (epoch), "words",
    "stale"}, or None when there is no cell. capital_truth.account_equity
    reads the sync's stored columns, never the broker. Past the bound the
    governor's own reading calls `stale` (TRACKING_FRESH_SECONDS) the words
    say so: a governor computed from a three-day-old cell is not "now"."""
    from bot_program.capital_truth import (TRACKING_FRESH_SECONDS,
                                           account_equity)
    reading = account_equity(user)
    if not reading or reading.get("at") is None:
        return None
    seconds = max(0, int(reading.get("age_seconds") or 0))
    stale = seconds > TRACKING_FRESH_SECONDS
    words = f"equity read {_ago(seconds)}"
    if stale:
        words += (f" — stale (a reading is fresh for "
                  f"{TRACKING_FRESH_SECONDS // 60} min)")
    return {"at": reading["at"].timestamp(), "words": words, "stale": stale}


def _equity(user):
    """_read_equity, once per render (the governor's fact and the desk's
    reason line print the same reading); None when it cannot be read."""
    render = _RENDER.get()
    try:
        if render is None:
            return _read_equity(user)
        key = getattr(user, "pk", None)
        once = render.equity.get(key)
        if once is None:
            once = render.equity[key] = _Once(lambda: _read_equity(user))
        return once()
    except Exception as exc:  # noqa: BLE001 — no age is printed, never a 500
        _warn_once("book.equity reading", exc)
        return None


#: What budget_for writes when the governor's reading raised, with the
#: exception's message inside the brackets.
_GOVERNOR_UNREADABLE = "governor unreadable ("


def _desk_reason(reason):
    """The desk's reason line as budget_for wrote it, except an unreadable
    governor's cause (2026-11-07, review): budget_for puts the exception's
    message in the brackets, and this page names a failure's kind, never
    its message (_why) — a database error carries SQL text. The cause is in
    the desk's log; what follows it (the currencies set aside) is kept."""
    reason = reason or ""
    if not reason.startswith(_GOVERNOR_UNREADABLE):
        return reason
    _head, sep, tail = reason.rpartition(") — 1.00")
    return ("governor unreadable — 1.00 (the cause is in the desk's log)"
            + (tail if sep else ""))


def _venue_facts(user, venue):
    """One venue's book, from the primitives the desk already sizes with.

    `budget_for` answers the whole column in one call — capital, risk at
    stop, budget left, the governor and how many open rows could not be
    measured — so this cannot drift from what the sizing engine believes.
    The money keeps its cents (2026-11-06): int() printed a budget of -0.6
    as 0, a breached ceiling as an exact one.
    """
    b = _budget(user, venue)
    ccy = b.get("currency") or ""

    def _f(key):
        return lambda: b.get(key)

    facts = [
        _fact('pool capital', _f("capital"), kind="money", currency=ccy,
              qualifier='capital assigned to the enabled configs: the '
                        'denominator sizing divides, not your equity'),
        _fact("open positions", _f("n_open")),
        _fact('risk to stop committed', _f("book_risk"), kind="money",
              currency=ccy,
              qualifier='sum of qty × |entry − opening stop|, pending '
                        'closes included'),
        _fact("budget left", _f("budget"), kind="money", tone="caution",
              currency=ccy,
              qualifier='new risk this tick: 2 % of the pools × the '
                        'governor, minus the risk already booked — not '
                        "the account's open-risk limit",
              alert_when=("<", 0),
              alert_words='past the ceiling: no new risk this tick'),
    ]
    if b.get("unmeasured_open"):
        facts.append(_fact(
            'positions whose risk is NOT measured', _f("unmeasured_open"),
            tone="caution",
            qualifier='open with no readable initial stop: they weigh on '
                      'the book and on no budget',
            alert_when=(">", 0),
            alert_words='open with no readable stop: on the book, on no '
                        'budget'))
    if venue == "live":
        # The governor exists on the live venue only — a drawdown brake on a
        # simulation would throttle a book that cannot lose anything.
        dd = b.get("drawdown_pct")
        # The broker's equity cell the governor rests on, when the desk had
        # one (no reading: drawdown_pct is None and 1.00 is its default).
        equity = _equity(user) if dd is not None else None

        def _governor():
            if b.get("governor") is None:
                return None
            # FLOORED, never rounded up (2026-11-07, review): 0.998 is 99,
            # not 100, which the qualifier keeps for its two meanings.
            value = math.floor(round(float(b["governor"]) * 100, 6))
            if equity is None:
                return value
            return _Reading(value, equity["at"], equity["words"],
                            stale=equity["stale"])

        facts.append(_fact(
            "drawdown governor (×100)", _governor,
            tone="caution",
            qualifier='100 means TWO things: no drawdown, or no equity '
                      'reading at all. The floor is 40.',
            alert_when=("<", 100),
            alert_words=('the desk trades smaller: '
                         + (f'{float(dd) * 100:.1f} % under the high-water '
                            'mark' if dd else 'under the high-water mark'))))
    return facts


#: The three money worlds, in the order the page prints them.
_WORLD_ORDER = ("live", "demo", "paper")


def _risk_at_stop(row):
    """capital_desk.book_risk's own arithmetic for one row, or None when it
    calls the row unmeasured: qty × |entry − metadata.initial_stop_loss| ×
    value_per_unit, through the desk's own float reader. The book's world
    split adds this per row; a test holds the sum to book_risk's."""
    from bot_program.capital_desk import _f as desk_float
    meta = row.metadata or {}
    stop = meta.get("initial_stop_loss")
    if stop is None:
        return None
    vpu = desk_float(meta.get("value_per_unit", 1.0), 1.0)
    risk = (desk_float(row.qty) * abs(desk_float(row.entry_price)
                                      - desk_float(stop)) * vpu)
    return risk if risk > 0 else None


def _world_split(user):
    """REAL, DEMO and PAPER over the viewer's open book (2026-11-06).

    The desk's live venue is `paper=False`, which is real money AND the
    broker's demo rows; "LIVE · REAL MONEY" printed it as real (B3.1). This
    splits the same rows — OPEN and CLOSE_PENDING, as book_risk reads them
    — by dashboard.position_summary.world_of, the platform's one world rule
    (the Horde and the headband count REAL with it), and adds each row's
    risk with book_risk's arithmetic. One read. A display helper: the desk
    is not asked and does not change.

    Risk is kept per currency and never added across currencies, as the
    desk keeps its budget in one: {currency: risk}. Nothing here adds one
    world to another. A row the world rule cannot place (it places every
    row whose `paper` is set) raises, and the split is a named dash rather
    than a row printed in the wrong world.
    """
    from bot_program.models import AssetBotTrade

    from .position_summary import WORLD_WORDS, world_of

    worlds = {w: {"world": w, "word": WORLD_WORDS[w], "n_open": 0,
                  "n_close_pending": 0, "unmeasured": 0, "risk": {},
                  "n_by_ccy": {}, "unmeasured_by_ccy": {},
                  "n_live_venue": 0, "risk_live_venue": {},
                  "carriers": set()}
              for w in _WORLD_ORDER}
    rows = (AssetBotTrade.objects
            .filter(config__user=user, status__in=("OPEN", "CLOSE_PENDING"))
            .annotate(ccy=F("config__base_currency"))
            .only("paper", "status", "qty", "entry_price", "metadata"))
    for row in rows:
        slot = worlds[world_of(row)]
        slot["n_open"] += 1
        if row.status == "CLOSE_PENDING":
            slot["n_close_pending"] += 1
        if not row.paper:
            slot["n_live_venue"] += 1
        carrier = str((row.metadata or {}).get("broker") or "").strip().lower()
        slot["carriers"].add(carrier)
        # the currency as book_risk reads it: the config's, USD when blank
        ccy = row.ccy or "USD"
        slot["n_by_ccy"][ccy] = slot["n_by_ccy"].get(ccy, 0) + 1
        risk = _risk_at_stop(row)
        if risk is None:
            slot["unmeasured"] += 1
            slot["unmeasured_by_ccy"][ccy] = (slot["unmeasured_by_ccy"]
                                              .get(ccy, 0) + 1)
            continue
        slot["risk"][ccy] = slot["risk"].get(ccy, 0.0) + risk
        if not row.paper:
            slot["risk_live_venue"][ccy] = (slot["risk_live_venue"]
                                            .get(ccy, 0.0) + risk)
    return [worlds[w] for w in _WORLD_ORDER]


def _world_facts(world, currency):
    """One world's column. `currency` is the desk's for the venue the
    world's rows sit on, printed first; any other currency gets a line of
    its own, never added to it.

    A world that holds open rows none of which has a readable opening stop
    has no risk to print (2026-11-07, review): its line is a named dash,
    never 0.00, a sum over no measured row that reads as a measured zero.
    A world with nothing open keeps its measured 0.00."""
    w = world["world"]
    facts = [_fact("open positions", lambda: world["n_open"],
                   qualifier=('real money at the broker' if w == "live" else
                              "simulated money at a broker's demo account"
                              if w == "demo" else
                              "the platform's own simulator"))]
    arithmetic = ("qty × |entry − opening stop|, the desk's own arithmetic, "
                  "pending closes included")
    if world["n_open"] and not world["risk"]:
        facts.append(_fact(
            'risk at the stops', lambda: None, kind="money",
            qualifier=arithmetic,
            none_why="no row in this world has a readable opening stop"))
    currencies = sorted(world["risk"], key=lambda c: (c != currency, c))
    if not currencies and not world["n_open"]:
        currencies = [currency or ""]
    for i, ccy in enumerate(currencies):
        label = 'risk at the stops' if i == 0 else f'risk at the stops, in {ccy}'
        facts.append(_fact(
            label, (lambda c=ccy: world["risk"].get(c, 0.0)), kind="money",
            currency=ccy,
            qualifier=(arithmetic if i == 0
                       else 'another currency: never added to the line above')))
    facts.append(_fact(
        "positions with no measured stop", lambda: world["unmeasured"],
        tone="caution",
        qualifier='no readable opening stop: counted, never priced',
        alert_when=(">", 0),
        alert_words='open with no readable stop: on the book, on no budget'))
    if w == "live":
        facts.append(_fact(
            "closes pending at the venue", lambda: world["n_close_pending"],
            qualifier='still open at the broker while the platform wants '
                      'them flat; retried by the beat'))
    return facts


def _demo_sentence(worlds, live):
    """What the desk's live venue counts that the REAL column does not.

    THE COUNT is measured from the desk's own: its live venue's open rows
    minus the REAL rows and any row stamped for the paper carrier that sit
    on it. Today that leaves the broker's demo rows. When the desk stops
    counting them (C1–C3) it is 0 and the sentence says the desk counts
    REAL rows only, by itself.

    THE RISK is the DEMO world's own (every demo row is paper=False, so on
    the desk's live venue), read under the currency rule the desk applied
    (2026-11-07, review). With a currency, book_risk adds only the rows in
    it: their risk is the figure, and a demo row in another currency is
    named as counted and left out of that budget — never 0.00 in the
    desk's currency. With none (no live config enabled: the kill switch,
    the brake and `bot off` disable them all and leave the rows open) the
    desk adds every row whatever its currency, and the demo risk is printed
    per currency, never subtracted from that mixed total, which held the
    REAL rows' risk too. A demo row with no readable stop is counted and
    named, never priced.
    """
    from .position_summary import BROKER_NAMES

    by = {w["world"]: w for w in worlds}
    demo = by["demo"]
    ccy = live.get("currency") or ""
    not_demo_n = by["live"]["n_open"] + by["paper"]["n_live_venue"]
    n = max(0, int(live.get("n_open") or 0) - not_demo_n)
    counted = {"n": n, "currency": ccy, "risk": 0.0 if ccy else None,
               "risk_by_currency": {}, "aside": {}, "unmeasured": 0}
    if n == 0:
        return counted, "The desk's live venue counts REAL rows only."

    def _in_budget(c):
        return not ccy or c == ccy

    def _first(c):   # the desk's currency first, then the others by name
        return (c != ccy, c)

    in_budget = {c: round(r, 2) for c, r in demo["risk"].items()
                 if _in_budget(c)}
    aside = {c: {"n": k,
                 "risk": (round(demo["risk"][c], 2) if c in demo["risk"]
                          else None),
                 "unmeasured": demo["unmeasured_by_ccy"].get(c, 0)}
             for c, k in demo["n_by_ccy"].items() if not _in_budget(c)}
    unmeasured = sum(k for c, k in demo["unmeasured_by_ccy"].items()
                     if _in_budget(c))
    if ccy:   # nothing of demo in its currency is a measured 0.00
        risk = in_budget.get(ccy, None if demo["n_by_ccy"].get(ccy) else 0.0)
    else:     # the desk mixed every currency: no one figure is true
        risk = None
    counted.update({"risk": risk, "risk_by_currency": in_budget,
                    "aside": aside, "unmeasured": unmeasured})

    carriers = {c for c in demo["carriers"] if c}
    who = (BROKER_NAMES.get(next(iter(carriers)), "")
           if len(carriers) == 1 else "")
    rows = _rows_word(n, f"{who} DEMO row".strip(),
                      f"{who} DEMO rows".strip())
    money = " and ".join(f"{money_text(in_budget[c])} {c}"
                         for c in sorted(in_budget, key=_first))
    apart = ", never added" if len(in_budget) > 1 else ""
    tail = " C1–C3 (real-only limits, planned) takes demo out of the desk."
    if in_budget and not aside and not unmeasured:
        stops = "its stop" if n == 1 else "their stops"
        return counted, (f"The desk's live venue counts {rows} ({money} at "
                         f"{stops}{apart}) as live; the REAL MONEY column "
                         f"above does not.{tail}")
    parts = [f"The desk's live venue counts {rows} as live; the REAL MONEY "
             f"column above does not."]
    if in_budget:
        where = f"in its {ccy} budget" if ccy else "in its budget"
        parts.append(f"At their stops {where}: {money}{apart}.")
    if unmeasured:
        parts.append(f"{_rows_word(unmeasured)} with no readable stop: "
                     f"counted, never priced.")
    for c in sorted(aside, key=_first):
        k, r, u = aside[c]["n"], aside[c]["risk"], aside[c]["unmeasured"]
        said = []
        if r is not None:
            said.append(f"{money_text(r)} {c} at "
                        f"{'its stop' if k == 1 else 'their stops'}")
        if u:
            said.append(f"{u} with no readable stop")
        priced = f" ({', '.join(said)})" if said else ""
        parts.append(f"{_rows_word(k)} in {c}{priced}: counted, and left out "
                     f"of its {ccy} budget.")
    return counted, " ".join(parts) + tail


def _paper_sentence(live, paper):
    """Why the paper venue's pool is the larger number (B3.2).

    venue_capital_detail sums the paper-mode AND the live-mode configs for
    the paper venue, in one currency. When both venues are in the same
    currency, the live venue's pool is exactly the live part of it."""
    ccy = paper.get("currency") or ""
    if ccy and ccy == (live.get("currency") or ""):
        total = float(paper.get("capital") or 0.0)
        live_part = float(live.get("capital") or 0.0)
        return (f"The paper venue divides by the paper AND the live pools: "
                f"{money_text(total)} = {money_text(total - live_part)} "
                f"paper + {money_text(live_part)} live ({ccy}). The live "
                f"pools count in both venues; the two venues are never "
                f"added.")
    return ("The paper venue divides by the paper AND the live pools; the "
            "live pools count in both venues, and the two venues are never "
            "added.")


def _gap_floor():
    """The desk's own evidence floor (capital_desk.DESK_MIN_N): below it on
    either venue a paper-against-live gap is printed and not judged — a
    4-trade gap was drawn in red (B3.9)."""
    from bot_program.capital_desk import DESK_MIN_N
    return int(DESK_MIN_N)


#: The broker account rows capital_truth.broker_backed reads for the
#: governor, in its own order: Saxo, eToro, IBKR.
_BROKER_ROWS = ("saxo_account", "etoro_account", "ibkr_account")


def _with_broker_rows(user):
    """The viewer, with the broker account rows the desk's governor reads
    loaded in one query instead of three (2026-11-06). The same rows, read
    the same way by the same code; a model without one of these relations,
    or any failure, keeps the viewer as it came."""
    try:
        from django.contrib.auth import get_user_model
        model = get_user_model()
        names = [rel.get_accessor_name() for rel in model._meta.related_objects
                 if rel.one_to_one and rel.get_accessor_name() in _BROKER_ROWS]
        if not names:
            return user
        return model.objects.select_related(*names).get(pk=user.pk)
    except Exception as exc:  # noqa: BLE001 — three reads instead of one
        _warn_once("book.broker rows", exc)
        return user


def _cycle_book(user):
    """THE BOOK — real, demo and paper beside each other, never added.

    The only per-VIEWER panel on this page; every other cycle is
    platform-wide. Capital belongs to a user, so pooling it across the
    platform would be meaningless, and saying so in the caveat matters
    more than the numbers: a reader who takes this for a fleet total
    misreads every figure in it.

    Three blocks (2026-11-06): the open book in its three money worlds;
    the desk's two venues, live and paper, exactly as budget_for answers
    them and labelled as the desk's (its live venue still counts the
    broker's demo rows, and says how many); and the paper-against-live
    expectancy gap, judged only past the desk's evidence floor.
    """
    missing = []
    worlds = []
    try:
        worlds = _world_split(user)
    except Exception as exc:  # noqa: BLE001 — the worlds must not cost the desk
        _warn_once("book.worlds", exc)
        why, fix = _why(exc)
        missing.append({"name": "book.worlds", "parts": ("book", "worlds"),
                        "why": why, "fix": fix})

    venues, budgets = [], {}
    for venue in ("live", "paper"):
        try:
            facts = _venue_facts(user, venue)
        except Exception as exc:  # noqa: BLE001 — one venue must not cost both
            _warn_once(f"book.{venue}", exc)
            facts = []
            why, fix = _why(exc)
            missing.append({"name": f"book.{venue}",
                            "parts": ("book", venue),
                            "why": f"venue unreadable: {why}", "fix": fix})
        entry = {"venue": venue, "facts": facts, "reason": "",
                 "currency": "", "not_summed": {}, "n_other_currency": 0,
                 "equity": None}
        try:
            b = _budget(user, venue)
            budgets[venue] = b
            entry.update({"reason": _desk_reason(b.get("reason")),
                          "currency": b.get("currency") or "",
                          "not_summed": dict(b.get("not_summed") or {}),
                          "n_other_currency": int(
                              b.get("n_other_currency") or 0)})
            if venue == "live" and b.get("drawdown_pct") is not None:
                # the equity cell the governor in this reason rests on
                entry["equity"] = _equity(user)
        except Exception as exc:  # noqa: BLE001 — named once, as book.<venue>
            _warn_once(f"book.{venue} desk", exc)
        venues.append(entry)

    desk = {"demo_counted": None, "sentence": "", "paper_sentence": ""}
    if worlds and "live" in budgets:
        desk["demo_counted"], desk["sentence"] = _demo_sentence(
            worlds, budgets["live"])
    if "live" in budgets and "paper" in budgets:
        desk["paper_sentence"] = _paper_sentence(budgets["live"],
                                                 budgets["paper"])
    live_ccy = (budgets.get("live") or {}).get("currency") or ""
    paper_ccy = (budgets.get("paper") or {}).get("currency") or live_ccy
    for world in worlds:
        world["facts"] = _world_facts(
            world, paper_ccy if world["world"] == "paper" else live_ccy)
        world.pop("carriers", None)

    # What the simulator promised, against what execution returned.
    gaps = []
    floor = None
    try:
        from bot_program.bot_grading import paper_live_expectancy_gap
        floor = _gap_floor()
        for row in paper_live_expectancy_gap(user=user, days=180, min_n=1):
            n_paper, n_live = row.get("n_paper"), row.get("n_live")
            gaps.append({
                "rule": row.get("rule_name") or "—",
                "asset_class": row.get("asset_class") or "—",
                "n_paper": n_paper,
                "n_live": n_live,
                "paper": row.get("paper_expectancy"),
                "live": row.get("live_expectancy"),
                "gap": row.get("gap"),
                "judged": (n_paper or 0) >= floor and (n_live or 0) >= floor,
            })
    except Exception as exc:  # noqa: BLE001
        _warn_once("book.expectancy gap", exc)
        why, fix = _why(exc)
        missing.append({"name": "book.expectancy gap",
                        "parts": ("book", "expectancy gap"),
                        "why": why, "fix": fix})

    return {
        "key": "book",
        "title": 'The book',
        "question": 'How much real money is committed, and how much is only '
                    'a simulation?',
        "gate": _gate("platform_master", "broker_account_sync"),
        "facts": [],
        "worlds": worlds,
        "venues": venues,
        "desk": desk,
        "gaps": gaps,
        "gap_floor": floor,
        "missing": missing,
        "caveat": (
            'The only panel on this page that speaks about YOU alone: every '
            'other cycle counts the whole platform. Real money, the '
            "broker's demo and paper are never summed — a simulated pool "
            'inflates the total and no real entry can draw on it. The '
            'expectancy gap is None when one of the two venues closed '
            'nothing: a gap measured against an unmeasured venue is not a '
            'small gap, it is the absence of measurement.'),
        "series": [],
    }


def _cycle_gates(staff=True):
    if not staff:
        return _withheld("gates", 'The switches', 'What is allowed to run?')
    rows = _Once(_component_rows)

    def _count(pred):
        return lambda: sum(1 for r in rows().values() if pred(r))

    return {
        "key": "gates",
        "title": 'The switches',
        "question": 'What is allowed to run?',
        "gate": _gate("platform_master"),
        "facts": [
            _fact('components on', _count(lambda r: r["is_enabled"])),
            _fact('components off', _count(lambda r: not r["is_enabled"]),
                  tone="inert",
                  qualifier='off does not mean broken — it is often the '
                            'right default'),
            _fact('on but never run',
                  _count(lambda r: r["is_enabled"]
                         and r["last_run_at"] is None),
                  tone="caution",
                  qualifier='on and never launched: the scheduler does not '
                            'reach it',
                  alert_when=(">", 0),
                  alert_words='the scheduler does not reach it'),
            _fact('last pass in error',
                  _count(lambda r: r["last_status"] == "error"),
                  tone="caution", alert_when=(">", 0), alert_level="danger",
                  alert_words='its last pass failed: the system map names it'),
        ],
        "caveat": (
            'The master switch cuts everything upstream. A component with '
            'no row in the database reads OFF — that is what the gate does: '
            'as of 2026-09-13, three tasks had never run at all because of '
            'it.'),
        "series": [],
    }


def _beat_words(entry):
    """When a beat entry fires, in the ring's words, read from the live
    schedule (core.day_of_sauron) — never typed into a caveat."""
    from django.conf import settings

    from core.day_of_sauron import read_schedule, schedule_words
    beat, _routes = read_schedule()
    words = schedule_words((beat.get(entry) or {}).get("schedule"))[0]
    return f"{words} {getattr(settings, 'CELERY_TIMEZONE', '') or 'UTC'}"


def _pass_words(entry):
    """"it runs at 23:15 UTC", read from the beat entry, fenced."""
    try:
        from core.day_of_sauron import read_schedule
        if (read_schedule()[0].get(entry) or {}).get("schedule") is None:
            return f"no beat entry runs {entry}"
        return f"it runs at {_beat_words(entry)}"
    except Exception as exc:  # noqa: BLE001 — words, never the page
        _warn_once(f"{entry} schedule", exc)
        return "its beat entry's time"


def _last_fire(schedule, at):
    """The latest instant at or before `at` when a beat schedule fires, or
    None when this cannot place it.

    A crontab over every day of the month and every month is laid out over
    the week, as core.component_digest reads it (Celery numbers the days
    from Sunday, 0), in the beat's own time zone. Anything else — an
    interval, a restricted day of the month — is None, and the caller
    judges it by its widest gap.
    """
    from zoneinfo import ZoneInfo

    from celery.schedules import crontab
    from django.conf import settings

    if not isinstance(schedule, crontab):
        return None
    if len(schedule.month_of_year) < 12 or len(schedule.day_of_month) < 31:
        return None
    marks = [d * 1440 + h * 60 + m for d in schedule.day_of_week
             for h in schedule.hour for m in schedule.minute]
    if not marks:
        return None
    tz = ZoneInfo(getattr(settings, "CELERY_TIMEZONE", "") or "UTC")
    local = at.astimezone(tz).replace(second=0, microsecond=0)
    here = (local.isoweekday() % 7) * 1440 + local.hour * 60 + local.minute
    back = min((here - mark) % (7 * 1440) for mark in marks)
    return local - timedelta(minutes=back)


def _last_pass(entry, now):
    """The last pass of the beat entry `entry` that should have finished by
    `now` (2026-11-07, review): its last scheduled run, given the floor the
    system map gives every row to finish (views_day.STALE_FLOOR_S).

    LATE MEANS PAST THE LAST PASS. A flag or a call that fell due before it
    and is still open is late: that pass should have taken it, so its
    resolver is off, late or failing on it. One that fell due after it
    waits for the next pass and is not late — counting it late lit "the
    resolver is late" about fourteen hours a day with the 23:15 resolver on
    time. A schedule this cannot place is judged one widest gap back, where
    a pass surely ran; no beat entry at all means no pass will come, and
    everything due is late now.
    """
    from core.day_of_sauron import read_schedule, widest_gap

    from .views_day import STALE_FLOOR_S

    schedule = (read_schedule()[0].get(entry) or {}).get("schedule")
    if schedule is None:
        return now
    at = now - timedelta(seconds=STALE_FLOOR_S)
    fired = _last_fire(schedule, at)
    if fired is not None:
        return fired
    gap = widest_gap(schedule)
    return at - timedelta(seconds=gap) if gap else now


def _cut_off(entry, now):
    """_last_pass, fenced: a schedule that cannot be read leaves the old
    rule (everything past its due date is late) rather than a dash."""
    try:
        return _last_pass(entry, now)
    except Exception as exc:  # noqa: BLE001
        _warn_once(f"{entry} last pass", exc)
        return now


def _flag_not_due(now, horizons=()):
    """An unresolved flag whose horizon has not passed, as one database
    condition: the resolver's own rule (opportunity_scanner
    .resolve_pending_flags: `now < scanned_at + horizon_days days`), i.e.
    scanned_at > now − horizon_days days.

    For each horizon in `horizons` (the setups' own, read beside it) the
    cut-off is a constant and the test one comparison; any other horizon
    takes the per-row date arithmetic, which is exact everywhere and a
    Python function per row on SQLite. An explicit DurationField: without
    it Django adds the day count to the datetime as a plain number on
    SQLite and every flag reads past due.
    """
    span = ExpressionWrapper(F("horizon_days") * timedelta(days=1),
                             output_field=DurationField())
    exact = ExpressionWrapper(Value(now, output_field=DateTimeField()) - span,
                              output_field=DateTimeField())
    usable = sorted(h for h in horizons
                    if isinstance(h, int) and 0 <= h <= 3660)
    if not usable:
        return Q(scanned_at__gt=exact)
    cutoff = Case(*[When(horizon_days=h,
                         then=Value(now - timedelta(days=h),
                                    output_field=DateTimeField()))
                    for h in usable],
                  default=exact, output_field=DateTimeField())
    return Q(scanned_at__gt=cutoff)


def _cycle_scan():
    from signals.models_opportunity import OpportunityFlag, OpportunitySetup

    now = timezone.now()
    week = now - timedelta(days=7)
    last_pass = _cut_off("resolve-opportunity-flags", now)

    def _read_setups():
        armed = disarmed = 0
        horizons = set()
        for active, horizon in OpportunitySetup.objects.values_list(
                "is_active", "suggested_horizon_days"):
            if active:
                armed += 1
            else:
                disarmed += 1
            horizons.add(horizon)
        return {"armed": armed, "disarmed": disarmed, "horizons": horizons}

    setups = _Once(_read_setups)

    def _read_flags():
        try:
            horizons = setups()["horizons"]
        except Exception:  # noqa: BLE001 — the exact path needs none
            horizons = ()
        unresolved = Q(outcome="")
        return OpportunityFlag.objects.aggregate(
            week=Count("id", filter=Q(scanned_at__gte=week)),
            unresolved=Count("id", filter=unresolved),
            not_due=Count("id", filter=unresolved
                          & _flag_not_due(now, horizons)),
            # not due yet at the resolver's last pass: that pass could not
            # take them, so they are either not due or waiting, never late
            open_at_pass=Count("id", filter=unresolved
                               & _flag_not_due(last_pass, horizons)),
            no_price=Count("id", filter=Q(outcome="expired")))

    flags = _Once(_read_flags)
    resolver = _pass_words("resolve-opportunity-flags")

    try:
        when = _beat_words("scan-opportunities")
    except Exception as exc:  # noqa: BLE001
        _warn_once("scan schedule", exc)
        when = "its beat entry's time"
    try:
        armed = setups()["armed"]
        over = ("every armed setup: "
                f"{_rows_word(armed, 'armed setup', 'armed setups')} now")
    except Exception:  # noqa: BLE001 — its fact is the dash
        over = "every armed setup"

    return {
        "key": "scan",
        "title": 'The scan',
        "question": 'What is the platform watching, and what does it find?',
        "gate": _gate("pipeline_opportunity_scanner"),
        "facts": [
            _fact('setups armed', lambda: setups()["armed"],
                  qualifier='armed = is_active alone; the scan consults no '
                            'ladder'),
            _fact('setups disarmed', lambda: setups()["disarmed"],
                  tone="inert",
                  qualifier='never evaluated, and with no diagnostic verdict'),
            _fact('detections over 7 days', lambda: flags()["week"],
                  window="7 d",
                  qualifier='one row per pass while the match lasts, not one '
                            'per opportunity'),
            _fact('detections not due yet', lambda: flags()["not_due"],
                  tone="inert",
                  qualifier="inside their horizon: the resolver's own "
                            "not_due, the healthiest thing a flag can be"),
            _fact('detections due, waiting for the resolver',
                  lambda: flags()["open_at_pass"] - flags()["not_due"],
                  tone="inert",
                  qualifier="past their horizon since the resolver's last "
                            f"pass ({resolver}): its next pass resolves "
                            "them, and that is not late"),
            _fact('detections past due, unresolved',
                  lambda: flags()["unresolved"] - flags()["open_at_pass"],
                  tone="caution", window="all time",
                  qualifier="due before the resolver's last pass and still "
                            "unresolved: it is off, late or failing on them, "
                            "and if it is off they never will be",
                  alert_when=(">", 0), alert_words='the resolver is late'),
            _fact('detections graded "no price"', lambda: flags()["no_price"],
                  window="all time",
                  qualifier='ⓘ expired = no price data at the deadline, not '
                            '"window passed"'),
        ],
        "caveat": (
            f'The scan runs on the beat at {when} (scan-opportunities) over '
            f'{over}. The detection count follows how long a match '
            f'persists, not the number of distinct opportunities.'),
        "series": _spark(lambda: _series(OpportunityFlag, "scanned_at")),
    }


def _cycle_ladder():
    from signals.models_control import PromotionEvent, RuleControl

    def _read_rules():
        def _at(stage):
            return Count("id", filter=Q(promotion_stage=stage))
        return RuleControl.objects.aggregate(
            research=_at("research"), paper=_at("paper"),
            live_small=_at("live_small"), live_full=_at("live_full"),
            paused=Count("id", filter=Q(status="paused")))

    rules = _Once(_read_rules)
    moves = _Once(lambda: _series(PromotionEvent, "created_at"))

    return {
        "key": "ladder",
        "title": 'The promotion ladder',
        "question": 'What is allowed to act on what it finds?',
        "gate": _gate("pipeline_actuator", "pipeline_promotion"),
        "facts": [
            _fact('rules at research', lambda: rules()["research"],
                  tone="inert",
                  qualifier='cannot place an order AND its signals are '
                            'dropped from the vote: registering a rule '
                            'demotes it'),
            _fact('rules at paper', lambda: rules()["paper"], tone="inert"),
            _fact('rules at live reduced', lambda: rules()["live_small"],
                  tone="caution"),
            _fact('rules at live full', lambda: rules()["live_full"],
                  tone="caution"),
            _fact('rules paused', lambda: rules()["paused"], tone="inert"),
            _fact("transitions over 30 days", lambda: _spark_total(moves),
                  window="30 d",
                  qualifier="the only honest series of the ladder's "
                            "movement: the strip's own thirty days"),
        ],
        "caveat": (
            'A rule with NO ladder row is not ungoverned: it is treated as '
            'full-size paper. So the row count measures what is throttled, '
            'not what is covered.'),
        "series": _spark(moves),
    }


def _cycle_signals():
    from signals.models import Signal

    def _read():
        def _graded(value):
            return Count("id", filter=Q(outcome=value))
        return Signal.objects.aggregate(
            live=Count("id", filter=Q(is_active=True)),
            hit=_graded("hit_target"), stopped=_graded("stopped_out"),
            expired=_graded("expired"), manual=_graded("manual_close"),
            open_live=Count("id", filter=Q(outcome="", is_active=True)),
            open_closed=Count("id", filter=Q(outcome="", is_active=False)))

    sig = _Once(_read)

    def _v(key):
        return lambda: sig()[key]

    return {
        "key": "signals",
        "title": 'The signals',
        "question": 'How many opinions, and how many got an answer?',
        "gate": _gate("pipeline_signals"),
        "facts": [
            _fact("live signals", _v("live")),
            _fact('graded: target hit', _v("hit"), window="all time"),
            _fact('graded: stopped out', _v("stopped"), window="all time"),
            _fact('graded: expired', _v("expired"), window="all time"),
            _fact('graded: closed by hand', _v("manual"), window="all time"),
            _fact('still live, not graded yet', _v("open_live"),
                  tone="inert",
                  qualifier='its answer comes when it closes'),
            _fact('closed with no grade', _v("open_closed"), tone="caution",
                  window="all time",
                  qualifier='no longer live and never graded',
                  alert_when=(">", 0),
                  alert_words='an opinion with no answer is not evidence'),
        ],
        "caveat": (
            'A setup that matches thirty passes in a row produces ONE '
            'reused signal, not thirty. Detections and signals do not '
            'compare term for term.'),
        "series": _spark(lambda: _series(Signal, "created_at")),
    }


def _cycle_evolution():
    from brain.generator_models import GeneratedSetupProposal
    from signals.models_control import RuleMutation

    ideas = _Once(lambda: _tally(GeneratedSetupProposal, "created_at",
                                 "status"))

    def _status(value):
        return lambda: ideas()["by"].get(value, 0)

    mutations = _Once(lambda: RuleMutation.objects.aggregate(
        all=Count("id"),
        walk_forward=Count("id", filter=Q(score_method="walk_forward"))))

    return {
        "key": "evolution",
        "title": 'Evolution',
        "question": 'Does the platform invent, and what becomes of its ideas?',
        "gate": _gate("pipeline_evolution", "generator_auto_research"),
        "facts": [
            _fact('proposals pending', _status("pending"), tone="caution"),
            _fact('proposals approved', _status("approved"),
                  window="all time"),
            _fact('proposals refused', _status("rejected"),
                  window="all time",
                  qualifier='a refusal row is written on purpose: an idea '
                            'paid for and then refused must stay visible'),
            _fact('proposals expired', _status("expired"),
                  tone="inert", window="all time"),
            _fact('mutations actually backtested',
                  lambda: mutations()["walk_forward"], window="all time",
                  qualifier='only walk_forward means a backtest ran'),
            _fact('mutations never backtested',
                  lambda: mutations()["all"] - mutations()["walk_forward"],
                  tone="caution", window="all time",
                  qualifier='score_method "heuristic": an opinion, not a '
                            'measurement'),
        ],
        "caveat": (
            'Counting mutations as evidence of a backtest is the over-claim '
            'this page refuses: the column says which one was actually '
            'simulated.'),
        "series": _spark(lambda: ideas()["series"]),
    }


def _cycle_personas():
    from bot_program import personas
    from bot_program.models import AssetBotConfig

    wearing = []   # the map, once read: seven facts ask for it

    def _wearing_map():
        """The Python bucket persona_mix._wearing uses — never a JSON query.

        Read ONCE per render: seven facts ask for it and each read was a
        scan of every config on the platform (2026-09-28). The eligible
        count rides the same read (2026-11-06). A read that fails memoises
        nothing, so the next fact asks again inside its own fence."""
        from types import SimpleNamespace
        if wearing:
            return wearing[0]
        out, eligible = {}, 0
        classes = set(personas.PERSONA_ASSET_CLASSES)
        for pk, extras, enabled, asset_class in (
                AssetBotConfig.objects.values_list(
                    "pk", "extras", "enabled", "asset_class")):
            if asset_class in classes:
                eligible += 1
            key = personas.persona_of(SimpleNamespace(extras=extras or {}))
            if key:
                out.setdefault(key, []).append((pk, enabled))
        wearing.append((out, eligible))
        return wearing[0]

    def _count_for(key, only_enabled=False):
        def _inner():
            worn = _wearing_map()[0].get(key, [])
            if only_enabled:
                return sum(1 for _pk, en in worn if en)
            return len(worn)
        return _inner

    def _eligible_without():
        out, eligible = _wearing_map()
        worn = sum(len(v) for v in out.values())
        return max(0, eligible - worn)

    facts = [_fact('personalities defined', lambda: len(personas.PERSONAS),
                   kind="constant",
                   qualifier='a code constant, not a query')]
    for key in ("scalp", "swing", "position"):
        facts.append(_fact(f'configs carrying "{key}"', _count_for(key)))
        facts.append(_fact("… of which actually enabled", _count_for(key, True),
                           tone="caution",
                           qualifier='carrying a personality without being '
                                     'enabled runs nothing'))
    facts.append(_fact('eligible configs with no personality', _eligible_without,
                       qualifier='honest denominator: options can never '
                                 'carry one'))

    return {
        "key": "personas",
        "title": 'Personalities',
        "question": 'What kind of trader is each pool?',
        "gate": _gate("pipeline_asset_bots"),
        "facts": facts,
        "caveat": (
            'No trade carries a personality: attribution goes by the '
            "config's CURRENT personality, so changing personality "
            'reattributes the past. A misspelled personality reads '
            'everywhere as "carries none", without a single alert.'),
        "series": [],
    }


def _cycle_allocation():
    from bot_program.desk_models import DeskPlan
    from bot_program.share_models import SharePlan

    shares = _Once(lambda: SharePlan.objects.aggregate(
        proposed=Count("id", filter=Q(state="proposed")),
        applied=Count("id", filter=Q(applied_at__isnull=False)),
        expired=Count("id", filter=Q(state="expired"))))
    passes = _Once(lambda: _stored(
        DESK_PASSES_KEY.format(build=_build_id()),
        lambda: DeskPlan.objects.aggregate(
            shadow=Count("id", filter=Q(mode="shadow")),
            live=Count("id", filter=Q(mode="live"))),
        STORED_TTL, "desk passes counted", expect=_PASSES_KEYS))
    strip = _Once(lambda: _series(DeskPlan, "created_at"))

    return {
        "key": "allocation",
        "title": 'Allocation',
        "question": 'Is capital moving, or is this a rehearsal?',
        "gate": _gate("pipeline_share_allocator", "share_allocator_mode_live",
                      "pipeline_capital_desk", "capital_desk_mode_live"),
        "facts": [
            _fact('share plans proposed', lambda: shares()["proposed"],
                  tone="inert"),
            _fact('share plans actually applied', lambda: shares()["applied"],
                  window="all time",
                  qualifier='measured on applied_at, not on state: a '
                            'cancelled plan did move a share'),
            _fact('share plans expired', lambda: shares()["expired"],
                  tone="inert", window="all time",
                  qualifier='mostly replacements, not neglect'),
            _fact('desk passes in shadow', lambda: _part(passes, "shadow"),
                  tone="inert", window="all time",
                  qualifier='in shadow, a "moved" candidate moved nothing: '
                            'everything runs at full size'),
            _fact('desk passes live', lambda: _part(passes, "live"),
                  tone="caution", window="all time"),
            _fact('desk passes over 30 days', lambda: _spark_total(strip),
                  window="30 d",
                  qualifier="both modes, the strip's own thirty days"),
        ],
        "caveat": (
            'Nothing here moves money without a human until both live '
            'switches are on. Paper and live are never summed, anywhere.'),
        "series": _spark(strip),
    }


def _cycle_horizon():
    from brain.horizon_models import HorizonView

    def _read():
        def _status(value):
            return Count("id", filter=Q(status=value))
        ok = Q(status="ok")
        return HorizonView.objects.aggregate(
            ok=_status("ok"), rejected=_status("rejected"),
            error=_status("error"), running=_status("running"),
            newest_ok=Max("created_at", filter=ok),
            first_ok=Min("created_at", filter=ok))

    views = _Once(_read)

    def _age_days():
        newest = views()["newest_ok"]
        if newest is None:
            return None
        return (timezone.now() - newest).days

    try:
        first = views()["first_ok"]
        since = (f"the first completed view on this database dates from "
                 f"{first:%Y-%m-%d}" if first else
                 "no view has completed on this database yet")
    except Exception:  # noqa: BLE001 — its facts are the dashes
        since = "the first view's date could not be read"

    return {
        "key": "horizon",
        "title": 'The horizon',
        "question": 'Does the five-to-ten-year view exist, and does the '
                    'allocator use it?',
        "gate": _gate("agent_horizon", "pipeline_calibration"),
        "facts": [
            _fact("views completed", lambda: views()["ok"], window="all time"),
            _fact('views refused', lambda: views()["rejected"], tone="inert",
                  window="all time"),
            _fact('views in error', lambda: views()["error"], tone="caution",
                  window="all time", alert_when=(">", 0),
                  alert_words='a view failed: no reaper retries it'),
            _fact('views left "in progress"', lambda: views()["running"],
                  tone="caution",
                  qualifier='no reaper: a killed worker leaves the row that '
                            'way forever',
                  alert_when=(">", 0), alert_words='no reaper'),
            _fact('age in days of the view in use', _age_days, kind="days",
                  qualifier='past 45 days the allocator ignores it and '
                            'falls back to 1.00',
                  none_why="no view has completed yet",
                  alert_when=(">", 45),
                  alert_words='the allocator ignores it and uses 1.00'),
        ],
        "caveat": (
            "The horizon's calls come due at 6 and 12 months, and " + since
            + ': zero graded is honest until its first calls come due. '
            'Rendering that as "0% accuracy" would turn "not due yet" into '
            '"wrong".'),
        "series": [],
    }


#: A complete bot run stored before 2026-09-14 carries no `unmeasured` key
#: in its stats (see _bot_runs_before_the_fix). `has_key` is false for a
#: list, a scalar, JSON null and a dict without the key alike — exactly the
#: rows the Python loop counted (tests/test_oculus_truth pins the shapes).
_BEFORE_THE_FIX = Q(status="complete") & ~Q(stats__has_key="unmeasured")


def _bot_runs_before_the_fix():
    """Completed bot runs whose stats carry no `unmeasured` key.

    Until 2026-09-14 a signal with no bar after it was priced at 0.0 and
    booked as a −50 R expiry, and the config's time-stop ceiling was ignored
    entirely. Both are fixed, and every run stored since carries the
    `unmeasured` key. Its absence is therefore a reliable marker of a number
    computed by the old engine — which must not be read beside the new ones
    as though they measured the same thing.

    Asked of the database (2026-11-06): it was a Python loop over every
    run's stats JSON.
    """
    from bot_program.backtest_models import BotBacktestRun
    return BotBacktestRun.objects.filter(_BEFORE_THE_FIX).count()


def _signals_no_run_could_price():
    """Signals that qualified and had no bar after them, across all runs.

    A tolerant Python sum, kept as it was: a value that is not a number is
    skipped, never cast. Stored STORED_TTL by the backtests cycle."""
    from bot_program.backtest_models import BotBacktestRun
    total = 0
    for stats in BotBacktestRun.objects.filter(
            status="complete").values_list("stats", flat=True):
        if isinstance(stats, dict):
            block = stats.get("unmeasured") or {}
            try:
                total += int(block.get("signals_without_bars") or 0)
            except (TypeError, ValueError, AttributeError):
                continue
    return total


def _cycle_backtests():
    from backtester.models import BacktestRun
    from bot_program.backtest_models import BotBacktestRun

    engine = _Once(lambda: BacktestRun.objects.aggregate(
        all=Count("id"),
        completed=Count("id", filter=Q(status="completed")),
        no_trade=Count("id", filter=Q(status="completed", total_trades=0)),
        win_rate=Count("id", filter=Q(win_rate__isnull=False))))
    complete = Q(status="complete")
    bots = _Once(lambda: BotBacktestRun.objects.aggregate(
        all=Count("id"),
        complete=Count("id", filter=complete),
        before_fix=Count("id", filter=_BEFORE_THE_FIX),
        newest=Max("id", filter=complete),
        newest_at=Max("created_at", filter=complete)))

    def _unsimulated():
        b = bots()
        fingerprint = [b["complete"], b["newest"],
                       b["newest_at"].isoformat() if b["newest_at"] else None]
        return _stored(UNSIMULATED_KEY.format(build=_build_id()),
                       _signals_no_run_could_price,
                       STORED_TTL, "counted", fingerprint=fingerprint)

    return {
        "key": "backtests",
        "title": 'The backtests',
        "question": 'What was simulated before it was believed?',
        "gate": [],
        "facts": [
            _fact("engine v1 runs", lambda: engine()["all"],
                  window="all time"),
            _fact("… completed", lambda: engine()["completed"],
                  window="all time",
                  qualifier='the literal is "completed"'),
            _fact('… completed with no trade at all',
                  lambda: engine()["no_trade"], window="all time",
                  qualifier='ⓘ a result, not a failure'),
            _fact('… carrying a MEASURED win rate',
                  lambda: engine()["win_rate"], window="all time",
                  qualifier='NULLs are unknown, never 0%'),
            _fact('bot runs', lambda: bots()["all"], window="all time"),
            _fact("… complete", lambda: bots()["complete"], window="all time",
                  qualifier='here the literal is "complete", with no -d: a '
                            'shared filter would return 0 forever'),
            _fact('… computed before the 09-14 fix',
                  lambda: bots()["before_fix"], window="all time",
                  qualifier='ⓘ a signal with no bar was worth −50 R there '
                            'and the time cap did not exist: these numbers '
                            'do not compare with the later ones'),
            _fact('signals a run could not simulate', _unsimulated,
                  window="all time",
                  qualifier='ⓘ no bar after the signal — set aside and '
                            'counted, never averaged'),
        ],
        "caveat": (
            'Two tables, two status vocabularies one letter apart, and two '
            'units for the win rate (a percentage on one side, a fraction '
            'on the other). They are never summed here. No backtest gates a '
            'promotion: the automatic ladder runs in memory and writes no '
            'row. On 09-14 the bot simulator changed in four ways: a signal '
            'with no bar is no longer a −50 R loss but a signal set aside '
            'and counted, a gap through the stop fills at the open rather '
            'than at the stop, "expired" no longer covers "the bar feed '
            'stops here", and the bot\'s own time cap is finally honoured. '
            'Earlier runs were not measuring the same bot.'),
        "series": [],
    }


def _cycle_trust():
    from ai_agents.models import AgentPrediction

    now = timezone.now()
    base = AgentPrediction.objects.filter(prediction_type="direction")
    awaiting = Q(was_correct__isnull=True, evaluated_at__isnull=True)
    # The nightly grader of every agent's calls but the Mind's, which grades
    # its own hourly: the older pass, so a call is never called late before
    # the grader that takes it has had its pass.
    grader = "resolve-pending-calibrations"

    def _read_calls():
        last_pass = _cut_off(grader, now)
        return base.aggregate(
            right=Count("id", filter=Q(was_correct=True)),
            wrong=Count("id", filter=Q(was_correct=False)),
            awaiting=Count("id", filter=awaiting),
            not_due=Count("id", filter=awaiting
                          & Q(expected_resolution_at__gt=now)),
            # due after the grader's last pass: waiting, not late (a call
            # with no due date is never taken by any pass: late)
            open_at_pass=Count("id", filter=awaiting
                               & Q(expected_resolution_at__gt=last_pass)),
            unsettled=Count("id", filter=Q(was_correct__isnull=True,
                                           evaluated_at__isnull=False)),
            agents=Count("agent", distinct=True))

    calls = _Once(lambda: _stored(
        PREDICTIONS_KEY.format(build=_build_id()), _read_calls,
        STORED_TTL, "counted", expect=_CALLS_KEYS))
    graded_at = _pass_words(grader)

    def _v(key):
        return lambda: _part(calls, key)

    return {
        "key": "trust",
        "title": 'Confidence',
        "question": 'Did what the platform asserted turn out to be true?',
        "gate": _gate("pipeline_calibration"),
        "facts": [
            _fact('direction calls graded right', _v("right"),
                  window="all time"),
            _fact('direction calls graded wrong', _v("wrong"),
                  window="all time"),
            _fact('calls not due yet', _v("not_due"), tone="inert",
                  qualifier='their due date is ahead: the market has not '
                            'been asked yet'),
            _fact('calls due, waiting for the grader',
                  lambda: _part(calls, "open_at_pass", minus="not_due"),
                  tone="inert",
                  qualifier="due since the nightly grader's last pass "
                            f"({graded_at}): its next pass grades them, and "
                            "that is not late"),
            _fact('calls past due, ungraded',
                  lambda: _part(calls, "awaiting", minus="open_at_pass"),
                  tone="caution", window="all time",
                  qualifier="due before the nightly grader's last pass, or "
                            "with no due date, and never graded: no grader "
                            "reaches them",
                  alert_when=(">", 0), alert_words='nobody is grading'),
            _fact('calls the market could not settle', _v("unsettled"),
                  tone="inert", window="all time",
                  qualifier='resolved and permanently unmeasurable'),
            _fact('agents carrying at least one call', _v("agents"),
                  window="all time"),
        ],
        "caveat": (
            'A confidence of 1.00 means two opposite things: well '
            'calibrated, or fewer than ten graded calls. An accuracy rate '
            'without its sample size is not a fact. Flat counts as wrong, '
            'so the baseline is not 50%.'),
        "series": _spark(lambda: _series(AgentPrediction, "created_at",
                                         extra={"prediction_type":
                                                "direction"})),
    }


#: Why a probe tally is not on the page when none is stored: probe_routes
#: has never run, the cache was flushed, or its seven days ran out. Not a
#: deploy: Redis keeps its data across one (an appendonly volume).
PROBE_MISSING = "no probe stored: never run, cleared, or older than 7 days"

#: Why it is not on the page when the stored one ran before this image.
PROBE_BEFORE_BUILD = "no probe since this build"


def _probe(field, built=None):
    """One count from the probe's stored tally, with its age (§5.1).

    `manage.py probe_routes` leaves it in the cache for seven days. Not
    there is a dash that says so — never "0 pages raise" — and a tally
    with no time is not printed either.

    DATED AGAINST THE BUILD (2026-11-07, review). `built` is when this
    image was built (seconds since the epoch, None when unstamped). Redis
    keeps its data across a deploy, so the previous image's tally survives
    one; it describes the previous image's pages, and the forge exists to
    catch the pages a deploy broke. A tally older than the build is a dash
    until probe_routes runs on this one."""
    from django.core.cache import cache
    fix = "manage.py probe_routes"
    try:
        stored = cache.get(PROBE_KEY)
    except Exception as exc:  # noqa: BLE001
        _warn_once("forge probe", exc)
        raise _Unmeasured("the cache could not be read") from exc
    if not isinstance(stored, dict):
        raise _Unmeasured(PROBE_MISSING, fix)
    at = stored.get("at")
    timed = not isinstance(at, bool) and isinstance(at, (int, float))
    if timed and built is not None and at < built:
        raise _Unmeasured(PROBE_BEFORE_BUILD, fix)
    if stored.get("state") != "ran":
        raise _Unmeasured(
            "the last probe could not run "
            f"({stored.get('why') or 'no reason stored'})", fix)
    if not timed:
        raise _Unmeasured("the stored probe carries no time", fix)
    value = int((stored.get("counts") or {}).get(field, 0))
    return _Reading(value, at, f"probed {_ago(time.time() - at)}")


def _cycle_forge(staff=True):
    """THE FORGE — the state of the code that is running, not of the market.

    Every other cycle answers a question about trading. This one answers
    the question the platform could not answer about ITSELF, and the one
    that cost a whole day on 2026-09-13: WHICH COMMIT AM I, and is what I
    am running the thing that was written?

    The blindness was total. `.dockerignore` excludes `.git`, so the
    container had no sha; nothing was stamped at build time; the box
    served the previous commit for a day while two pages answered 404,
    and the only way to discover it was probing the public site route by
    route from outside. A stamp and a timestamp would have made it a
    five-second glance.

    It reports and does not act — and that is the honest state of the
    forge today. The lane where an agent proposes a patch and a human
    approves it from this page is the next brick; a table of proposals
    that do not exist yet would be a panel of em dashes pretending to be
    a feature.

    Staff's, like the switches (STAFF_ONLY_CYCLES): the sha and the
    pending migrations are what /ops/ and /health/ keep from any other
    login, and the guard scan reads every .py file of the image — the
    page's one costly read, made only for the reader who gets its answer.

    ONCE PER BUILD (2026-11-06). The scan and the plan ran on every staff
    GET; their answers change per image. The scan is stored under the
    image (its sha and build time, `_build_id`: a same-sha rebuild is
    another image) until the cache is cleared (unstamped: STORED_TTL), the
    plan STORED_TTL because `migrate` can run on the same image, and each
    prints when it was checked. The probe's tally counts only when it ran
    on this image.
    """
    if not staff:
        return _withheld("forge", 'The forge',
                         'Which code is this platform running, and is it '
                         'the code that was written?')
    from core.build_stamp import stamp

    st = stamp()
    build = _build_id()
    built = _epoch(st["built_at"])

    def _pending_migrations():
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor
        executor = MigrationExecutor(connection)
        targets = executor.loader.graph.leaf_nodes()
        return len(executor.migration_plan(targets))

    def _tests_published():
        from core.wall_facts import TESTS_GREEN
        return TESTS_GREEN

    def _unregistered_guards():
        """Guarded task keys with no component row — the defect that hid
        three never-running tasks until 2026-09-13."""
        import re
        from pathlib import Path

        from django.conf import settings
        from core.platform_control import DEFAULT_COMPONENTS
        declared = {c["key"] for c in DEFAULT_COMPONENTS}
        skip = {".git", ".venv", "venv", "__pycache__", "staticfiles",
                "static", "node_modules", ".pytest_cache", "test_backups",
                "migrations",
                # the agents' worktrees: whole copies of this tree, on a
                # dev checkout only (.dockerignore drops them)
                ".claude"}
        pattern = re.compile(r"""guarded_task\(\s*["']([A-Za-z0-9_]+)["']""")
        root = Path(settings.BASE_DIR)
        used = set()
        for path in root.rglob("*.py"):
            if any(p in skip for p in path.relative_to(root).parts):
                continue
            used.update(pattern.findall(
                path.read_text(encoding="utf-8", errors="replace")))
        return len(used - declared)

    return {
        "key": "forge",
        "title": 'The forge',
        "question": 'Which code is this platform running, and is it the '
                    'code that was written?',
        "gate": [],
        "facts": [
            _text_fact('commit of this image', lambda: st["sha"],
                       qualifier='stamped at build time by deploy/dc; a '
                                 'dash means the image was not stamped, '
                                 'never an invented sha',
                       none_why="the image was not stamped",
                       fix="deploy/dc stamps it at build time"),
            _fact('build age, in hours', lambda: st["age_hours"],
                  kind="hours", tone="caution",
                  qualifier='the age is the fact that matters: a sha tells '
                            'a human nothing, "built 31 h ago" on a branch '
                            'that moved this morning tells everything',
                  none_why="the image carries no build time",
                  fix="deploy/dc stamps it at build time"),
            _fact('migrations pending',
                  lambda: _stored(FORGE_MIGRATIONS_KEY.format(build=build),
                                  _pending_migrations, STORED_TTL,
                                  "plan checked"),
                  tone="caution",
                  qualifier='not applied on THIS database: a deploy without '
                            'them serves pages against a schema that is not '
                            'there',
                  alert_when=(">", 0), alert_words='manage.py migrate'),
            _fact('tests published on the wall', _tests_published,
                  kind="constant",
                  qualifier='a constant, recounted at each merge: the number '
                            'the public page shows; tests/test_wall_facts '
                            'fails when it drifts'),
            _fact('guarded tasks with no switch',
                  lambda: _stored(FORGE_GUARDS_KEY.format(build=build),
                                  _unregistered_guards,
                                  None if st["sha"] else STORED_TTL,
                                  "scan checked", at_build=bool(st["sha"])),
                  tone="caution",
                  qualifier='a guarded_task key with no row reads OFF and '
                            'the task never runs — three were, from the '
                            'beginning, found on 2026-09-13',
                  alert_when=(">", 0),
                  alert_words='a task that can never run'),
            # THE PAGES THEMSELVES. 305 URL patterns and 243 named routes no
            # test touches (measured 2026-09-23); the suite cannot see a page
            # that renders 500. `manage.py probe_routes` GETs every
            # argument-free route as a superuser and leaves its tally in
            # the cache; these two read it, with its age. Never run on this
            # image is a dash — the probe is a human's command and this lane
            # only reports.
            _fact('pages that raise, at the last probe',
                  lambda: _probe("broken", built), tone="caution",
                  qualifier='5xx or a raise on a GET as a superuser; a dash '
                            'means no probe of this build is stored, never '
                            'that no page raises',
                  alert_when=(">", 0), alert_words='a page raises on a GET'),
            _fact('pages answering 404, at the last probe',
                  lambda: _probe("missing", built), tone="caution",
                  qualifier='a route wired to nothing that answers — the '
                            'defect that hid for a day on 2026-09-13',
                  alert_when=(">", 0), alert_words='a route answers 404'),
        ],
        "caveat": (
            'This lane REPORTS; it does not act yet, and that is the honest '
            'state of the forge today. It knows which commit the image was '
            'built from; it cannot know whether that commit is still the '
            'latest — the image has neither git nor guaranteed network. '
            'That was already all that was missing on 13 September. The '
            'scan and the plan are read once per build and stored; each '
            'prints when it was checked. A probe counts only when it ran on '
            'this build: the cache outlives a deploy.'),
        "series": [],
    }


BUILDERS = (
    _cycle_forge,
    _cycle_gates,
    _cycle_scan,
    _cycle_ladder,
    _cycle_signals,
    _cycle_evolution,
    _cycle_personas,
    _cycle_allocation,
    _cycle_horizon,
    _cycle_backtests,
    _cycle_trust,
)


def _not_measured_row(name, parts, why, fix):
    return {"name": name, "place": " · ".join(parts),
            "why": why or "nothing to measure yet", "fix": fix or ""}


def oculus(user=None) -> dict:
    """Every cycle, fenced one by one. Never raises.

    A cycle whose builder dies is REPORTED AS DEAD rather than dropped:
    a missing panel reads as "there is no such cycle", which is a lie of
    omission the operator cannot see. A broken one says so.

    `user` adds THE BOOK — the one per-viewer panel. Without it the page
    is entirely platform-wide, which is what an anonymous or system
    caller should get: a book pooled across users would be a number
    nobody could act on.

    `user` also decides what may be read (2026-09-28). /health/'s rule,
    as the cockpit applies it (views_ops.ops_dashboard: is_staff or
    is_superuser): the switches and the forge are staff's, and so are
    the gate chips on every panel, which are switch states. Any other
    login gets those two cycles as a header and the STAFF_ONLY caveat,
    and no chip. No user is the shell, which is the operator: it reads
    everything.

    Every dash is named (2026-11-06): `degraded` lists each by name, the
    book's included, and `not_measured` carries each one's place, its
    reason in words and the command that fixes it, for the page's foot.
    """
    staff = user is None or bool(getattr(user, "is_staff", False)
                                 or getattr(user, "is_superuser", False))
    cycles, degraded, not_measured = [], [], []
    builders = list(BUILDERS)
    if user is not None and getattr(user, "is_authenticated", False):
        book_user = _with_broker_rows(user)
        builders.insert(0, lambda: _cycle_book(book_user))
    token = _RENDER.set(_Render(staff=staff))
    try:
        for builder in builders:
            name = getattr(builder, "__name__", "_cycle_book")
            if name == "<lambda>":
                name = "_cycle_book"
            key = name.replace("_cycle_", "")
            try:
                if not staff and key in STAFF_ONLY_CYCLES:
                    cycle = builder(staff=False)
                else:
                    cycle = builder()
            except Exception as exc:  # noqa: BLE001
                logger.warning("oculus: cycle %s failed (%s)", name, exc)
                degraded.append(name)
                why, fix = _why(exc)
                not_measured.append(_not_measured_row(name, (key, "the whole cycle"),
                                                      why, fix))
                cycles.append({
                    "key": key,
                    "title": key.title(),
                    "question": "",
                    "gate": [],
                    "facts": [],
                    "caveat": 'This cycle could not be read. The missing '
                              'number is not a zero.',
                    "series": [],
                    "dead": True,
                })
                continue
            cycle.setdefault("dead", False)
            cycle.setdefault("staff_only", False)
            if not staff:
                # The chips are switch states, every one of them staff's;
                # the panel says so in their place.
                cycle["gate"] = []
                cycle["gate_withheld"] = True
            # The spark's own scale. Each strip is scaled to ITSELF, never
            # to the busiest cycle on the page: one shared axis would
            # flatten every slow cycle into a line of nothing and read as
            # "dead" when the honest reading is "slower than the scanner,
            # by design".
            series = cycle.get("series") or []
            cycle["max_n"] = max((p["n"] for p in series), default=0)
            # The way OUT of the panel. Resolved here rather than in the
            # template so a renamed route costs one link, not the page.
            cycle["pages"] = _pages_for(cycle.get("key", ""))
            for fact in cycle.get("facts", []):
                if fact.get("value") is UNMEASURED:
                    degraded.append(f"{cycle['key']}.{fact['label']}")
                    not_measured.append(_not_measured_row(
                        f"{cycle['key']}.{fact['label']}",
                        (cycle["key"], fact["label"]),
                        fact.get("why"), fact.get("fix")))
            for venue in cycle.get("venues", []):
                for fact in venue.get("facts", []):
                    if fact.get("value") is UNMEASURED:
                        name_ = f"book.{venue['venue']}.{fact['label']}"
                        degraded.append(name_)
                        not_measured.append(_not_measured_row(
                            name_, ("book", venue["venue"], fact["label"]),
                            fact.get("why"), fact.get("fix")))
            # The worlds by their words (REAL MONEY, DEMO, PAPER), apart
            # from the desk's venues (live, paper) that sit below them.
            for world in cycle.get("worlds", []):
                for fact in world.get("facts", []):
                    if fact.get("value") is UNMEASURED:
                        name_ = f"book.{world['word']}.{fact['label']}"
                        degraded.append(name_)
                        not_measured.append(_not_measured_row(
                            name_, ("book", world["word"], fact["label"]),
                            fact.get("why"), fact.get("fix")))
            for row in cycle.pop("missing", []):
                degraded.append(row["name"])
                not_measured.append(_not_measured_row(
                    row["name"], row["parts"], row["why"], row["fix"]))
            cycles.append(cycle)
    finally:
        _RENDER.reset(token)
    return {
        "generated_at": timezone.now(),
        "window_days": WINDOW_DAYS,
        "cycles": cycles,
        "degraded": degraded,
        "not_measured": not_measured,
    }
