"""THE PROBES (the O2 spec B.8a, B.11, B.12, B.16; O2b, 2026-11-06): the
rungs beside the one that answered, measured in shadow.

Behind `orcs_probes` (OFF on arrival, turned on only with the trading PIN,
N2), beside a paper or demo wake a model read (its call came back `done`
or `refused`), each probe its route lists (router.py's probes[]: h0 on calm
and eventful days, the rung across a band boundary within BAND_HYSTERESIS
of 30, 55 or 75) reads the wake's OWN stored dossier again, blind to the
routed answer, on its answering rung (B.5's map, read when it is sent, as
a ticket's is; never the wake's own rung). Real money gets none (§4 Q13),
and the weather's caps say on which days any is sent (weather.caps_for's
`probes`, binding from O2b, B.8a).

  due            the probes due now, oldest routed answer first: reads only
  run            from the worker (tasks.orc_think, after its claims, with no
                 lock held): one probe at a time, LAST of all (a real-money
                 wake waiting for its call stops the pass: the next run
                 claims it first), the probes' switch and the four gates
                 read before each one; a probe goes within PROBE_FRESH_MIN
                 of the routed answer, else it is dropped by code
  send           one probe: a ticket (A.57; scheduler.reserve_ticket, under
                 the line lock: its item 'probe:<wake>:<kind>' billed once,
                 its day cap by (caller, kind, user), the class C - R, the
                 deep share for an Opus rung, the core's floor, the probes'
                 own allowance, then the line), ONE send through the
                 gateway with no fallback (B.14: its bound the primary's
                 alone), agent orc, source_ref Orc:<pk>:Wake:<w>:probe:
                 <rung>; the ticket settled once the ledger row is looked
                 up; the answer judged by the same validator with no lock
                 held (mind.judge_probe); the pair stored (OrcTierGrade)
  grade_forward  B.12, from the watchdog's task (tasks.orc_minds_watch,
                 after scheduler.watch, with no lock held: the scheduler
                 never names pricing): each pair priced by pricing.py over
                 the next final decision-frame bar after the LATER answer,
                 read from stored bars
  ladder, boundary_states  what the surfaces read (/orcs/seats/ for staff,
                 /ai-models/): shown only, read by no router
  store_twin     B.10 (O2b's frontier, 2026-11-06): r5's blind twin, sent by
                 mind.think beside its r5 wake (never from here): its answer
                 judged by the same validator, blind, and kept only as a
                 `twin` pair, real money's (the probe pairs' table); in O2
                 the pair cannot run (frontier_state, for /ai-models/)

A probe is stored ONLY in OrcTierGrade and the ledger: never a plan, an
intent, a note, a card line, a PS5 note or a journal entry, and never
counted in the Orc's own caps (its wakes, its dollars, its spacing). Its
note is read by nothing: a pair keeps each side's action, its level id
(only when it names the wake's own menu, mind._kept), whether the
validator passed it, a tighten's would-stop (a price) and its moment.
Nothing here reaches an order, a stop, a size or a close (N1).
"""
import logging
import time
from collections import Counter
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from bot_program.orcs.constants import (ACTIONS, CLASS_REAL, CODE_DAY_CAP,
                                        CODE_PROBE_REAL, CODE_PROBES_OFF,
                                        CODE_REAL_WAITS, CODE_UNBILLED,
                                        CODE_UNSENT, ITEM_CLOSED,
                                        ITEM_RESERVED, ITEM_WAITING,
                                        MINDS_TICKETS_KEY, O2A_RUNG,
                                        PROBE_BOUNDARIES, PROBE_CALLER,
                                        PROBE_FRESH_MIN, PROBE_GRADE_DAYS,
                                        PROBE_KINDS, RANKS, REPLY_ANSWER,
                                        REPLY_BILLED, REPLY_UNBILLED,
                                        SEAT_WINDOW, THINK_RUN_S, TRIM_SHARE,
                                        TWIN_CALLER, TWIN_RUNG,
                                        VALIDATED_BLOCKS, VENUE_DEMO,
                                        VENUE_LIVE, VENUE_PAPER,
                                        WAKE_STATUS_DONE,
                                        WAKE_STATUS_PENDING,
                                        WAKE_STATUS_REFUSED)

