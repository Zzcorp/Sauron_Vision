"""THE SCHEDULER (the O2 spec A.7, A.11-A.27, A.51-A.56; O2a, 2026-11-05):
the Orcs' queue and its money, around one wake's read (mind.py). The render
pass (wake.render_queued, on `slow`) calls absorb before each wake's render
and admit after it; a pass that admitted a wake sends one orc_think
ticket. Only this module writes `pending`, and `recorded` again on a wake
it sends back to the render (A.3). With the minds switch OFF (as it ships)
or the Orcs line at 0, admission answers every wake by code and nothing
is claimed: the worker (tasks.orc_think) and the watchdog
(tasks.orc_minds_watch) run idle.

  absorb   A.7 step 1 (P15), before a wake's render, under its Orc's lock:
           the Orc's pending wake is merged into it (the union of the
           reasons by key, each keeping its own urgency; the first send
           inherited as components["queued_at_inherited"]); the older
           wake becomes `merged`
  admit    A.11, after the render, the Orc's lock taken for the status
           write only. A quiet wake stays quiet; otherwise the first check
           that fails answers it by code (`skipped` with its code, a
           `budget` entry while the minds switch itself is on), in this
           order: the four gates; the Orc dead, the row closed; the
           dossier over its size cap; the breaker; the Orc's day caps
           (A.12); the triage and the core's floor (A.13, A.18); the
           spacing (A.15). Else `pending`: dedupe_key "orc<pk>:pending"
           (the database then holds one pending wake per Orc), the tick's
           key kept in components["record_key"], queued_at set once, the
           priority its rank (A.14), the answering rung and A.21's bound
           (B.2b; O2b, 2026-11-06: r0 while the router's switch is OFF,
           as O2a; ON, the rung the router chose, on a dossier rendered
           for its family, with the fallback's bound for a real-money
           wake on r2-r5)
  claim    A.18, one short transaction per examined candidate, best first
           (-priority, queued_at, id): the line lock, the candidate's Orc
           row (skip_locked: a row the tick or a close holds stays
           `pending`), the wake. One call in flight per Orc; A.11 steps
           2-8 again with the money in flight and held, then the line
           (A.20); the cold-burst rule (A.16). The rung is read again
           first (O2b, 2026-11-06): the admitted rung while the router's
           switch is ON, through the effort map; r0, re-priced, once it is
           OFF (frictionless off). A pass writes `running`,
           started_at, est_usd (the bound), the rung's model, the Orc's
           last_wake_at and its two count counters; the call follows with
           no lock held. A wake past the stale clock (A.55) is never sent:
           answered `paused` after a pause of the watchdog, as a returning
           `orcs` or platform master leaves it, else left to the watchdog
  run      A.19: claim and think one wake at a time, the four gates read
           again at each claim, for THINK_RUN_S at most
  settle   A.24-A.26 (below), then the Orc's states (A.51-A.53) and the
           breaker (A.56)
  watch    A.54-A.56 (orc_minds_watch, on `slow`): the stall alarm, the
           stale and backlog closes, the wall time, the holds, the
           breaker, the ledger gaps; and a ticket past its wall time made
           an orphan hold (A.57). A call the worker sent that is still
           inside its wall time (a running wake's, a probe's or a twin's
           ticket) keeps the worker busy, never silent: from O2b an r3 or
           r4 call may run past the 30-minute stale clock (2026-11-06,
           completing O2b)
  tickets  A.57 (O2a's arm, 2026-11-05): every model call that is not a
           wake (from O2a, `orcs smoke --row`; from O2b the probes) holds
           its bound through reserve_ticket, under the line lock: its
           caller and rung a row of §1.0.9, its request refused by code
           above TICKET_MAX_TOKENS, the four gates and the caller's own
           switch, its item (one billed attempt), its day cap by its key,
           its class's ceiling and the core's floor, a probe's own
           allowance, then the line, with the money in flight and held.
           settle_ticket releases it as the settle releases a wake's, the
           ledger check included
  pairs    B.12 (O2b's probes, 2026-11-06): store_pair writes one probe
           pair (OrcTierGrade), its block counted under the line lock;
           probes.py builds it with no lock held
  Fable    B.9, B.10 (O2b's frontier, 2026-11-06): fable_money, the money
           clauses of Fable's gate (the pair priced at the dossier's size
           cap under the wake's class's ceiling, the deep share and the
           core's floor), which the render pass reads; an r5 wake's claim
           reads the frontier's switch again (OFF: r4 as B.5 maps it
           answers, from the stored Fable dossier), and under the line lock
           real money and the frontier quota left, then weighs the money
           once for the whole pair and reserves both in its one
           transaction: the wake's est_usd r5's bound, the twin's ticket
           (caller twin, its `pair` the wake) its own. In O2 the pair is
           above the core's $3.00 floor, so no r5 wake is ever admitted

THE MONEY (N3): every check of the line reads its cap, what it booked
today and the OTHER calls' money in flight and held, through mind.py
(the gateway's reads: the ledger's sums and the settings, never a call),
so this module names no gateway and holds its locks over database reads
and writes only (N8). A call's own reservation is never counted twice.
THE DEEP SHARE (B.13; O2b, 2026-11-06): spend.can_spend holds the deep and
frontier tiers to 70% of the line on its BOOKED spend alone, so admission,
the claim and reserve_ticket also hold the booked spend, the money in
flight and held and this bound within that share for a call on those
tiers (r2-r5, the tier read through mind.price), else `deep_share`. A
real-money urgent wake is exempt (decision D30); a ticket never is.
THE PROBES' OWN ALLOWANCE (B.11; O2b's probes, 2026-11-06): a probe's
ticket is also held to the probes' booked spend today (the ledger's probe
rows, read through mind.py), their tickets and holds in flight and this
bound within OrcSetting "probes_usd_per_day" (15% of the line's cap by
default), else `probe_allowance`; and its day cap is counted by (caller,
kind, user): 6 boundary probes and 40 h0 probes a user a day.

THE SETTLE. Validation, the officer and the lookup of the provider's
ledger row have run already, with no lock held (N8, mind.py). Then one
short transaction, on every outcome, under
the line lock (OrcSetting "minds_lock") and the Orc's row lock, in that
order, each waited for 2 s at most, doing only database reads and writes:

  1. book the usage on the decision or error entry's columns
  2. add the cost to the Orc's day dollars (and to the routine ones for a
     routine wake), the four day counters reset lazily on the UTC day
     (seen["counters_day"]), as the line's day is
  3. release the reservation (est_usd = 0) only once the provider's own
     ledger row of this call is found (outcome["ledger"]: the lookup ran
     before the locks, through the gateway); none found holds the booked
     cost as a
     `ledger_gap` until 00:00 UTC. A call that came back without a bill
     keeps its bound held as `unbilled` until 00:00 UTC, its HIGH counted
     in the Orc's seen["unbilled_usd"] (A.12): Anthropic may bill the
     tokens of a cut call
  4. finished_at = now, the answer's time (components.as_of keeps the
     render's moment)
  5. read the row again (A.26): the position open, the Orc alive, the four
     gates ON, or the answer is `late`, booked and journaled, nothing
     applied; else the outcome's writes (mind.write_*)
  6. send a pending wake of the same Orc back to the render: status
     `recorded`, components.render "queued", components.journal_as_of =
     now, queued_at kept

A wake that is no longer running when its settle comes (a wall-timed
call settling late) books its real cost on an error entry and writes
nothing else (A.55); its orphan hold goes by what came back, as a
ticket's does (A.24, A.25): a bill with its ledger row drops it, a bill
with none holds the booked cost as `ledger_gap`, a call never sent drops
it, and a call with no bill keeps it until 00:00 UTC (_late_hold).

THE MONEY HELD (OrcSetting "minds_inflight"): {key: {kind, usd, high,
orc, wake, rung, at, until}}. Every hold counts in the line's in-flight
sum (mind_gateway.inflight_usd) until it expires at 00:00 UTC, never
earlier; a late settle drops its own only once its bill is booked with
its ledger row, or when its call was never sent (_late_hold).
"""
import logging
import math
import time
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from bot_program.orcs.constants import (BREAKER_FAILS, BREAKER_PAUSE_MIN,
                                        BREAKER_WINDOW_MIN,
                                        CARE_AFTER_FAILED,
                                        CARE_AFTER_REFUSED,
                                        CARE_ANSWERS_REFUSED,
                                        CARE_CALLS_FAILING, CARE_WORDS,
                                        CARE_WORKER_SILENT, CLASS_PAPER,
                                        CLASS_PAPER_URGENT, CLASS_REAL,
                                        CLASS_REAL_URGENT, CODE_BACKLOG,
                                        CODE_BREAKER, CODE_DAY_CAP,
                                        CODE_DEAD, CODE_DEEP_SHARE,
                                        CODE_DOLLAR_CAP,
                                        CODE_EXPIRED, CODE_INFLIGHT,
                                        CODE_ITEM_BUSY, CODE_ITEM_CLOSED,
                                        CODE_OVER_BUDGET,
                                        CODE_PAUSED, CODE_PROBE_ALLOWANCE,
                                        CODE_QUIET,
                                        CODE_ROUTINE_CAP, CODE_ROW_CLOSED,
                                        CODE_SPACING, CODE_TRIAGE,
                                        CODE_WALL_TIME, CODE_WORKER_SILENT,
                                        COLD_MODEL_MIN, DEEP_TIERS,
                                        FRONTIER_RUNG, HIGH,
                                        HOLD_LEDGER_GAP, HOLD_ORPHAN,
                                        HOLD_TICKET, HOLD_UNBILLED,
                                        ITEM_BILLED, ITEM_CLOSED, ITEM_EXPIRED,
                                        ITEM_FAILED, ITEM_RESERVED,
                                        ITEM_UNBILLED, ITEM_UNSENT,
                                        ITEM_WAITING, LINE_LOCK_TIMEOUT_MS,
                                        MIN_WAKE_SPACING_MIN,
                                        MINDS_BREAKER_KEY,
                                        MINDS_INFLIGHT_KEY, MINDS_LOCK_KEY,
                                        MINDS_TICKETS_KEY,
                                        MINDS_WATCH_LAST_KEY, O2A_RUNG,
                                        OFFICER_REFUSE,
                                        ORC_STATEMENT_TIMEOUT_MS,
                                        PER_ORC_DAILY_KEY,
                                        PER_ORC_DAILY_USD, PER_ORC_HIGH_KEY,
                                        PROBE_CALLER, PROBE_KINDS,
                                        PROBES_PER_DAY, PROBES_PER_DAY_KEY,
                                        PROBES_USD_KEY, PROBES_USD_SHARE,
                                        RANKS, REPLY_ANSWER, REPLY_CLOSED,
                                        REPLY_UNBILLED, REPLY_UNSENT,
                                        ROUTINE_SHARE,
                                        ROUTINE_SHARE_KEY, SEAT_WINDOW,
                                        STALE_MIN, STALL_MIN, STATE_ACTIVE,
                                        STATE_BORN, STATE_CARE_OWNED,
                                        STATE_DEAD, THINK_RUN_S,
                                        TICKET_CLASS, TICKET_DAY_CAP,
                                        TICKET_ITEMS_KEEP_DAYS,
                                        TICKET_MAX_TOKENS, TICKET_RETRIES,
                                        TRIAGE, TRIAGE_KEY, TWIN_CALLER,
                                        TWIN_RUNG, VENUE_LIVE,
                                        WAKE_CODE_WORDS,
                                        WAKE_STATUS_DONE, WAKE_STATUS_FAILED,
                                        WAKE_STATUS_MERGED,
                                        WAKE_STATUS_PENDING,
                                        WAKE_STATUS_QUIET,
                                        WAKE_STATUS_RECORDED,
                                        WAKE_STATUS_REFUSED,
                                        WAKE_STATUS_RUNNING,
                                        WAKE_STATUS_SKIPPED,
                                        WAKE_STATUS_STALE, WAKES_PER_DAY_KEY,
                                        WALL_S, WATCH_PAUSED_MIN)