logger = logging.getLogger(__name__)

#: The caller of a probe's ticket (§1.0.9).
CALLER = PROBE_CALLER
#: The routed answers a probe stands beside (B.11): a model read the wake.
ANSWERED = (WAKE_STATUS_DONE, WAKE_STATUS_REFUSED)
#: The money worlds a pair is graded in, never pooled (B.12): a demo seat's
#: own, else paper (a row that states no world is budgeted as paper).
WORLDS = (VENUE_PAPER, VENUE_DEMO)
#: The decision frame a pair is graded on when its context names none.
DEFAULT_TF = "4h"


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and v not in (float("inf"), float("-inf")) else None


def _parse(value):
    from django.utils.dateparse import parse_datetime
    if hasattr(value, "tzinfo"):
        return value
    try:
        return parse_datetime(str(value)) if value else None
    except (TypeError, ValueError):
        return None


def item_key(wake, kind) -> str:
    """A.57's item of one probe: one billed attempt per (wake, kind)."""
    return f"{CALLER}:{getattr(wake, 'pk', wake)}:{kind}"


def world_of(orc) -> str:
    """The pair's money world (B.12: blocks never pool worlds): `demo` for
    an Orc on a demo seat (the seat is the row's money world in the
    platform's words), else `paper`. Real money gets no probe."""
    seat = getattr(orc, "seat", None)
    venue = str(getattr(seat, "venue", "") or "")
    return VENUE_DEMO if venue == VENUE_DEMO else VENUE_PAPER


def real_waits() -> bool:
    """A real-money wake waits for its model call (`pending`, ranked real,
    A.14): probes go last (map_army §3.4), so none is sent then."""
    from bot_program.orcs.models import OrcWake
    return OrcWake.objects.filter(status=WAKE_STATUS_PENDING,
                                  priority__gte=RANKS[CLASS_REAL]).exists()


# ── which probes are due (B.11) ──────────────────────────────────────────

def _skip_item(item) -> bool:
    """A probe's ticket item that may not be tried again: closed (billed,
    failed twice, refused before the send, expired), in flight, or refused
    for the day's cap (a cap reached today stays reached)."""
    if not isinstance(item, dict):
        return False
    state = item.get("state")
    return state in ITEM_CLOSED + (ITEM_RESERVED,) or (
        state == ITEM_WAITING and item.get("code") == CODE_DAY_CAP)


def due(now) -> list:
    """The probes due at `now` (B.11), oldest routed answer first:
    [(wake, {kind, rung, would_rung, boundary})]. Beside each paper or demo
    wake a model read (done or refused) within PROBE_FRESH_MIN, on a day
    the weather lets probes run (weather.caps_for's `probes`, B.8a), each
    probe its route lists, its rung mapped now (B.5: one effort per model
    until the smoke's PASS), never the wake's own answering rung, with no
    pair stored for it and its ticket item neither closed, in flight nor
    capped for the day. A routed answer older than the window is dropped
    by code: its probe is never sent. Database reads only."""
    from bot_program.orcs import mind, router, scheduler, weather
    from bot_program.orcs.models import OrcSetting, OrcTierGrade, OrcWake
    wakes = list(OrcWake.objects.filter(
        status__in=ANSWERED,
        finished_at__gte=now - timedelta(minutes=PROBE_FRESH_MIN),
        finished_at__lte=now)
        .select_related("orc", "orc__seat", "orc__root_trade")
        .order_by("finished_at", "id"))
    if not wakes:
        return []
    stored = set(OrcTierGrade.objects.filter(
        wake_id__in=[w.pk for w in wakes]).values_list("wake_id", "kind"))
    book = OrcSetting.get(MINDS_TICKETS_KEY) or {}
    items = book.get("items") if isinstance(book, dict) and isinstance(
        book.get("items"), dict) else {}
    emap = mind.answering_map()
    out = []
    for w in wakes:
        comps = w.components if isinstance(w.components, dict) else {}
        route = comps.get("route") if isinstance(comps.get("route"),
                                                 dict) else {}
        listed = [p for p in route.get("probes") or [] if isinstance(p, dict)]
        if not listed or comps.get("real"):
            continue
        if not weather.caps_for(w.day_class, False).get("probes"):
            continue
        if scheduler.is_real(w.orc):
            continue
        answering = str(comps.get("rung") or O2A_RUNG)
        for p in listed:
            kind = str(p.get("kind") or "")
            would = str(p.get("would_rung") or p.get("rung") or "")
            if kind not in PROBE_KINDS or (w.pk, kind) in stored:
                continue
            rung = router.answering(would, emap)
            if rung == answering or _skip_item(items.get(item_key(w, kind))):
                continue
            boundary = p.get("boundary") if kind == "boundary" else None
            out.append((w, {"kind": kind, "rung": rung, "would_rung": would,
                            "boundary": (int(boundary) if boundary in
                                         PROBE_BOUNDARIES else None)}))
    return out


# ── the worker's pass (B.11 as built) ────────────────────────────────────

def run(*, clock=None, now_fn=None, budget_s=THINK_RUN_S) -> dict:
    """The probes, from the worker (tasks.orc_think, after its claims, no
    lock held): the due probes one at a time, oldest routed answer first,
    for `budget_s` at most. Before each one the probes' switch, the four
    gates and the queue are read anew: a probe goes only while
    `orcs_probes` and the four gates are ON and no real-money wake waits
    for its call (probes go last: the next run claims that wake first).
    Returns {probed, by_code, code}: `code` why the pass stopped, or why
    its last probe was answered by code ("" when none)."""
    from bot_program.orcs import switches
    clock = clock or time.monotonic
    now_fn = now_fn or timezone.now
    started = clock()
    out = {"probed": 0, "by_code": 0, "code": ""}
    tried = set()
    while clock() - started < budget_s:
        code = (CODE_PROBES_OFF if not switches.probes_on()
                else switches.gate_code()
                or (CODE_REAL_WAITS if real_waits() else ""))
        if code:
            out["code"] = code
            break
        now = now_fn()
        nxt = next(((w, p) for w, p in due(now)
                    if (w.pk, p["kind"]) not in tried), None)
        if nxt is None:
            break
        w, p = nxt
        tried.add((w.pk, p["kind"]))
        got = send(w, p, now=now)
        if got["sent"]:
            out["probed"] += 1
        else:
            out["by_code"] += 1
            out["code"] = got["code"]
    return out