logger = logging.getLogger(__name__)

#: The four day counters (models.py) and the memory key of their day.
COUNTERS = ("llm_wakes_today", "routine_wakes_today", "spend_today_usd",
            "routine_spend_today_usd")
COUNTERS_DAY = "counters_day"
#: A wake is routine when every reason is one of these, or a plan's watch.
ROUTINE_CODES = ("W2", "W11")
#: How many pending wakes one claim examines, best first.
CLAIM_SCAN = 50
#: A rendered wake admission may act on: the O1 render's statuses.
ADMISSIBLE = (WAKE_STATUS_SKIPPED, WAKE_STATUS_RECORDED)
#: The codes that answer a wake by code for budget (§2.6 item 8).
BUDGET_CODES = (CODE_TRIAGE, CODE_INFLIGHT, CODE_DAY_CAP, CODE_ROUTINE_CAP,
                CODE_DOLLAR_CAP, "line", "total", "deep_share")
#: The return's words (A.53).
RETURN_WORDS = "The Orc reads its position again: it cited the takeover."
#: A.55 (2026-11-06, completing O2b): the ticket callers the `orcs` worker
#: itself sends (the probes, after its claims; r5's blind twin, beside its
#: wake). One of their calls inside its wall time keeps the worker busy;
#: the smoke is sent from the shell, never by the worker.
WORKER_TICKET_CALLERS = (PROBE_CALLER, TWIN_CALLER)


def _utc(now):
    return now.astimezone(dt_tz.utc)


def utc_day(now) -> str:
    """The UTC date the line's day and the counters' day are (A.12)."""
    return _utc(now).date().isoformat()


def next_midnight(now) -> datetime:
    """00:00 UTC after `now`: when every hold expires (A.25)."""
    day = _utc(now).date() + timedelta(days=1)
    return datetime(day.year, day.month, day.day, tzinfo=dt_tz.utc)


def _parse(value):
    from django.utils.dateparse import parse_datetime
    if isinstance(value, datetime):
        return value
    try:
        return parse_datetime(str(value)) if value else None
    except (TypeError, ValueError):
        return None


def high(rung) -> float:
    """A.12's HIGH of a rung: OrcSetting "per_orc_high" once a week's p90
    is measured, else §2.2's high column."""
    from bot_program.orcs.models import OrcSetting
    over = OrcSetting.get(PER_ORC_HIGH_KEY) or {}
    try:
        if isinstance(over, dict) and rung in over:
            return float(over[rung])
    except (TypeError, ValueError):
        pass
    return float(HIGH.get(str(rung), max(HIGH.values())))


def is_routine(reasons) -> bool:
    """Every reason a W2, a W11 or a plan's own watch (A.12)."""
    rs = [r for r in reasons or () if isinstance(r, dict)]
    return bool(rs) and all(r.get("code") in ROUTINE_CODES
                            or r.get("source") == "plan" for r in rs)


def is_urgent(reasons) -> bool:
    """A.14: any reason urgent; a reason from the plan's own watch never
    makes a wake urgent (A.48)."""
    return any(isinstance(r, dict) and r.get("urgent")
               and r.get("source") != "plan" for r in reasons or ())


# ── the money world, the class and the rank (A.13, A.14) ─────────────────

def is_real(orc, row=None) -> bool:
    """A.14 (§4 Q6): real money only when BOTH the Orc's seat is live and
    the row's own world (dashboard.position_summary.world_of) is live. A
    demo row, a paper row and a row that states no world are budgeted as
    paper: birth.world maps no world to live, so it is never read for the
    budget. An unreadable one is paper."""
    try:
        from dashboard.position_summary import world_of
        seat = orc.seat
        row = row if row is not None else orc.root_trade
        return (str(seat.venue or "") == VENUE_LIVE
                and world_of(row) == VENUE_LIVE)
    except Exception as e:  # noqa: BLE001 — unread is never real money
        logger.info("[orcs] Orc %s: the money world unread: %s",
                    getattr(orc, "pk", "?"), e)
        return False


def triage_class(real, urgent) -> str:
    if real:
        return CLASS_REAL_URGENT if urgent else CLASS_REAL
    return CLASS_PAPER_URGENT if urgent else CLASS_PAPER


def rank(real, urgent) -> int:
    """A.14: 3 real urgent, 2 real non-urgent, 1 paper urgent, 0 paper
    non-urgent; the claim takes -priority, queued_at, id."""
    return int(RANKS[triage_class(real, urgent)])


def _setting(key):
    from bot_program.orcs.models import OrcSetting
    return OrcSetting.get(key)


def triage_shares() -> dict:
    """A.13's shares and R's cap: constants.TRIAGE, each key overridden
    by OrcSetting "triage" (binding at once)."""
    out = dict(TRIAGE)
    over = _setting(TRIAGE_KEY)
    if isinstance(over, dict):
        for key, value in over.items():
            if key in out:
                try:
                    out[key] = max(0.0, float(value))
                except (TypeError, ValueError):
                    continue
    return out


def ceilings(cap, shares=None) -> dict:
    """A.13: each class's ceiling in a line of cap C, with the reserve
    R = min(reserve_cap, reserve_share x C) kept for real-money urgent
    wakes: real urgent C, real non-urgent C - R, paper urgent and paper
    non-urgent their shares of C, the tickets of the post-mortems and the
    council of war theirs. R <= 0.2 x C keeps C - R >= 0.8 x C, so they
    never invert; each is also held at or under the class above it, so an
    override cannot invert them either."""
    s = shares or triage_shares()
    c = max(0.0, float(cap or 0.0))
    reserve = min(float(s["reserve_cap"]), float(s["reserve_share"]) * c)
    real = max(0.0, c - reserve)
    paper_urgent = min(real, float(s["paper_urgent"]) * c)
    paper = min(paper_urgent, float(s["paper"]) * c)
    return {CLASS_REAL_URGENT: c, CLASS_REAL: real,
            CLASS_PAPER_URGENT: paper_urgent, CLASS_PAPER: paper,
            "tickets": min(paper, float(s["tickets"]) * c),
            "reserve": c - real}


# ── the Orc's day caps (A.12) ────────────────────────────────────────────

def wakes_cap(day_class, real) -> int:
    """The Orc's model wakes for the day, by its OWN money world and the
    trading day's class (weather.caps_for: real 12, 14 or 16; paper and
    demo 6), never read back from OrcDayBaseline.caps (that row holds what
    its first reader's world produced). OrcSetting "wakes_per_day"
    overrides them."""
    from bot_program.orcs import weather
    n = int(weather.caps_for(day_class, real)["wakes_per_day"])
    over = _setting(WAKES_PER_DAY_KEY)
    try:
        if isinstance(over, dict):
            if real and isinstance(over.get("real"), dict) and \
                    day_class in over["real"]:
                n = int(over["real"][day_class])
            elif not real and "paper" in over:
                n = int(over["paper"])
    except (TypeError, ValueError):
        pass
    return max(0, n)


def per_orc_daily_usd(real) -> float:
    """The Orc's dollars a day (OrcSetting "per_orc_daily_usd" overrides
    PER_ORC_DAILY_USD): real money $2.00, paper and demo $0.50."""
    key = "real" if real else "paper"
    over = _setting(PER_ORC_DAILY_KEY)
    try:
        if isinstance(over, dict) and key in over:
            return max(0.0, float(over[key]))
    except (TypeError, ValueError):
        pass
    return float(PER_ORC_DAILY_USD[key])


def routine_share() -> float:
    over = _setting(ROUTINE_SHARE_KEY)
    try:
        share = ROUTINE_SHARE if over is None else float(over)
    except (TypeError, ValueError):
        share = ROUTINE_SHARE
    return min(1.0, max(0.0, share))


def day_counters(orc, now) -> dict:
    """The Orc's four day counters and its unbilled HIGH for the UTC day of
    `now`: all zero when they belong to an earlier day (they reset lazily,
    A.12, §4 Q7)."""
    seen = orc.seen if isinstance(orc.seen, dict) else {}
    if seen.get(COUNTERS_DAY) != utc_day(now):
        return {"llm": 0, "routine": 0, "usd": 0.0, "routine_usd": 0.0,
                "unbilled": 0.0}
    return {"llm": int(orc.llm_wakes_today or 0),
            "routine": int(orc.routine_wakes_today or 0),
            "usd": float(orc.spend_today_usd or 0),
            "routine_usd": float(orc.routine_spend_today_usd or 0),
            "unbilled": float(seen.get("unbilled_usd") or 0.0)}


def cap_code(orc, *, real, urgent, routine, rung, day_class, now,
             inflight_high=0.0) -> str:
    """A.12: the first of the Orc's day caps this wake would pass, as its
    code; "" when none. The whole day first, then the routine sub-caps, as
    well as the whole day, never instead of it:

      day_cap      llm_wakes_today has reached the count cap; a real-money
                   urgent wake alone may pass it
      dollar_cap   spend_today + unbilled + HIGH of the Orc's call in
                   flight + HIGH(this rung) would pass its dollars: no wake
                   ever passes them (the line and the triage keep the
                   whole bound)
      routine_cap  a routine wake past routine_share of either cap

    The count is written at the claim, the dollars at the settle."""
    c = day_counters(orc, now)
    wakes = wakes_cap(day_class, real)
    usd = per_orc_daily_usd(real)
    this = high(rung)
    if c["llm"] >= wakes and not (real and urgent):
        return CODE_DAY_CAP
    if c["usd"] + c["unbilled"] + inflight_high + this > usd + 1e-9:
        return CODE_DOLLAR_CAP
    if routine:
        share = routine_share()
        if c["routine"] >= math.floor(share * wakes + 1e-9):
            return CODE_ROUTINE_CAP
        if c["routine_usd"] + c["unbilled"] + inflight_high + this > \
                share * usd + 1e-9:
            return CODE_ROUTINE_CAP
    return ""


def money_code(*, real, urgent, bound, purse, tier="balanced") -> str:
    """A.13 and A.18's floor rule, on the line as `purse` reads it (its
    cap, what it booked today, the OTHER calls' money in flight and held,
    the core's floor, the deep tiers' share): `triage` when the booked
    spend, the money in flight and held and this bound pass this class's
    ceiling; `deep_share` when, for a call on a deep or frontier `tier`,
    the same sum passes the deep tiers' share of the line (B.13), a
    real-money urgent wake exempt (D30); `inflight` when the money in
    flight and held and this bound pass ORC_LIVE_FLOOR_USD, the floor the
    core line holds back for the Orcs' unbooked money."""
    return class_money_code(triage_class(real, urgent), bound=bound,
                           purse=purse, tier=tier,
                           deep_exempt=bool(real and urgent))


def class_money_code(klass, *, bound, purse, tier="balanced",
                     deep_exempt=False) -> str:
    """money_code under one class's ceiling (a key of `ceilings`: a wake's
    triage class, or a ticket caller's, A.57). `deep_exempt`: a real-money
    urgent wake only (D30); a ticket never is."""
    ceiling = ceilings(purse["cap"])[klass]
    others = float(purse["inflight"])
    held = float(purse["spent"]) + others + float(bound)
    if held > ceiling + 1e-9:
        return CODE_TRIAGE
    if str(tier) in DEEP_TIERS and not deep_exempt and held > float(
            purse["deep_share"]) * float(purse["cap"] or 0) + 1e-9:
        return CODE_DEEP_SHARE
    if others + float(bound) > float(purse["floor"]) + 1e-9:
        return CODE_INFLIGHT
    return ""