def send(wake, probe, *, now=None) -> dict:
    """One probe of `wake` (one of due()'s): its request from the wake's
    own stored blocks on the probe's rung (mind.build_request); its ticket
    (A.57) for the primary's bound alone, reserved under the line lock
    against the probes' own allowance and C - R; ONE send through the
    gateway with no fallback, agent orc, source_ref
    Orc:<pk>:Wake:<w>:probe:<rung>; the ticket settled whatever came back,
    the ledger's row looked up first; then the answer judged by the same
    validator with no lock held, and the pair stored. A real-money wake is
    refused before any ticket (`real_money`). Returns {sent, code, grade}:
    `grade` the stored pair when the call came back billed (an answer, or
    a billed failure, stored invalid), else None."""
    from bot_program.orcs import mind, mind_gateway, scheduler
    now = now or timezone.now()
    out = {"sent": False, "code": "", "grade": None}
    orc = wake.orc
    if scheduler.is_real(orc):
        out["code"] = CODE_PROBE_REAL
        return out
    kind = str(probe.get("kind") or "")
    rung = str(probe.get("rung") or "")
    would = str(probe.get("would_rung") or rung)
    try:
        request = mind.build_request(wake, rung)
        tokens = mind.ticket_tokens(wake, rung)
        ref = mind.source_ref(wake, rung, caller=CALLER)
        got = scheduler.reserve_ticket(CALLER, {
            "rung": rung, "tokens": tokens, "item": item_key(wake, kind),
            "orc": orc.pk, "ref": ref, "kind": kind, "user": orc.user_id,
            "would_rung": would}, now=now)
    except (ValueError, KeyError, TypeError) as e:
        # nothing reserved and nothing sent: a dossier gone, a rung the
        # probe may not use (N4)
        logger.info("[orcs] wake %s: its %s probe was not sent: %s",
                    wake.pk, kind, e)
        out["code"] = CODE_UNSENT
        return out
    if not got["ok"]:
        out["code"] = got["code"]
        return out
    # what the settle reads if the gateway itself raised: a call that may
    # have been sent, its bound held until 00:00 UTC
    reply = {"kind": REPLY_UNBILLED, "sent": True, "usage": None,
             "code": CODE_UNBILLED}
    started = timezone.now()
    try:
        reply = mind_gateway.call(caller=CALLER, rung_name=rung,
                                  request=request, source_ref=ref,
                                  bound_usd=got["bound"],
                                  exclude_key=got["key"], would_rung=would)
    finally:
        usage = reply.get("usage") if isinstance(reply.get("usage"),
                                                 dict) else None
        found = (mind_gateway.ledger_row(ref, since=started)
                 if usage is not None else None)
        scheduler.settle_ticket(got["key"], {**reply, "ledger": found})
    out["sent"] = bool(reply.get("sent"))
    out["code"] = str(reply.get("code") or "")
    if reply.get("kind") in (REPLY_ANSWER, REPLY_BILLED):
        side = mind.judge_probe(wake, reply, now=timezone.now())
        out["grade"] = _store(wake, {**probe, "kind": kind, "rung": rung,
                                     "would_rung": would}, side, usage=usage)
    return out


# ── the pair (OrcTierGrade, B.12) ────────────────────────────────────────

def routed_side(wake) -> tuple:
    """(side, cost) of the answer the wake's own rung gave, read from what
    its settle stored: the decision entry (the answer as kept, so an id
    stands only when it names the wake's own menu; the validator's status
    and rule; the booked cost) and, for a tighten, its proposal's
    would-stop (OrcIntent). Database reads only."""
    from bot_program.orcs.models import OrcIntent, OrcJournal
    entry = (OrcJournal.objects.filter(wake_id=wake.pk, kind="decision")
             .order_by("id").first())
    body = entry.body if entry is not None and isinstance(entry.body,
                                                          dict) else {}
    answer = body.get("answer") if isinstance(body.get("answer"),
                                              dict) else {}
    action = str(answer.get("action") or "")
    action = action if action in ACTIONS else ""
    stop = None
    if action == "tighten":
        got = (OrcIntent.objects.filter(wake_id=wake.pk, kind="tighten")
               .values_list("would_stop", flat=True).first())
        stop = float(got) if got is not None else None
    side = {"action": action,
            "level_id": str(answer.get("level_id") or "") if answer else "",
            "valid": (wake.status == WAKE_STATUS_DONE
                      and body.get("status") == WAKE_STATUS_DONE),
            "rule": str(body.get("rule") or ""), "stop": stop,
            "at": wake.finished_at.isoformat() if wake.finished_at else ""}
    cost = entry.cost_usd if entry is not None else Decimal(0)
    return side, Decimal(str(cost or 0))


def _store(wake, probe, side, *, usage, world=None):
    """The pair, stored (scheduler.store_pair: one OrcTierGrade row, its
    block counted and written under the line lock, database work only,
    N8; this module holds no lock). None when the pair is stored already
    (one per wake and kind). `world`: the pair's money world, a probe's
    paper or demo (world_of) unless given (the twin's: real money)."""
    from bot_program.orcs import scheduler
    routed, routed_cost = routed_side(wake)
    comps = wake.components if isinstance(wake.components, dict) else {}
    route = comps.get("route") if isinstance(comps.get("route"),
                                             dict) else {}
    kind = probe["kind"]
    boundary = probe.get("boundary") if kind == "boundary" else None
    world = world or world_of(wake.orc)
    agree_action = bool(routed["action"]) and \
        routed["action"] == side.get("action")
    agree_level = agree_action and routed["level_id"] == side.get(
        "level_id") and routed["level_id"] not in ("", "unknown")
    cost = Decimal(str(round(float((usage or {}).get("cost_usd") or 0), 6)))
    return scheduler.store_pair({
        "wake": wake, "orc_id": wake.orc_id, "kind": kind,
        "boundary": boundary, "world": world,
        "routed_rung": str(comps.get("rung") or O2A_RUNG)[:4],
        "probe_rung": str(probe["rung"])[:4],
        "would_rung": str(route.get("would_rung") or "")[:4],
        "routed": routed, "probe": dict(side),
        "agree_action": agree_action, "agree_level": agree_level,
        "routed_cost_usd": routed_cost, "probe_cost_usd": cost})


def store_twin(wake, twin, reply, *, now=None):
    """B.10 (O2b's frontier, 2026-11-06): r5's blind twin, once both calls
    came back and the wake's settle stored r5's answer, the Orc's: the
    twin's answer judged by the same validator with no lock held, blind to
    r5's (mind.judge_probe: as of the wake's own moment, on the plan
    changes made before its claim), and the pair stored as kind `twin`,
    boundary none, in real money's world (r5 answers real money only):
    never a plan, an intent, a note, a card line, a PS5 note or a journal
    entry. Only when the twin's call came back billed (an answer, or a
    billed failure stored invalid). The pair or None."""
    from bot_program.orcs import mind
    from bot_program.orcs.models import OrcWake
    if not isinstance(reply, dict) or reply.get("kind") not in (
            REPLY_ANSWER, REPLY_BILLED):
        return None
    fresh = (OrcWake.objects.select_related("orc", "orc__seat")
             .get(pk=wake.pk))
    side = mind.judge_probe(fresh, reply, now=now or timezone.now())
    usage = reply.get("usage") if isinstance(reply.get("usage"),
                                             dict) else None
    return _store(fresh, {"kind": TWIN_CALLER,
                          "rung": str(twin.get("rung") or ""),
                          "would_rung": TWIN_RUNG, "boundary": None},
                  side, usage=usage, world=VENUE_LIVE)


def frontier_state() -> dict:
    """B.9 on /ai-models/ (O2b's frontier, 2026-11-06): whether Fable's
    gate can open at all. {pair_usd: the pair's bound at the dossier's size
    cap (mind.pair_price, about $3.57), floor_usd: the money the Orcs may
    hold in flight (ORC_LIVE_FLOOR_USD, $3.00), fits: the pair fits under
    it (never in O2), on: the frontier's switch, quota: OrcSetting
    frontier_per_day}. Shown only: no router reads it. Reads, never a
    call."""
    from bot_program.orcs import mind, mind_gateway, switches, weather
    pair = mind.pair_price()
    floor = float(mind_gateway.live_floor())
    return {"pair_usd": float(pair["weigh"]), "floor_usd": floor,
            "fits": float(pair["weigh"]) <= floor + 1e-9,
            "on": bool(switches.frontier_on()),
            "quota": int(weather.frontier_per_day())}


# ── the forward grade (B.12) ─────────────────────────────────────────────