def fable_money(reasons) -> str:
    """B.9's money clauses (O2b's frontier, 2026-11-06), for a real-money
    wake (the gate's first clause): Fable's pair priced at the dossier's
    size cap (mind.pair_price: r5's bound with its fallback and its
    twin's, about $3.57) under the wake's own class's ceiling, the deep
    share and the core's floor, with the money in flight and held
    (class_money_code, on the line as it stands). "" when the pair fits,
    else its code: triage, deep_share or inflight. Priced at the cap, the
    pair passes the $3.00 floor whatever the dossier, so in O2 it reads
    `inflight` (§4 Q12). The render pass reads it (wake.render_queued,
    only once the clauses before it hold); database reads only, no
    lock."""
    from bot_program.orcs import mind
    urgent = is_urgent(reasons)
    pair = mind.pair_price()
    return class_money_code(triage_class(True, urgent), bound=pair["weigh"],
                            purse=mind.purse(), tier=pair["tier"],
                            deep_exempt=urgent)


def spacing_code(orc, *, urgent, now) -> str:
    """A.15: a non-urgent wake needs MIN_WAKE_SPACING_MIN since the Orc's
    last CLAIMED model wake (last_wake_at, written at the claim)."""
    if urgent or orc.last_wake_at is None:
        return ""
    if now - orc.last_wake_at < timedelta(minutes=MIN_WAKE_SPACING_MIN):
        return CODE_SPACING
    return ""


# ── the breaker (A.56) ───────────────────────────────────────────────────

def breaker_state(now) -> dict:
    """OrcSetting "minds_breaker" while it is open at `now` ({until, why,
    at}); {} when it is closed."""
    value = _setting(MINDS_BREAKER_KEY)
    if not isinstance(value, dict):
        return {}
    until = _parse(value.get("until"))
    return dict(value) if until is not None and until > now else {}


def _trip(now) -> bool:
    """Open the breaker for BREAKER_PAUSE_MIN when BREAKER_FAILS wakes of
    any Orc ended `failed` within BREAKER_WINDOW_MIN. The caller holds the
    line lock. True when it opened now."""
    from bot_program.orcs.models import OrcSetting, OrcWake
    if breaker_state(now):
        return False
    n = OrcWake.objects.filter(
        status=WAKE_STATUS_FAILED,
        finished_at__gte=now - timedelta(minutes=BREAKER_WINDOW_MIN),
        finished_at__lte=now).count()
    if n < BREAKER_FAILS:
        return False
    OrcSetting.objects.update_or_create(key=MINDS_BREAKER_KEY, defaults={
        "value": {"until": (now + timedelta(minutes=BREAKER_PAUSE_MIN))
                  .isoformat(),
                  "why": f"{n} model calls failed within "
                         f"{BREAKER_WINDOW_MIN} minutes",
                  "at": now.isoformat()},
        "updated_by": "breaker"})
    logger.warning("[orcs] the minds' breaker opened: %s calls failed within "
                   "%s min; the claims pause %s min", n, BREAKER_WINDOW_MIN,
                   BREAKER_PAUSE_MIN)
    return True


# ── the line lock (N8) ───────────────────────────────────────────────────

def _bound_waits(conn) -> None:
    """SET LOCAL lock_timeout and statement_timeout for the caller's
    transaction, on PostgreSQL (SQLite has no row lock)."""
    if conn.vendor != "postgresql" or conn.get_autocommit():
        return
    with conn.cursor() as cur:
        cur.execute("SELECT set_config('lock_timeout', %s, true), "
                    "set_config('statement_timeout', %s, true)",
                    [f"{LINE_LOCK_TIMEOUT_MS}ms",
                     f"{ORC_STATEMENT_TIMEOUT_MS}ms"])


def line_lock():
    """The line lock: OrcSetting "minds_lock" locked for the caller's
    transaction, waited for 2 s at most (N8). The row is created with
    get_or_create, once more on an IntegrityError (two first callers in
    the same instant); the migration does not create it."""
    from bot_program.orcs.models import OrcSetting
    for attempt in (1, 2):
        try:
            with transaction.atomic():
                OrcSetting.objects.get_or_create(key=MINDS_LOCK_KEY,
                                                 defaults={"value": {}})
            break
        except IntegrityError:
            if attempt == 2:
                raise
    _bound_waits(transaction.get_connection())
    return OrcSetting.objects.select_for_update().get(key=MINDS_LOCK_KEY)


# ── the money held ───────────────────────────────────────────────────────

def _inflight_row():
    """OrcSetting "minds_inflight", locked: the caller holds the line
    lock already, so this row is never written by two settles at once."""
    from bot_program.orcs.models import OrcSetting
    row_, _ = OrcSetting.objects.get_or_create(key=MINDS_INFLIGHT_KEY,
                                               defaults={"value": {}})
    return OrcSetting.objects.select_for_update().get(pk=row_.pk)


def _pruned(value, now) -> dict:
    from django.utils.dateparse import parse_datetime
    out = {}
    for key, entry in (value or {}).items():
        if not isinstance(entry, dict):
            continue
        until = parse_datetime(str(entry.get("until") or "")) \
            if entry.get("until") else None
        if until is not None and until <= now:
            continue
        out[key] = entry
    return out


def hold(*, kind, usd, wake, rung, now, high_usd=0.0) -> str:
    """Hold `usd` until 00:00 UTC for one wake's call (A.25); the hold's
    key. The caller holds the line lock."""
    store = _inflight_row()
    value = _pruned(store.value if isinstance(store.value, dict) else {},
                    now)
    key = f"w{wake.pk}"
    value[key] = {"kind": kind, "usd": round(float(usd), 6),
                  "high": round(float(high_usd), 6), "orc": wake.orc_id,
                  "wake": wake.pk, "rung": str(rung or ""),
                  "at": now.isoformat(),
                  "until": next_midnight(now).isoformat()}
    store.value = value
    store.save(update_fields=["value"])
    return key


def drop_hold(wake, now) -> dict:
    """Drop the hold of `wake`'s call, if any (a late settle whose bill
    was booked, or whose call was never sent: _late_hold); the entry
    dropped, or {}."""
    store = _inflight_row()
    value = _pruned(store.value if isinstance(store.value, dict) else {},
                    now)
    gone = value.pop(f"w{wake.pk}", None) or {}
    store.value = value
    store.save(update_fields=["value"])
    return gone


# ── the tickets (A.57; O2a's arm, 2026-11-05) ────────────────────────────
# Every model call that is not a wake reserves through a ticket: from O2a,
# `orcs smoke --row`; from O2b the probes (bot_program/orcs/probes.py) and
# r5's blind twin, whose ticket only its r5 wake's claim writes, never
# reserve_ticket (_hold_twin); later Captains, the Emperor, the Skeptic,
# post-mortems, the council of war and questions. A ticket is
# an entry of OrcSetting "minds_inflight" {kind: "ticket", usd: its bound,
# at, wall_s, caller, rung, item, orc, ref}, counted in every in-flight sum
# of the line like a running wake's bound (mind_gateway.inflight_usd), and
# released only by its settle; past its wall time the watchdog makes it an
# orphan hold until 00:00 UTC (_tickets_wall_time). Its book, OrcSetting
# "minds_tickets" {day, counts {key: n}, items {item: {...}}}, keeps the
# day caps by key (a caller's name; a probe's `probe:<kind>:<user>`, O2b)
# and ONE BILLED ATTEMPT PER ITEM: a call with usage closes
# its item, billed or refused alike; one failure with no bill leaves one
# more try; a refusal for budget (no call made) may wait, at most until
# the next UTC day, when the item closes `expired`. So an item refused
# every time is billed once, never once a beat.

def _tickets_row():
    """OrcSetting "minds_tickets", locked: the caller holds the line lock
    already, so two reservations never write it at once."""
    from bot_program.orcs.models import OrcSetting
    row_, _ = OrcSetting.objects.get_or_create(key=MINDS_TICKETS_KEY,
                                               defaults={"value": {}})
    return OrcSetting.objects.select_for_update().get(pk=row_.pk)


def ticket_book(value, now) -> dict:
    """The tickets' book for the UTC day of `now` (pure): the counts of
    an earlier day dropped, an item that waited for the budget past its
    day closed `expired`, items older than TICKET_ITEMS_KEEP_DAYS gone."""
    book = value if isinstance(value, dict) else {}
    today = utc_day(now)
    keep_from = (_utc(now).date()
                 - timedelta(days=TICKET_ITEMS_KEEP_DAYS)).isoformat()
    items = {}
    for key, item in (book.get("items") or {}).items():
        if not isinstance(item, dict) or str(item.get("day") or "") \
                < keep_from:
            continue
        item = dict(item)
        if item.get("state") == ITEM_WAITING and item.get("day") != today:
            item["state"], item["code"] = ITEM_EXPIRED, CODE_EXPIRED
        items[str(key)] = item
    counts = dict(book.get("counts") or {}) if book.get("day") == today \
        else {}
    return {"day": today, "counts": counts, "items": items}


def _item_code(item) -> str:
    """Why an item may not send again, as a code; "" when it may."""
    if not item:
        return ""
    state = item.get("state")
    if state == ITEM_EXPIRED:
        return CODE_EXPIRED
    if state in ITEM_CLOSED:
        return CODE_ITEM_CLOSED
    if state == ITEM_RESERVED:
        return CODE_ITEM_BUSY
    return ""


def probes_per_day() -> dict:
    """B.11 (O2b's probes, 2026-11-06): a user's probes a UTC day by kind,
    PROBES_PER_DAY (boundary 6, h0 40), each kind overridden by OrcSetting
    "probes_per_day", binding at once (0 sends none of that kind)."""
    out = dict(PROBES_PER_DAY)
    over = _setting(PROBES_PER_DAY_KEY)
    if isinstance(over, dict):
        for kind, value in over.items():
            if kind in out:
                try:
                    out[kind] = max(0, int(value))
                except (TypeError, ValueError):
                    continue
    return out


def probes_usd_per_day(cap) -> float:
    """B.11: the probes' own allowance of the Orcs line: OrcSetting
    "probes_usd_per_day", an explicit value in dollars; else
    PROBES_USD_SHARE (15%) of the line's cap `cap`, read at once ($1.50 at
    $10). An unreadable value is the default."""
    over = _setting(PROBES_USD_KEY)
    if over is not None and not isinstance(over, (bool, dict, list)):
        try:
            return max(0.0, float(over))
        except (TypeError, ValueError):
            pass
    return PROBES_USD_SHARE * max(0.0, float(cap or 0.0))


def ticket_cap(caller, request) -> tuple:
    """(the key a ticket's day is counted under in the tickets' book, its
    cap a UTC day, or None for none). A probe's (O2b's probes, 2026-11-06,
    B.11) is `probe:<kind>:<user>`, its kind's cap a user a day
    (probes_per_day); ValueError, before anything is held, for a probe of
    no probe kind or no user. Any other caller's is its name, with
    TICKET_DAY_CAP's cap (0 counts none)."""
    req = request if isinstance(request, dict) else {}
    if caller == PROBE_CALLER:
        kind = str(req.get("kind") or "")
        if kind not in PROBE_KINDS:
            raise ValueError(f"a probe's kind is one of {PROBE_KINDS}, not "
                             f"{kind!r}")
        try:
            user = int(req.get("user"))
        except (TypeError, ValueError):
            raise ValueError("a probe names its user: its cap is a user's "
                             "a day") from None
        return f"{caller}:{kind}:{user}", int(probes_per_day()[kind])
    cap = int(TICKET_DAY_CAP.get(caller) or 0)
    return str(caller), (cap or None)


def probe_allowance_code(*, bound, booked, inflight, allowance) -> str:
    """B.11: `probe_allowance` when the probes' booked spend today, their
    tickets and holds in flight and this bound pass the probes' own
    allowance; "" otherwise. Pure."""
    if float(booked) + float(inflight) + float(bound) > float(allowance) \
            + 1e-9:
        return CODE_PROBE_ALLOWANCE
    return ""


def _caller_inflight(caller, now) -> float:
    """The money one caller's tickets hold in flight, and the holds they
    left (a call with no bill, an orphan, a ledger gap), in OrcSetting
    "minds_inflight", locked: the caller holds the line lock."""
    store = _inflight_row()
    value = _pruned(store.value if isinstance(store.value, dict) else {},
                    now)
    total = 0.0
    for entry in value.values():
        if isinstance(entry, dict) and entry.get("caller") == caller:
            try:
                total += float(entry.get("usd") or 0)
            except (TypeError, ValueError):
                continue
    return total


def reserve_ticket(caller, request, *, now=None) -> dict:
    """A.57: one ticket for a call of `caller` that is not a wake. Its
    request comes first: `request` {rung, tokens (the estimate of the
    exact text it sends, x the family factor: mind.ticket_tokens), item,
    orc, ref; a probe's kind, user and would_rung too}. ValueError, before
    anything is held, for a caller that is no ticket row of §1.0.9
    (mind_gateway.CALLER_RUNGS, TICKET_MAX_TOKENS, TICKET_CLASS), a rung
    outside its list (a probe's r2 only as B.5's map of r3 or r4), or a
    probe of no kind or no user. Then, the first that fails answering by
    code with nothing held: the request above TICKET_MAX_TOKENS
    (`over_budget`, before any lock); under the line lock, its item (one
    billed attempt), the four gates and the caller's own switch (the
    probes': `probes_off`), its day cap by its key (ticket_cap), its
    class's ceiling, the deep share and the core's floor (A.13, B.13,
    A.18), a probe's own allowance (`probe_allowance`, B.11), then the
    line for the whole bound plus the money in flight and held (A.20).
    Every check a database read under the line lock (N8). A pass holds
    the bound (no fallback, B.14) and counts the day under its key.
    Returns {ok, code, key, bound, model, tier}."""
    from bot_program.orcs import mind, switches
    now = now or timezone.now()
    req = dict(request or {})
    rung = str(req.get("rung") or "")
    mind.ticket_caller(caller, rung,
                       would=str(req.get("would_rung") or "") or None)
    cap, klass = TICKET_MAX_TOKENS.get(caller), TICKET_CLASS.get(caller)
    if cap is None or klass is None:
        raise ValueError(f"the {caller} caller has no ticket row "
                         f"(TICKET_MAX_TOKENS, TICKET_CLASS)")
    cap_key, day_cap = ticket_cap(caller, req)
    tokens = max(0, int(req.get("tokens") or 0))
    # the bound: the catalog's arithmetic, read before the lock
    price = mind.ticket_price(rung, tokens)
    out = {"ok": False, "code": "", "key": "", "bound": price["bound"],
           "model": price["model"], "tier": price["tier"]}
    if tokens > int(cap):
        out["code"] = CODE_OVER_BUDGET
        return out
    item = str(req.get("item") or "")[:160]
    with transaction.atomic():
        line_lock()
        books = _tickets_row()
        book = ticket_book(books.value, now)
        prior = book["items"].get(item) if item else None
        code = (_item_code(prior) or switches.gate_code()
                or switches.caller_code(caller))
        if not code and day_cap is not None and int(
                book["counts"].get(cap_key) or 0) >= day_cap:
            code = CODE_DAY_CAP
        if not code:
            # B.13 (O2b, 2026-11-06): the deep share too, on the ticket's
            # own tier; a ticket is never exempt
            purse = mind.purse()
            code = class_money_code(klass, bound=price["bound"],
                                    purse=purse, tier=price["tier"])
            if not code and caller == PROBE_CALLER:
                # B.11 (O2b's probes, 2026-11-06): the probes' own
                # allowance, on their own booked spend and money in flight
                code = probe_allowance_code(
                    bound=price["bound"], booked=mind.probes_spent(),
                    inflight=_caller_inflight(caller, now),
                    allowance=probes_usd_per_day(purse["cap"]))
        if not code:
            _ok, code, _why = mind.ask_line(rung_name=rung,
                                            bound_usd=price["bound"])
        if code:
            if item and code not in (CODE_ITEM_CLOSED, CODE_ITEM_BUSY,
                                     CODE_EXPIRED):
                # no call made: the item may wait, at most to the next UTC
                # day (ticket_book closes it then)
                book["items"][item] = {**(prior or {}), "caller": caller,
                                       "day": book["day"],
                                       "state": ITEM_WAITING, "code": code,
                                       "at": now.isoformat()}
            books.value = book
            books.save(update_fields=["value"])
            out["code"] = code
            return out
        import uuid
        key = f"t{uuid.uuid4().hex[:16]}"
        store = _inflight_row()
        value = _pruned(store.value if isinstance(store.value, dict) else {},
                        now)
        value[key] = {"kind": HOLD_TICKET,
                      "usd": round(float(price["bound"]), 6),
                      "caller": str(caller), "rung": rung, "item": item,
                      "orc": req.get("orc"),
                      "ref": str(req.get("ref") or "")[:120],
                      "at": now.isoformat(), "wall_s": int(price["wall_s"])}
        store.value = value
        store.save(update_fields=["value"])
        book["counts"][cap_key] = int(book["counts"].get(cap_key) or 0) + 1
        if item:
            book["items"][item] = {**(prior or {}), "caller": caller,
                                   "day": book["day"],
                                   "state": ITEM_RESERVED, "code": "",
                                   "at": now.isoformat(), "ticket": key}
        books.value = book
        books.save(update_fields=["value"])
    out.update(ok=True, key=key)
    return out


def _item_after(item, outcome) -> dict:
    """An item after its call (pure): billed (closed) by a call with
    usage, its one retry used by a failure with no bill (closed on the
    second), closed by a request refused before the send, waiting after a
    refusal with no call made."""
    item = dict(item or {})
    usage = outcome.get("usage") if isinstance(outcome.get("usage"),
                                               dict) else None
    kind = outcome.get("kind")
    if outcome.get("sent"):
        item["sends"] = int(item.get("sends") or 0) + 1
    if usage is not None:
        item["state"], item["code"] = ITEM_BILLED, ""
    elif kind == REPLY_UNBILLED:
        item["state"] = (ITEM_FAILED if int(item.get("sends") or 0)
                         > TICKET_RETRIES else ITEM_UNBILLED)
        item["code"] = str(outcome.get("code") or "")
    elif kind == REPLY_UNSENT:
        item["state"], item["code"] = ITEM_UNSENT, str(
            outcome.get("code") or "")
    else:
        item["state"], item["code"] = ITEM_WAITING, str(
            outcome.get("code") or "")
    item.pop("ticket", None)
    return item


def settle_ticket(key, outcome, *, now=None) -> dict:
    """A.57, a ticket's settle (A.24's release, the ledger check included),
    in one short transaction under the line lock, database writes only.
    `outcome` is the gateway's reply with "ledger": whether the provider's
    own ledger row of the call exists, looked up before the lock through
    the gateway (never inside it). A call with usage releases the ticket
    once its ledger row is found, else holds the booked cost as
    `ledger_gap` until 00:00 UTC; a call with no bill keeps its bound held
    as `unbilled` until 00:00 UTC (it may have been billed); nothing sent
    releases it. A ticket the watchdog already made an orphan (its wall
    time) settles late: a bill drops the hold once its row is found, no
    bill leaves it held until 00:00 UTC. Then its item (_item_after).
    Returns {held, released, late, item}."""
    now = now or timezone.now()
    usage = outcome.get("usage") if isinstance(outcome.get("usage"),
                                               dict) else None
    kind = outcome.get("kind")
    out = {"held": "", "released": False, "late": False, "item": ""}
    with transaction.atomic():
        line_lock()
        store = _inflight_row()
        value = _pruned(store.value if isinstance(store.value, dict) else {},
                        now)
        entry = value.get(key) if isinstance(value.get(key), dict) else None
        if entry is not None and entry.get("kind") in (HOLD_TICKET,
                                                       HOLD_ORPHAN):
            out["late"] = entry.get("kind") == HOLD_ORPHAN
            until = next_midnight(now).isoformat()
            if usage is not None and outcome.get("ledger"):
                value.pop(key)
                out["released"] = True
            elif usage is not None:
                value[key] = {**entry, "kind": HOLD_LEDGER_GAP,
                              "usd": round(float(usage.get("cost_usd")
                                                 or 0), 6), "until": until}
            elif kind == REPLY_UNBILLED or out["late"]:
                value[key] = {**entry, "kind": (HOLD_ORPHAN if out["late"]
                                                else HOLD_UNBILLED),
                              "until": until}
            else:
                value.pop(key)
                out["released"] = True
            if key in value:
                out["held"] = value[key]["kind"]
            store.value = value
            store.save(update_fields=["value"])
        item = str((entry or {}).get("item") or "")
        if item:
            books = _tickets_row()
            book = ticket_book(books.value, now)
            book["items"][item] = {**_item_after(book["items"].get(item),
                                                 outcome),
                                   "day": book["day"], "at": now.isoformat()}
            out["item"] = book["items"][item]["state"]
            books.value = book
            books.save(update_fields=["value"])
    return out


def store_pair(fields):
    """B.12 (O2b's probes, 2026-11-06): one probe pair (OrcTierGrade, its
    `fields` built by probes.py with no lock held), its block the count of
    the earlier pairs of its (boundary, kind, world) over SEAT_WINDOW,
    counted and written in one short transaction under the line lock, so
    two workers never share an index: database work only (N8). None, and
    nothing written, when the pair is stored already (one per wake and
    kind)."""
    from bot_program.orcs.models import OrcTierGrade
    try:
        with transaction.atomic():
            line_lock()
            n = OrcTierGrade.objects.filter(
                kind=fields["kind"], boundary=fields.get("boundary"),
                world=fields["world"]).count()
            return OrcTierGrade.objects.create(block=n // SEAT_WINDOW,
                                               **fields)
    except IntegrityError as e:
        logger.warning("[orcs] a probe pair of wake %s is stored already: "
                       "%s", getattr(fields.get("wake"), "pk", "?"), e)
        return None


def _tickets_wall_time(now) -> int:
    """A.57: a ticket past its wall time becomes an `orphan` hold until
    00:00 UTC: its call may still stream, or be orphaned by a worker's
    restart, and may yet bill; nothing is dropped earlier. Its late
    settle books it (settle_ticket)."""
    n = 0
    with transaction.atomic():
        line_lock()
        store = _inflight_row()
        value = _pruned(store.value if isinstance(store.value, dict) else {},
                        now)
        for key, entry in list(value.items()):
            if entry.get("kind") != HOLD_TICKET:
                continue
            at = _parse(entry.get("at"))
            if at is None or now - at <= timedelta(
                    seconds=float(entry.get("wall_s") or 0)):
                continue
            value[key] = {**entry, "kind": HOLD_ORPHAN,
                          "until": next_midnight(now).isoformat()}
            n += 1
        if n:
            store.value = value
            store.save(update_fields=["value"])
    if n:
        logger.warning("[orcs] %s ticket(s) ran past their wall time: their "
                       "bounds stay held until 00:00 UTC", n)
    return n


# ── the merge (A.7 step 1) ───────────────────────────────────────────────

def _pending_key(orc_id) -> str:
    return f"orc{orc_id}:pending"