def forward_r(side, bar, *, entry, rpu, direction, cf=0.0):
    """B.12: one side's R over `bar` ({open, high, low, close}: the next
    final decision-frame bar opening after the LATER answer, read from
    stored bars), each priced point less the one-way modelled cost
    (pricing.level_exit_px), its R by pricing.r_of:

      exit       the first price after the later answer: the bar's open
      trim       TRIM_SHARE there, the rest at the bar's close
      tighten    the bar's close; the would-stop when the bar traded
                 through it; the open when it opened through it (a gap)
      the rest   the bar's close: hold, revise_plan, lock_waive and add
                 (a lock waiver changes nothing at the bar, an add is
                 never applied); an invalid answer is priced as a hold,
                 since nothing of it is applied

    None when the R cannot be measured (no entry, no risk)."""
    from bot_program.orcs import pricing
    side = side if isinstance(side, dict) else {}
    action = str(side.get("action") or "") if side.get("valid") else "hold"

    def r(px):
        if px is None:
            return None
        return pricing.r_of(pricing.level_exit_px(px, direction, cf), entry,
                            rpu, direction)
    o, c = _f(bar.get("open")), _f(bar.get("close"))
    if action == "exit":
        return r(o)
    if action == "trim":
        a, b = r(o), r(c)
        if a is None or b is None:
            return None
        return TRIM_SHARE * a + (1.0 - TRIM_SHARE) * b
    if action == "tighten":
        stop = _f(side.get("stop"))
        if stop is not None and o is not None:
            sign = pricing.d(direction)
            if sign * (o - stop) <= 0:
                return r(o)
            lo, hi = _f(bar.get("low")), _f(bar.get("high"))
            if (sign > 0 and lo is not None and lo <= stop) or (
                    sign < 0 and hi is not None and hi >= stop):
                return r(stop)
    return r(c)


def _later(row, wake):
    """The LATER of the pair's two answers: the routed answer's moment
    (its side's `at`, else the wake's finished_at) and the probe's (its
    side's `at`, else the row's own moment)."""
    a = _parse((row.routed or {}).get("at")) or getattr(wake, "finished_at",
                                                         None)
    b = _parse((row.probe or {}).get("at")) or row.created_at
    known = [t for t in (a, b) if t is not None]
    return max(known) if known else None


def grade_pair(row, *, now):
    """B.12 for one pair: {routed, probe, at} (`at` the graded bar's end),
    or None while the bar after the later answer is not final yet. A pair
    whose wake keeps no position context (its symbol, side, entry or risk
    unread) is closed unmeasured: both R None, `at` now."""
    from bot_program.orcs import bars
    wake = row.wake
    comps = wake.components if wake is not None and isinstance(
        wake.components, dict) else {}
    vctx = comps.get("vctx") if isinstance(comps.get("vctx"), dict) else {}
    symbol, side = str(vctx.get("symbol") or ""), str(vctx.get("side") or "")
    entry, rpu = _f(vctx.get("entry")), _f(vctx.get("rpu"))
    later = _later(row, wake)
    if not symbol or not side or entry is None or rpu is None \
            or later is None:
        return {"routed": None, "probe": None, "at": now}
    tf = str(vctx.get("decision_tf") or DEFAULT_TF)
    got, _source = bars.complete_bars_after(symbol, tf, later, now,
                                            final=True, limit=2)
    if not got:
        return None
    bar = got[0]
    cf = _f(vctx.get("cf")) or 0.0
    return {"routed": forward_r(row.routed, bar, entry=entry, rpu=rpu,
                                direction=side, cf=cf),
            "probe": forward_r(row.probe, bar, entry=entry, rpu=rpu,
                               direction=side, cf=cf),
            "at": bar["end"]}


def grade_forward(*, now=None) -> int:
    """B.12, from the watchdog's task (tasks.orc_minds_watch, after
    scheduler.watch, with no lock held): every pair not graded yet, of the
    last PROBE_GRADE_DAYS, priced over the next final decision-frame bar
    after its later answer (grade_pair), each written once. Stored bars
    and the pricing only: no model, no lock. Returns how many pairs it
    graded."""
    from bot_program.orcs.models import OrcTierGrade
    now = now or timezone.now()
    n = 0
    for row in list(OrcTierGrade.objects.filter(
            fwd_at__isnull=True,
            created_at__gte=now - timedelta(days=PROBE_GRADE_DAYS))
            .select_related("wake").order_by("id")):
        try:
            got = grade_pair(row, now=now)
        except Exception as e:  # noqa: BLE001 — one pair never stops one
            logger.warning("[orcs] probe pair %s not graded: %s", row.pk, e)
            continue
        if got is None:
            continue
        n += OrcTierGrade.objects.filter(pk=row.pk, fwd_at__isnull=True)\
            .update(fwd_routed_r=got["routed"], fwd_probe_r=got["probe"],
                    fwd_at=got["at"])
    return n