def absorb(wake, *, now=None) -> int:
    """A.7 step 1 (P15): in its own transaction under the Orc's lock,
    BEFORE `wake` is rendered, the Orc's pending wake is merged into it:
    `wake` takes the union of both wakes' reasons, by key, each reason
    keeping its own `urgent`, and the older first send as
    components["queued_at_inherited"] (the earliest, when it inherits
    twice); its kind is the union's. The older wake becomes `merged`, with
    components["merged_into"] and finished_at. So the survivor's dossier
    lists every reason, and its urgency, its rank and its F6 test are the
    union's. Returns how many wakes it merged."""
    from bot_program.orcs import journal
    from bot_program.orcs.models import OrcWake
    from bot_program.orcs.wake import _kind_of
    now = now or timezone.now()
    with transaction.atomic():
        journal.orc_lock(wake.orc_id)
        w = OrcWake.objects.select_for_update().get(pk=wake.pk)
        older = list(OrcWake.objects.select_for_update()
                     .filter(orc_id=w.orc_id, status=WAKE_STATUS_PENDING)
                     .exclude(pk=w.pk).order_by("id"))
        if not older:
            return 0
        reasons = [r for r in w.reasons or [] if isinstance(r, dict)]
        keys = {r.get("key") for r in reasons}
        comps = dict(w.components or {})
        first = _parse(comps.get("queued_at_inherited"))
        for o in older:
            for r in o.reasons or []:
                if isinstance(r, dict) and r.get("key") not in keys:
                    reasons.append(r)
                    keys.add(r.get("key"))
            sent = o.queued_at or _parse((o.components or {}).get(
                "queued_at_inherited"))
            if sent is not None and (first is None or sent < first):
                first = sent
            o.status = WAKE_STATUS_MERGED
            o.components = {**(o.components or {}), "merged_into": w.pk}
            o.finished_at = now
            o.save(update_fields=["status", "components", "finished_at"])
        if first is not None:
            comps["queued_at_inherited"] = first.isoformat()
        w.reasons, w.components = reasons, comps
        w.kind = _kind_of(reasons)
        w.save(update_fields=["reasons", "components", "kind"])
    wake.reasons, wake.components, wake.kind = w.reasons, w.components, w.kind
    return len(older)


# ── admission (A.11) ─────────────────────────────────────────────────────

def _facts(w, orc) -> dict:
    """The wake's world, urgency, routine-ness and rank (A.12, A.14), read
    on the wake's reasons as they stand (a survivor's after a merge)."""
    real = is_real(orc)
    urgent = is_urgent(w.reasons)
    return {"real": real, "urgent": urgent, "routine": is_routine(w.reasons),
            "rank": rank(real, urgent)}


def _running_high(orc_id, *, exclude=None) -> float:
    """Σ HIGH of the Orc's calls in flight (A.12): one at most (A.18)."""
    from bot_program.orcs.models import OrcWake
    qs = OrcWake.objects.filter(orc_id=orc_id, status=WAKE_STATUS_RUNNING)
    if exclude is not None:
        qs = qs.exclude(pk=exclude)
    return sum(high((c or {}).get("rung") or O2A_RUNG)
               for c in qs.values_list("components", flat=True))


def _check(w, orc, f, *, now, rung, bound, purse, inflight_high,
           tier="balanced") -> str:
    """A.11 steps 2-8, the first that fails as its code; "" when all pass:
    the four gates (read anew); the Orc dead, the row not open; the
    dossier over its size cap; the breaker; the day caps; the triage, the
    deep share on a deep or frontier `tier` (B.13) and the core's floor;
    the spacing. Database reads only."""
    from bot_program.orcs import switches
    code = switches.gate_code()
    if code:
        return code
    if orc.state == STATE_DEAD:
        return CODE_DEAD
    if _row_status(orc) not in _open_statuses():
        return CODE_ROW_CLOSED
    if (w.components or {}).get("over_budget"):
        return CODE_OVER_BUDGET
    if breaker_state(now):
        return CODE_BREAKER
    code = cap_code(orc, real=f["real"], urgent=f["urgent"],
                    routine=f["routine"], rung=rung, day_class=w.day_class,
                    now=now, inflight_high=inflight_high)
    if code:
        return code
    code = money_code(real=f["real"], urgent=f["urgent"], bound=bound,
                      purse=purse, tier=tier)
    if code:
        return code
    return spacing_code(orc, urgent=f["urgent"], now=now)


def _open_statuses():
    from bot_program.orcs.wake import OPEN_STATUSES
    return OPEN_STATUSES


def _code_body(code, *, bound, purse, rung="") -> dict:
    """What a code answer's journal body keeps: the line's numbers for a
    money code (dollars in the body only, never in the headline, A.5),
    and the rung the call would have answered on (O2b, 2026-11-06)."""
    if code in BUDGET_CODES:
        return {"bound_usd": round(float(bound), 6), "rung": str(rung),
                "line": {k: round(float(purse.get(k) or 0), 6)
                         for k in ("cap", "spent", "inflight", "floor")}}
    return {}


def _by_code(locked, w, code, *, now, body=None) -> None:
    """A code answer (A.4, A.5): the wake `skipped` with its code, never a
    refusal and never silence; while the minds switch itself is on, a
    `budget` entry in fixed words, off the card, the card's intellect
    saying how this wake was answered when it is this wake's (A.62). The
    caller holds the Orc's lock."""
    from bot_program.orcs import journal, notes, switches
    w.status, w.skipped_reason = WAKE_STATUS_SKIPPED, code
    w.est_usd = Decimal(0)
    w.save(update_fields=["status", "skipped_reason", "est_usd"])
    if switches.minds_switch_on():
        it = notes.intellect_after(locked.card, w.pk,
                                   status_t=notes.wake_status_t(
                                       WAKE_STATUS_SKIPPED, code))
        journal.append(locked, "budget", f"Answered by code: "
                       f"{WAKE_CODE_WORDS.get(code, code)}.",
                       body={"wake": w.pk, "code": code, **(body or {})},
                       wake=w, card=False, at=now,
                       card_extra={"intellect": it} if it else None)


def _to_pending(w, f, *, rung, price, now) -> None:
    """A.11 step 9: `pending`, one per Orc at the database (the key
    "orc<pk>:pending", the constraint orcwake_one_pending_per_key), the
    tick's own key kept, the first send set once (inherited from a merged
    wake, or now) and never moved, the priority its rank, the rung (the
    answering rung, B.2b), its bound and whether it names the fallback
    (B.14); an r5 wake's whole pair beside it (O2b's frontier,
    2026-11-06)."""
    comps = dict(w.components or {})
    if w.dedupe_key != _pending_key(w.orc_id):
        comps.setdefault("record_key", w.dedupe_key)
    comps.update({"rung": rung, "bound": round(float(price["bound"]), 6),
                  "fallback": bool(price.get("fallback")),
                  "real": bool(f["real"]), "urgent": bool(f["urgent"])})
    if price.get("twin"):
        comps["pair"] = round(float(price["weigh"]), 6)
    w.components = comps
    w.dedupe_key = _pending_key(w.orc_id)
    if w.queued_at is None:
        w.queued_at = _parse(comps.get("queued_at_inherited")) or now
    w.priority = float(f["rank"])
    w.status, w.skipped_reason = WAKE_STATUS_PENDING, ""
    w.est_usd = Decimal(0)
    w.save(update_fields=["components", "dedupe_key", "queued_at",
                          "priority", "status", "skipped_reason", "est_usd"])


def admit(wake, rendered=None, *, now=None) -> dict:
    """A.11, after the render (`rendered`: the render's own result, whose
    over_budget it reads; else the wake's components): a quiet wake stays
    quiet; otherwise the first check that fails answers it by code, or it
    becomes `pending`. The checks read first; then one short transaction
    under the Orc's lock writes the status alone (A.7 step 3). The Orc's
    older pending wake was merged into this one before its render
    (absorb), so the database's one-pending rule holds. Returns {status,
    code, priority}."""
    from bot_program.orcs import journal, mind, switches
    from bot_program.orcs.models import OrcWake
    now = now or timezone.now()
    w = (OrcWake.objects.select_related("orc", "orc__seat",
                                        "orc__root_trade").get(pk=wake.pk))
    if w.status == WAKE_STATUS_QUIET:
        return {"status": WAKE_STATUS_QUIET, "code": CODE_QUIET,
                "priority": w.priority}
    comps = w.components if isinstance(w.components, dict) else {}
    if w.status not in ADMISSIBLE or comps.get("render") != "done":
        return {"status": w.status, "code": w.skipped_reason,
                "priority": w.priority}
    if isinstance(rendered, dict) and "over_budget" in rendered:
        w.components = {**comps, "over_budget": bool(
            rendered["over_budget"])}
    orc = w.orc
    f = _facts(w, orc)
    rung = O2A_RUNG
    gate = switches.gate_code()
    if gate:
        # a gate OFF answers first (A.11 step 2): the line's money is not
        # read for a wake no model will see (as the minds ship, every one)
        price, purse, code = {"bound": 0.0, "weigh": 0.0}, {}, gate
    else:
        # B.2b (O2b, 2026-11-06): the answering rung, behind the router's
        # switch: r0 while it is OFF, as O2a
        rung = mind.admitted_rung(w, router_on=switches.router_on())
        price = mind.price(w, rung, real=f["real"])
        purse = mind.purse()
        # `weigh`: the bound, or an r5 wake's whole pair (O2b's frontier)
        code = _check(w, orc, f, now=now, rung=rung, bound=price["weigh"],
                      purse=purse, inflight_high=_running_high(
                          orc.pk, exclude=w.pk), tier=price["tier"])
    with transaction.atomic():
        locked = journal.orc_lock(orc.pk)
        fresh = OrcWake.objects.select_for_update().get(pk=w.pk)
        if fresh.status not in ADMISSIBLE:
            return {"status": fresh.status, "code": fresh.skipped_reason,
                    "priority": fresh.priority}
        fresh.components = w.components
        if code:
            fresh.save(update_fields=["components"])
            _by_code(locked, fresh, code, now=now,
                     body=_code_body(code, bound=price["weigh"], purse=purse,
                                     rung=rung))
        else:
            _to_pending(fresh, f, rung=rung, price=price, now=now)
    wake.status, wake.skipped_reason = fresh.status, fresh.skipped_reason
    return {"status": fresh.status, "code": code, "priority": fresh.priority}


# ── the claim (A.16, A.18) ───────────────────────────────────────────────

def _cold_running(model) -> bool:
    """A.16: the first call on a cold model is running."""
    from bot_program.orcs.models import OrcWake
    return any(isinstance(c, dict) and c.get("cold")
               for c in OrcWake.objects.filter(
                   status=WAKE_STATUS_RUNNING, model=model)
               .values_list("components", flat=True))


def _hold_twin(w, price, *, now) -> dict:
    """B.10 (O2b's frontier, 2026-11-06): the blind twin's ticket beside its
    r5 wake, written in the claim's own transaction under the line lock:
    an entry of OrcSetting "minds_inflight" {kind ticket, usd: its bound,
    caller twin, rung, item twin:<wake>, orc, pair: the wake, ref, at,
    wall_s: the pair's, both sent one after the other}, counted in every
    in-flight sum of the line, r5's own ask included (its `pair` is never
    the `wake` a call excludes); released by its settle (mind.think), an
    orphan past its wall time. Returns {key, rung, bound, ref}."""
    import uuid

    from bot_program.orcs import mind
    twin = price["twin"]
    key = f"t{uuid.uuid4().hex[:16]}"
    ref = mind.source_ref(w, twin["rung"], caller=TWIN_CALLER)
    usd = round(float(twin["bound"]), 6)
    store = _inflight_row()
    value = _pruned(store.value if isinstance(store.value, dict) else {},
                    now)
    value[key] = {"kind": HOLD_TICKET, "usd": usd, "caller": TWIN_CALLER,
                  "rung": str(twin["rung"]),
                  "item": f"{TWIN_CALLER}:{w.pk}", "orc": w.orc_id,
                  "pair": w.pk, "ref": ref[:120], "at": now.isoformat(),
                  "wall_s": int(price.get("wall_s") or 0)}
    store.value = value
    store.save(update_fields=["value"])
    return {"key": key, "rung": str(twin["rung"]), "bound": usd, "ref": ref}


def _take(locked, w, f, price, *, rung, now, frontier="") -> None:
    """A.18 on a pass: `running`, started_at, est_usd = the bound, the
    rung's model; whether its model was cold (A.16); the Orc's
    last_wake_at and its count counters (reset first on a new UTC day).
    An r5 wake's twin's ticket beside it (_hold_twin; O2b's frontier,
    2026-11-06), and `frontier`, the clause of Fable's gate that no longer
    held at the claim when r4 answers a wake routed r5. The caller holds
    the line lock and the Orc's lock."""
    from bot_program.orcs import journal
    from bot_program.orcs.models import OrcWake
    model = str(price["model"] or "")[:50]
    cold = not OrcWake.objects.filter(
        model=model, started_at__gte=now - timedelta(minutes=COLD_MODEL_MIN)
    ).exclude(pk=w.pk).exists()
    # a wake admitted with its pair and answered on r4 keeps no pair
    kept = {k: v for k, v in (w.components or {}).items()
            if k not in ("twin", "pair")}
    extra = {}
    if rung == FRONTIER_RUNG and price.get("twin"):
        extra = {"twin": _hold_twin(w, price, now=now),
                 "pair": round(float(price["weigh"]), 6)}
    elif frontier:
        extra = {"frontier": str(frontier)}
    w.status = WAKE_STATUS_RUNNING
    w.started_at = now
    w.est_usd = Decimal(str(round(float(price["bound"]), 6)))
    w.model = model
    w.components = {**kept, "rung": rung,
                    "bound": round(float(price["bound"]), 6),
                    "fallback": bool(price.get("fallback")),
                    "real": bool(f["real"]), "urgent": bool(f["urgent"]),
                    "cold": cold, **extra}
    w.save(update_fields=["status", "started_at", "est_usd", "model",
                          "components"])
    c = day_counters(locked, now)
    fields = {"last_wake_at": now, "llm_wakes_today": c["llm"] + 1,
              "routine_wakes_today": c["routine"] + (1 if f["routine"]
                                                     else 0)}
    keys = {COUNTERS_DAY: utc_day(now)}
    seen = locked.seen if isinstance(locked.seen, dict) else {}
    if seen.get(COUNTERS_DAY) != utc_day(now):
        fields.update(spend_today_usd=Decimal(0),
                      routine_spend_today_usd=Decimal(0))
        keys["unbilled_usd"] = 0.0
    journal.remember(locked, fields=fields, **keys)


def _past_stale(queued_at, now) -> bool:
    """A.55: a pending wake whose first send is older than STALE_MIN."""
    return queued_at is not None and queued_at < now - timedelta(
        minutes=STALE_MIN)


def _claim_one(wid, orc_id, *, now, paused=False) -> tuple:
    """One candidate, in its own short transaction: ("claimed", wake),
    ("code", code), or ("wait", why) for a candidate that stays pending
    (its Orc's row held by another, a call of its Orc in flight, a cold
    model's first call running, or its first send past the stale clock
    while the watchdog runs). A wake past the stale clock is never sent on
    its old dossier (A.55; 2026-11-05, completing O2a): with a gate OFF it
    is answered by that gate's code, after a pause of the watchdog
    (`paused`, as after `orcs` or the platform master came back ON) by
    `paused`, as the watchdog's next pass would; else the watchdog closes
    it (backlog behind a busy worker, worker_silent)."""
    from bot_program.orcs import journal, mind, router, switches
    from bot_program.orcs.models import OrcWake
    w0 = OrcWake.objects.get(pk=wid)
    # B.2b (O2b, 2026-11-06), read before the locks: the answering rung,
    # the router's switch read again (frictionless off: r0 once it is OFF,
    # the wake re-priced); the bound and the model, the catalog's
    # arithmetic, for either money world (the locks read the world)
    rung = mind.claim_rung(w0, router_on=switches.router_on())
    frontier, alt = "", None
    if rung == FRONTIER_RUNG:
        # B.9, B.10 (O2b's frontier, 2026-11-06): r4 as B.5 maps it, priced
        # too, reads the stored Fable dossier should a clause of the gate
        # no longer hold; the frontier's switch read again (frictionless
        # off), real money and the quota under the locks below
        alt_rung = mind.answering_rung(TWIN_RUNG)
        alt = (alt_rung, {real: mind.price(w0, alt_rung, real=real)
                          for real in (False, True)})
        if not switches.frontier_on():
            frontier = router.FRONTIER_OFF
            rung = alt_rung
    prices = (alt[1] if frontier else
              {real: mind.price(w0, rung, real=real) for real in (False,
                                                                  True)})
    with transaction.atomic():
        line_lock()
        locked = journal.orc_lock(orc_id, skip_locked=True)
        if locked is None:
            return "wait", "the Orc's row is held"
        w = OrcWake.objects.select_for_update().get(pk=wid)
        if w.status != WAKE_STATUS_PENDING:
            return "gone", w.status
        if OrcWake.objects.filter(orc_id=orc_id,
                                  status=WAKE_STATUS_RUNNING).exists():
            return "wait", "a call of this Orc is in flight"
        f = _facts(w, locked)
        if rung == FRONTIER_RUNG:
            # B.9 under the line lock, which every r5 claim takes: real
            # money, and a frontier quota left, the r5 calls in flight
            # counted; else r4 as B.5 maps it answers
            frontier = (router.NOT_REAL if not f["real"] else
                        router.NO_QUOTA if mind.frontier_left(
                            locked.user_id) <= 0 else "")
            if frontier:
                rung, prices = alt
        price = prices[bool(f["real"])]
        purse = mind.purse()
        if _past_stale(w.queued_at, now):
            code = switches.gate_code() or (CODE_PAUSED if paused else "")
            if not code:
                return "wait", "past the stale clock: the watchdog closes it"
        else:
            # `weigh`: the bound, or an r5 wake's whole pair, weighed once
            code = _check(w, locked, f, now=now, rung=rung,
                          bound=price["weigh"], purse=purse,
                          inflight_high=0.0, tier=price["tier"])
        if not code:
            _ok, code, _why = mind.ask_line(
                rung_name=rung, bound_usd=price["weigh"],
                real_urgent=f["real"] and f["urgent"])
        if code:
            _by_code(locked, w, code, now=now,
                     body=_code_body(code, bound=price["weigh"],
                                     purse=purse, rung=rung))
            return "code", code
        if not f["urgent"] and _cold_running(price["model"]):
            return "wait", "the first call on a cold model is running"
        _take(locked, w, f, price, rung=rung, now=now, frontier=frontier)
    return "claimed", w


def claim(*, now=None, limit=CLAIM_SCAN) -> dict:
    """A.18: claim the best pending wake whose Orc has no call in flight,
    one short transaction per candidate examined (N8). A candidate a check
    refuses is answered by code and committed, and the claim tries the
    next. A wake whose first send is past the stale clock is never sent
    on its old dossier (A.55; 2026-11-05, completing O2a): after a pause
    of the watchdog (`orcs` or the platform master came back ON) it is
    answered `paused` here, else left pending for the watchdog's next
    pass, without a lock. Returns {wake (the claimed wake, or None),
    by_code, waiting}."""
    from bot_program.orcs.models import OrcWake
    now = now or timezone.now()
    out = {"wake": None, "by_code": 0, "waiting": 0}
    busy = set(OrcWake.objects.filter(status=WAKE_STATUS_RUNNING)
               .values_list("orc_id", flat=True))
    candidates = list(OrcWake.objects.filter(status=WAKE_STATUS_PENDING)
                      .order_by("-priority", "queued_at", "id")
                      .values_list("id", "orc_id", "queued_at")[:int(limit)])
    # A.55: the watchdog's pause, read once per claim (a wake past the
    # stale clock is never sent; _claim_one)
    paused = _paused(_watch_last(), now)
    for wid, orc_id, queued_at in candidates:
        if orc_id in busy:
            # one call in flight per Orc: it stays pending; the running
            # wake's settle sends it back to the render (A.24)
            out["waiting"] += 1
            continue
        if not paused and _past_stale(queued_at, now):
            # never sent on its old dossier: the watchdog's next pass
            # answers it by code (no lock taken here for it)
            out["waiting"] += 1
            continue
        verdict, what = _claim_one(wid, orc_id, now=now, paused=paused)
        if verdict == "claimed":
            out["wake"] = what
            return out
        if verdict == "code":
            out["by_code"] += 1
        elif verdict == "wait":
            out["waiting"] += 1
    return out


def run(*, clock=None, now_fn=None, budget_s=THINK_RUN_S) -> dict:
    """A.19, one orc_think run: claim one wake, read it (mind.think, no
    lock held), and again, until nothing can be claimed or `budget_s` has
    passed since it started. Each claim reads the four gates anew, the
    platform master included (A.2). Returns {thought, by_code, waiting}."""
    from bot_program.orcs import mind
    clock = clock or time.monotonic
    now_fn = now_fn or timezone.now
    started = clock()
    out = {"thought": 0, "by_code": 0, "waiting": 0}
    while clock() - started < budget_s:
        got = claim(now=now_fn())
        out["by_code"] += got["by_code"]
        out["waiting"] = got["waiting"]
        w = got["wake"]
        if w is None:
            if got["by_code"]:
                continue        # the candidates behind those answered
            break
        try:
            mind.think(w)
        except Exception as e:  # noqa: BLE001 — the watchdog closes it
            logger.warning("[orcs] wake %s: the read failed: %s", w.pk, e)
        out["thought"] += 1
    return out


def close_pending(code, *, now=None) -> int:
    """A.17: every pending wake answered by code (the minds switch OFF:
    `minds_off`), each in its own short transaction under the line lock
    and its Orc's lock. Returns how many it closed."""
    from bot_program.orcs import journal
    from bot_program.orcs.models import OrcWake
    now = now or timezone.now()
    n = 0
    for wid, orc_id in list(OrcWake.objects.filter(
            status=WAKE_STATUS_PENDING).values_list("id", "orc_id")):
        with transaction.atomic():
            line_lock()
            locked = journal.orc_lock(orc_id)
            w = OrcWake.objects.select_for_update().get(pk=wid)
            if w.status != WAKE_STATUS_PENDING:
                continue
            _by_code(locked, w, code, now=now)
            n += 1
    return n


# ── the settle ───────────────────────────────────────────────────────────

def _counters(locked, now, *, cost, routine, unbilled_high=0.0,
              unbilled_drop=0.0) -> tuple:
    """(fields, seen keys) of the four day counters after this settle,
    reset first when the UTC day moved (A.12, §4 Q7). Pure."""
    seen = locked.seen if isinstance(locked.seen, dict) else {}
    today = utc_day(now)
    fields = {k: getattr(locked, k) for k in COUNTERS}
    unbilled = float(seen.get("unbilled_usd") or 0.0)
    if seen.get(COUNTERS_DAY) != today:
        fields = {"llm_wakes_today": 0, "routine_wakes_today": 0,
                  "spend_today_usd": Decimal(0),
                  "routine_spend_today_usd": Decimal(0)}
        unbilled = 0.0
    fields["spend_today_usd"] = Decimal(str(fields["spend_today_usd"] or 0)) \
        + cost
    if routine:
        fields["routine_spend_today_usd"] = Decimal(str(
            fields["routine_spend_today_usd"] or 0)) + cost
    unbilled = max(0.0, unbilled + float(unbilled_high)
                   - float(unbilled_drop))
    return fields, {COUNTERS_DAY: today, "unbilled_usd": round(unbilled, 6)}


def _row_status(locked) -> str:
    from bot_program.models import AssetBotTrade
    return str(AssetBotTrade.objects.filter(pk=locked.root_trade_id)
               .values_list("status", flat=True).first() or "")


def _late_code(locked) -> str:
    """A.26: why an answer that came back can no longer be applied: the
    row closed, the Orc dead, or a gate OFF (its code); "" when none."""
    from bot_program.orcs import switches
    if _row_status(locked) not in _open_statuses():
        return CODE_ROW_CLOSED
    if locked.state == STATE_DEAD:
        return CODE_DEAD
    return switches.gate_code()