# ── the surfaces' reads (B.16a, B.16b) ───────────────────────────────────

def _completed(blocks) -> int:
    """The completed blocks among a group's block indexes: SEAT_WINDOW
    pairs each."""
    return sum(1 for n in Counter(blocks).values() if n >= SEAT_WINDOW)


def _share(rows, test):
    return (sum(1 for r in rows if test(r)) / len(rows)) if rows else None


def _mean(xs):
    xs = [float(x) for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def ladder() -> list:
    """B.16b, the staff ladder table (/orcs/seats/): one row per (kind,
    boundary, world), the blocks' own key, from OrcTierGrade in one query:
    the answering rungs seen (routed vs probe), the pairs, the completed
    blocks and whether the group reads validated (VALIDATED_BLOCKS), each
    side's share of valid answers, the agreement on the action and on the
    level, each side's mean forward R over the graded pairs and their
    count, and each side's mean cost per pair (AI spend in USD, a staff
    page only). Shown only: no router reads it."""
    from bot_program.orcs.models import OrcTierGrade
    groups = {}
    for row in OrcTierGrade.objects.order_by("id").values(
            "kind", "boundary", "world", "routed_rung", "probe_rung",
            "routed", "probe", "agree_action", "agree_level",
            "routed_cost_usd", "probe_cost_usd", "fwd_routed_r",
            "fwd_probe_r", "fwd_at", "block"):
        groups.setdefault((row["kind"], row["boundary"], row["world"]),
                          []).append(row)
    out = []
    for (kind, boundary, world), rows in sorted(
            groups.items(), key=lambda kv: (kv[0][0], kv[0][1] or 0,
                                            kv[0][2])):
        graded = [r for r in rows if r["fwd_at"] is not None
                  and r["fwd_routed_r"] is not None
                  and r["fwd_probe_r"] is not None]
        blocks = _completed(r["block"] for r in rows)
        out.append({
            "kind": kind, "boundary": boundary, "world": world,
            "rungs": ", ".join(f"{a} vs {b}" for a, b in sorted(
                {(r["routed_rung"], r["probe_rung"]) for r in rows})),
            "pairs": len(rows), "blocks": blocks,
            "validated": blocks >= VALIDATED_BLOCKS,
            "valid_routed": _share(rows, lambda r: bool(
                (r["routed"] or {}).get("valid"))),
            "valid_probe": _share(rows, lambda r: bool(
                (r["probe"] or {}).get("valid"))),
            "agree_action": _share(rows, lambda r: r["agree_action"]),
            "agree_level": _share(rows, lambda r: r["agree_level"]),
            "fwd_routed": _mean(r["fwd_routed_r"] for r in graded),
            "fwd_probe": _mean(r["fwd_probe_r"] for r in graded),
            "graded": len(graded),
            "cost_routed": _mean(r["routed_cost_usd"] for r in rows) or 0.0,
            "cost_probe": _mean(r["probe_cost_usd"] for r in rows) or 0.0})
    return out


def boundary_states() -> list:
    """B.16a, on /ai-models/: each band boundary's state by money world,
    paper and demo never pooled, from its boundary probes' pairs in one
    query: {boundary, world, pairs, blocks (the completed ones, SEAT_WINDOW
    pairs each), validated (VALIDATED_BLOCKS completed)}. Shown only: no
    router reads it."""
    from bot_program.orcs.models import OrcTierGrade
    found = {}
    for boundary, world, block in OrcTierGrade.objects.filter(
            kind="boundary").values_list("boundary", "world", "block"):
        found.setdefault((boundary, world), []).append(block)
    out = []
    for boundary in PROBE_BOUNDARIES:
        for world in WORLDS:
            blocks = found.get((boundary, world), [])
            done = _completed(blocks)
            out.append({"boundary": boundary, "world": world,
                        "pairs": len(blocks), "blocks": done,
                        "validated": done >= VALIDATED_BLOCKS})
    return out