def _late_hold(w, outcome, *, usage, cost, ledger, rung, now) -> tuple:
    """A.24, A.25 for a late settle (2026-11-05, completing O2a): the
    orphan hold the watchdog made of a wall-timed wake's bound (A.55),
    after its call came back. (the hold's kind kept, or "", the HIGH to
    take off the Orc's unbilled dollars). The caller holds the line lock.

      a bill, its ledger row found   the hold dropped, its HIGH with it
      a bill, no ledger row          the booked cost held as `ledger_gap`
                                     until 00:00 UTC; its HIGH dropped, the
                                     cost being in the Orc's day dollars
      nothing sent (closed, unsent)  the hold dropped: nothing can bill
      no bill (a timeout, a cut      the hold and its HIGH kept until
      stream, a network error)       00:00 UTC: the tokens streamed
                                     before the cut may still be billed"""
    kind = outcome.get("kind")
    if usage is not None:
        gone = drop_hold(w, now)
        if ledger:
            return "", float(gone.get("high") or 0.0)
        hold(kind=HOLD_LEDGER_GAP, usd=cost, wake=w, rung=rung, now=now)
        return HOLD_LEDGER_GAP, float(gone.get("high") or 0.0)
    if kind in (REPLY_CLOSED, REPLY_UNSENT):
        gone = drop_hold(w, now)
        return "", float(gone.get("high") or 0.0)
    store = _inflight_row()
    value = _pruned(store.value if isinstance(store.value, dict) else {},
                    now)
    entry = value.get(f"w{w.pk}")
    return (str(entry.get("kind") or HOLD_ORPHAN)
            if isinstance(entry, dict) else ""), 0.0


def _send_back(locked, now) -> int:
    """A.24 step 6: the Orc's pending wake goes back to the render,
    still as of its own moment, reading the Orc's journal up to now."""
    from bot_program.orcs.models import OrcWake
    from bot_program.orcs.wake import RENDER_QUEUED
    n = 0
    for w in OrcWake.objects.select_for_update().filter(
            orc_id=locked.pk, status=WAKE_STATUS_PENDING):
        w.status = WAKE_STATUS_RECORDED
        w.components = {**(w.components or {}), "render": RENDER_QUEUED,
                        "journal_as_of": now.isoformat()}
        w.save(update_fields=["status", "components"])
        n += 1
    return n


def settle(wake, outcome, *, now=None) -> dict:
    """Settle one claimed wake with what its call came back with
    (`outcome`, mind.judge's), in one short transaction (A.24-A.26), then
    the Orc's states (A.51-A.53) and, after a failed call, the breaker
    (A.56). Returns {status, code, held, sent_back, late}."""
    from bot_program.orcs import journal, mind
    from bot_program.orcs.models import OrcWake
    now = now or timezone.now()
    usage = outcome.get("usage") if isinstance(outcome.get("usage"),
                                               dict) else None
    cost = Decimal(str(round(float((usage or {}).get("cost_usd") or 0), 6)))
    rung = str(outcome.get("rung") or "")
    # A.24 step 3's one lookup of the provider's ledger row, made by the
    # mind before this transaction (through the gateway, which alone names
    # the ledger): never inside a lock
    ledger = outcome.get("ledger")
    routine = is_routine(wake.reasons)
    out = {"status": "", "code": "", "held": "", "sent_back": 0,
           "late": False}
    with transaction.atomic():
        line_lock()
        locked = journal.orc_lock(wake.orc_id)
        w = OrcWake.objects.select_for_update().get(pk=wake.pk)
        if w.status != WAKE_STATUS_RUNNING:
            # a late settle (A.55): the real cost booked once, nothing else
            # written; its orphan hold kept or released by what came back
            # (A.24, A.25), as a ticket's late settle does
            held, unbilled_drop = _late_hold(w, outcome, usage=usage,
                                             cost=cost, ledger=ledger,
                                             rung=rung, now=now)
            fields, keys = _counters(locked, now, cost=cost, routine=routine,
                                     unbilled_drop=unbilled_drop)
            mind.write_late_settle(locked, w, outcome, now=now,
                                   fields=fields, keys=keys, held=held)
            mind.write_intellect(locked, w, outcome)
            out.update(status=w.status, late=True,
                       held=f"w{w.pk}" if held else "")
            return out
        held_high = 0.0
        kind = outcome.get("kind")
        if kind == REPLY_UNBILLED:
            held_high = high(rung)
            out["held"] = hold(kind=HOLD_UNBILLED, usd=w.est_usd, wake=w,
                               rung=rung, now=now, high_usd=held_high)
        elif usage is not None and not ledger:
            out["held"] = hold(kind=HOLD_LEDGER_GAP, usd=cost, wake=w,
                               rung=rung, now=now)
        fields, keys = _counters(locked, now, cost=cost, routine=routine,
                                 unbilled_high=held_high)
        late = _late_code(locked) if kind == REPLY_ANSWER else ""
        w.est_usd = Decimal(0)
        w.finished_at = now
        saved = ["status", "skipped_reason", "est_usd", "finished_at"]
        served = str((usage or {}).get("model") or "")[:50]
        if served and served != w.model:
            # B.14 (O2b, 2026-11-06): the server's fallback answered; the
            # model that did is the wake's, as on the decision entry
            w.model = served
            saved.append("model")
        if late:
            mind.write_late(locked, w, outcome, now=now, code=late,
                            fields=fields, keys=keys)
        else:
            mind.write_outcome(locked, w, outcome, now=now, fields=fields,
                               keys=keys)
        w.save(update_fields=saved)
        mind.write_intellect(locked, w, outcome)
        if not late:
            states(locked, w, outcome, now=now)
        if w.status == WAKE_STATUS_FAILED:
            _trip(now)
        out.update(status=w.status, code=w.skipped_reason, late=bool(late))
        out["sent_back"] = _send_back(locked, now)
    return out


# ── the Orc's states (A.51-A.53) ─────────────────────────────────────────

def takeover(locked, reason, *, wake=None, now) -> None:
    """A.53: the care takes the idea. A `takeover` journal entry, a code
    FACT (an F-id, body {fk: "care", reason, wake}, so fence.fact_kind
    reads a T0 care fact), in fixed words; state `care_owned`, its words
    and its moment; both counters reset. In shadow nothing changes in what
    the care does: the care always holds the row in O2. The caller holds
    the Orc's lock."""
    from bot_program.orcs import journal
    words = CARE_WORDS.get(reason, reason)
    journal.append(locked, "takeover", f"The care holds this position: "
                   f"{words}.", fact=True,
                   body={"fk": "care", "reason": reason,
                         "wake": getattr(wake, "pk", None)},
                   wake=wake, at=now,
                   fields={"state": STATE_CARE_OWNED,
                           "care_owned_reason": words[:200],
                           "care_owned_at": now},
                   remember={"refused_in_row": 0, "failed_in_row": 0})
    logger.info("[orcs] Orc %s: the care takes the idea (%s)", locked.pk,
                reason)


def _cites_takeover(locked, w, outcome) -> str:
    """A.53's return: the F-id of the Orc's latest takeover when this
    wake's dossier carried it (the fact existed when the wake was
    rendered: its number is at most vctx.max_fact, and PS5 pins it while
    the care holds the idea) and the answer cites it; "" otherwise."""
    from bot_program.orcs.models import OrcJournal
    took = (OrcJournal.objects.filter(orc_id=locked.pk, kind="takeover")
            .exclude(fact_id="").order_by("-at", "-id").first())
    if took is None:
        return ""
    cited = set((outcome.get("kept") or {}).get("facts_cited") or [])
    number = took.fact_id[1:]
    vctx = ((w.components or {}).get("vctx") or {})
    try:
        shown = int(number) <= int(vctx.get("max_fact") or 0)
    except (TypeError, ValueError):
        shown = False
    return took.fact_id if shown and took.fact_id in cited else ""


def states(locked, w, outcome, *, now) -> None:
    """A.51-A.53 after a settle's writes, inside its transaction (database
    writes only). What moves the two counters (A.52):

      refused_in_row  rises on a refused answer: the wake ended `refused`
                      (a V-rule), or `done` with an intent the officer
                      would refuse
      failed_in_row   rises on a `failed` wake
      both reset      on any other `done` wake

    A code answer, `quiet`, `merged` and `late` never move either, nor a
    part refusal (V9, V11). Then: born -> active on the first done wake;
    a done wake that carried the takeover in its dossier and cites it
    returns the Orc from the care (a `return` entry); CARE_AFTER_REFUSED
    refused answers or CARE_AFTER_FAILED failed calls in a row send the
    Orc to the care (A.53's takeover)."""
    from bot_program.orcs import journal
    status = w.status
    seen = locked.seen if isinstance(locked.seen, dict) else {}
    refused = int(seen.get("refused_in_row") or 0)
    failed = int(seen.get("failed_in_row") or 0)
    intent = outcome.get("intent") if isinstance(outcome.get("intent"),
                                                 dict) else {}
    would_refuse = (intent.get("officer") or {}).get("verdict") == \
        OFFICER_REFUSE
    if status == WAKE_STATUS_FAILED:
        failed += 1
    elif status == WAKE_STATUS_REFUSED or (status == WAKE_STATUS_DONE
                                           and would_refuse):
        refused += 1
    elif status == WAKE_STATUS_DONE:
        refused = failed = 0
    else:
        return
    if locked.state == STATE_DEAD:
        return
    counts = {"refused_in_row": refused, "failed_in_row": failed}
    if status == WAKE_STATUS_DONE and locked.state == STATE_CARE_OWNED:
        cited = _cites_takeover(locked, w, outcome)
        if cited:
            journal.append(locked, "return", RETURN_WORDS,
                           body={"wake": w.pk, "takeover": cited},
                           wake=w, at=now,
                           fields={"state": STATE_ACTIVE,
                                   "care_owned_reason": "",
                                   "care_owned_at": None},
                           remember=counts)
            return
    reason = (CARE_ANSWERS_REFUSED if refused >= CARE_AFTER_REFUSED
              else CARE_CALLS_FAILING if failed >= CARE_AFTER_FAILED
              else "")
    if reason and locked.state != STATE_CARE_OWNED:
        takeover(locked, reason, wake=w, now=now)
        return
    fields = {}
    if status == WAKE_STATUS_DONE and locked.state == STATE_BORN:
        fields["state"] = STATE_ACTIVE
    journal.remember(locked, fields=fields, **counts)


# ── the watchdog (A.54-A.56) ─────────────────────────────────────────────

def _stalled(now) -> int:
    """A.54: the pending wakes whose FIRST send is older than STALL_MIN.
    Nothing re-stamps queued_at; a claim ends the stall clock."""
    from bot_program.orcs.models import OrcWake
    n = OrcWake.objects.filter(
        status=WAKE_STATUS_PENDING,
        queued_at__lt=now - timedelta(minutes=STALL_MIN)).count()
    if n:
        logger.warning("[orcs] %s wake(s) waited over %s minutes for a "
                       "model call", n, STALL_MIN)
    return n


def _wall_s(comps) -> int:
    """A.21's wall time of a running wake, in seconds: WALL_S of the rung
    it was claimed on (components["rung"]; r0 when it names none), plus
    its twin's for an r5 wake's pair (O2b's frontier, 2026-11-06), sent
    one after the other within the claim's one wall time. _wall_time
    closes a wake past it; _worker_silent counts a wake inside it as a
    call in flight."""
    comps = comps if isinstance(comps, dict) else {}
    rung = str(comps.get("rung") or O2A_RUNG)
    wall = WALL_S.get(rung, WALL_S[O2A_RUNG])
    twin = comps.get("twin") if isinstance(comps.get("twin"), dict) else {}
    if twin.get("rung") in WALL_S:
        wall += WALL_S[twin["rung"]]
    return int(wall)


def _calls_in_flight(now) -> bool:
    """A.55 (2026-11-06, completing O2b): a call the worker sent is still
    inside its wall time: a running wake claimed less than its wall time
    ago (_wall_s), or a ticket of a caller the worker itself sends
    (WORKER_TICKET_CALLERS: the probes, r5's twin) reserved less than its
    `wall_s` ago. From O2b such a call may run past STALE_MIN (r3's wall
    is 2,160 s, r4's 3,460 s), and while it does the worker is busy. A
    smoke's ticket is the shell's, never the worker's; a call past its
    wall time is the wall time's to judge (A.55, A.57). Reads only."""
    from bot_program.orcs.models import OrcWake
    for started, comps in OrcWake.objects.filter(
            status=WAKE_STATUS_RUNNING, started_at__isnull=False,
            started_at__lte=now).values_list("started_at", "components"):
        if now - started <= timedelta(seconds=_wall_s(comps)):
            return True
    value = _setting(MINDS_INFLIGHT_KEY)
    for entry in _pruned(value if isinstance(value, dict) else {},
                         now).values():
        if entry.get("kind") != HOLD_TICKET or \
                entry.get("caller") not in WORKER_TICKET_CALLERS:
            continue
        at = _parse(entry.get("at"))
        try:
            wall = float(entry.get("wall_s") or 0)
        except (TypeError, ValueError):
            continue
        if at is not None and at <= now and \
                now - at <= timedelta(seconds=wall):
            return True
    return False


def _worker_silent(now) -> bool:
    """A.55: no wake was claimed (started_at) and none settled in the
    last STALE_MIN, and no call the worker sent is still inside its wall
    time (_calls_in_flight; 2026-11-06, completing O2b: from O2b an r3 or
    r4 call, a routed wake's or a probe's, may run past STALE_MIN, and a
    wake that waited behind it waited behind a busy worker, §4 Q8). A
    settle is a claimed wake that finished; a wake the watchdog closed for
    its wall time is not one."""
    from bot_program.orcs.models import OrcWake
    cutoff = now - timedelta(minutes=STALE_MIN)
    if OrcWake.objects.filter(started_at__gte=cutoff,
                              started_at__lte=now).exists():
        return False
    if OrcWake.objects.filter(started_at__isnull=False,
                              finished_at__gte=cutoff,
                              finished_at__lte=now) \
            .exclude(skipped_reason=CODE_WALL_TIME).exists():
        return False
    return not _calls_in_flight(now)


def _stale(now, *, paused) -> dict:
    """A.55: each pending wake older than STALE_MIN is closed: answered by
    code while a gate is OFF (its code) or after a pause of the watchdog
    (`paused`), with no care; `stale` with `worker_silent` when the worker
    was silent (_worker_silent), and its Orc goes to the care (A.52); else
    `skipped` with `backlog`: it waited behind a busy worker (a claim or a
    settle in the last STALE_MIN, or a call still inside its wall time), a
    code answer, never a refusal and never silence."""
    from bot_program.orcs import journal, switches
    from bot_program.orcs.models import OrcWake
    out = {"stale": 0, "backlog": 0, "by_code": 0}
    old = list(OrcWake.objects.filter(
        status=WAKE_STATUS_PENDING,
        queued_at__lt=now - timedelta(minutes=STALE_MIN))
        .order_by("queued_at", "id").values_list("id", "orc_id"))
    if not old:
        return out
    gate = switches.gate_code()
    silent = _worker_silent(now)
    for wid, orc_id in old:
        with transaction.atomic():
            line_lock()
            locked = journal.orc_lock(orc_id)
            w = OrcWake.objects.select_for_update().get(pk=wid)
            if w.status != WAKE_STATUS_PENDING:
                continue
            if gate or paused:
                _by_code(locked, w, gate or CODE_PAUSED, now=now)
                out["by_code"] += 1
            elif silent:
                w.status, w.skipped_reason = (WAKE_STATUS_STALE,
                                              CODE_WORKER_SILENT)
                w.finished_at = now
                w.save(update_fields=["status", "skipped_reason",
                                      "finished_at"])
                out["stale"] += 1
                if locked.state not in (STATE_CARE_OWNED, STATE_DEAD):
                    takeover(locked, CARE_WORKER_SILENT, wake=w, now=now)
            else:
                _by_code(locked, w, CODE_BACKLOG, now=now)
                out["backlog"] += 1
    return out


def _wall_time(now) -> int:
    """A.55: a running wake past WALL_S(rung) since started_at is closed
    `failed` (code `wall_time`), for the care's counters; its bound moves
    to a hold of kind `orphan` until 00:00 UTC (its HIGH on the Orc's
    unbilled dollars): the call may still be streaming, or be orphaned by
    a worker's restart, and may yet bill. Its late settle books the real
    cost once and keeps or releases the hold by what came back
    (_late_hold): never released without a bill or a call never sent."""
    from bot_program.orcs import journal
    from bot_program.orcs.models import OrcWake
    n = 0
    for w0 in list(OrcWake.objects.filter(status=WAKE_STATUS_RUNNING,
                                          started_at__isnull=False)):
        comps = w0.components if isinstance(w0.components, dict) else {}
        rung = str(comps.get("rung") or O2A_RUNG)
        # an r5 wake's pair (O2b's frontier, 2026-11-06): its twin is sent
        # first, then r5, within the claim's one wall time (_wall_s)
        if now - w0.started_at <= timedelta(seconds=_wall_s(comps)):
            continue
        with transaction.atomic():
            line_lock()
            locked = journal.orc_lock(w0.orc_id)
            w = OrcWake.objects.select_for_update().get(pk=w0.pk)
            if w.status != WAKE_STATUS_RUNNING:
                continue
            held_high = high(rung)
            hold(kind=HOLD_ORPHAN, usd=w.est_usd, wake=w, rung=rung, now=now,
                 high_usd=held_high)
            fields, keys = _counters(locked, now, cost=Decimal(0),
                                     routine=False, unbilled_high=held_high)
            w.status, w.skipped_reason = WAKE_STATUS_FAILED, CODE_WALL_TIME
            w.est_usd = Decimal(0)
            w.finished_at = now
            w.save(update_fields=["status", "skipped_reason", "est_usd",
                                  "finished_at"])
            journal.append(locked, "error", "The model call ran past its wall "
                           "time: its bound stays held until 00:00 UTC.",
                           body={"wake": w.pk, "code": CODE_WALL_TIME,
                                 "rung": rung, "held": True},
                           wake=w, at=now, fields=fields, remember=keys)
            states(locked, w, {"kind": "wall_time"}, now=now)
            n += 1
    if n:
        with transaction.atomic():
            line_lock()
            _trip(now)
    return n


def _holds(now) -> dict:
    """The holds: the expired ones pruned at 00:00 UTC, never earlier;
    those still held counted, the ledger gaps apart (A.24, A.25)."""
    with transaction.atomic():
        line_lock()
        store = _inflight_row()
        value = store.value if isinstance(store.value, dict) else {}
        kept = _pruned(value, now)
        if kept != value:
            store.value = kept
            store.save(update_fields=["value"])
    return {"held": len(kept),
            "ledger_gap": sum(1 for e in kept.values()
                              if e.get("kind") == HOLD_LEDGER_GAP)}


def _watch_last():
    """The watchdog's previous pass (OrcSetting "minds_watch_last_at"),
    read; None when it never ran."""
    value = _setting(MINDS_WATCH_LAST_KEY)
    return _parse(value.get("at") if isinstance(value, dict) else value)


def _paused(last, now) -> bool:
    """A.55: the watchdog did not run for more than WATCH_PAUSED_MIN
    before `now` (or never ran): the Orcs were paused, `orcs` or the
    platform master OFF, whose task gate skips the watchdog and the
    worker alike."""
    return last is None or now - last > timedelta(minutes=WATCH_PAUSED_MIN)


def _watch_stamp(now):
    """The watchdog's previous pass (OrcSetting "minds_watch_last_at"),
    then this one stamped. None when it never ran."""
    from bot_program.orcs.models import OrcSetting
    last = _watch_last()
    OrcSetting.objects.update_or_create(
        key=MINDS_WATCH_LAST_KEY, defaults={"value": {"at": now.isoformat()},
                                            "updated_by": "watchdog"})
    return last


def watch(*, now=None) -> dict:
    """One pass of the minds' watchdog (A.54-A.56; orc_minds_watch, on
    `slow`, every 5 minutes: never on the fast queue, N8), its steps in
    the census's tuple style, each fenced. The result names the counts
    (stalled, stale, backlog, wall-timed, the tickets wall-timed (A.57),
    holds, breaker, ledger gaps, and the wakes answered by code for budget
    today), never a `skipped`,
    `parsed` or `attempted` key (core/task_gate.py reads those as a
    health verdict); `idle` when nothing waits, runs or is held."""
    from bot_program.orcs.models import OrcWake
    now = now or timezone.now()
    last = _watch_stamp(now)
    paused = _paused(last, now)
    out = {"minds_stalled": 0, "minds_stale": 0, "minds_backlog": 0,
           "minds_wall_time": 0, "minds_ticket_wall_time": 0,
           "minds_holds": 0, "minds_ledger_gap": 0, "minds_breaker": 0,
           "answered_by_code": 0}

    def stale():
        got = _stale(now, paused=paused)
        out["minds_backlog"] = got["backlog"]
        return got["stale"]

    def holds():
        got = _holds(now)
        out["minds_ledger_gap"] = got["ledger_gap"]
        return got["held"]

    day_start = datetime.combine(_utc(now).date(), datetime.min.time(),
                                 tzinfo=dt_tz.utc)
    steps = (("minds_stalled", lambda: _stalled(now)),
             ("minds_stale", stale),
             ("minds_wall_time", lambda: _wall_time(now)),
             # A.57 (O2a's arm, 2026-11-05): a ticket past its wall time
             # becomes an orphan hold until 00:00 UTC, before the holds count
             ("minds_ticket_wall_time", lambda: _tickets_wall_time(now)),
             ("minds_holds", holds),
             ("minds_breaker", lambda: 1 if breaker_state(now) else 0),
             ("answered_by_code", lambda: OrcWake.objects.filter(
                 status=WAKE_STATUS_SKIPPED, skipped_reason__in=BUDGET_CODES,
                 created_at__gte=day_start).count()))
    for key, step in steps:
        try:
            out[key] = int(step() or 0)
        except Exception as e:  # noqa: BLE001 — one step never stops the rest
            logger.warning("[orcs] the minds' watchdog step %s failed: %s",
                           key, e)
    waiting = OrcWake.objects.filter(status__in=(WAKE_STATUS_PENDING,
                                                 WAKE_STATUS_RUNNING)).exists()
    alarms = []
    for key, words in (
            ("minds_stalled", "waited over 20 minutes for a model call"),
            ("minds_stale", "closed stale: the worker was silent"),
            ("minds_backlog", "answered by code after waiting behind a busy "
                              "worker"),
            ("minds_wall_time", "ran past their wall time"),
            ("minds_ledger_gap", "held: the provider wrote no ledger row")):
        if out[key]:
            alarms.append(f"{out[key]} wake(s) {words}")
    if out["minds_ticket_wall_time"]:
        alarms.append(f"{out['minds_ticket_wall_time']} ticket(s) ran past "
                      f"their wall time: their bounds stay held until 00:00 "
                      f"UTC")
    if out["minds_breaker"]:
        alarms.append("the breaker pauses the claims")
    if alarms:
        return {"status": "warning", "reason": "; ".join(alarms), **out}
    if not waiting and not out["minds_holds"] and not out["minds_wall_time"]:
        return {"idle": "no wake waits for a model and no money is held",
                **out}
    return {"status": "success", **out}
