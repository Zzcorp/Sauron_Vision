"""THE QUEUED INTENTS AT THE TICK (the O2 spec A.41-A.45b, P32, P33; O2a,
2026-11-05). A proposal of a model's answer, judged by the officer and
queued by the settle (mind._write_intent: an OrcIntent `queued`, its id in
seen["intents_queued"]), steps the Orc's own arm, the O arm, at the next
tick, and nothing else: never the row, its stops, its metadata or the
tick's own objects (A.45, A.45b). The proposals' words and the card's
three newest live here, read by the settle too.

  take           A.42, called from ghost._step_orc on the O arm's state:
                 each queued intent, oldest first, is
                   expired  `ttl` once its time to live has passed;
                            `arm_closed` once an earlier one closed the arm;
                            `moved` when a tighten's would-stop has lost its
                            room on the tick's own price and closing-side
                            mark (0.5 ATR of its timeframe, as V7 measured
                            it) or is no longer tighter than the arm's
                            effective stop, or a trim finds nothing to bank
                   waiting  on a tick with no fresh price (a shut market:
                            its price is the last print before the shut) or
                            a row whose state cannot be read (P32): it is
                            never priced later, at a reopen gap; and while
                            the care holds the idea (`care_owned`, A.53: it
                            holds the would-world too), so one queued
                            before the takeover is never applied
                   applied  on any other tick, priced by pricing.py at that
                            tick: `simulated`, with applied_at,
                            applied_price and applied_r; the arm steps
                            through ghost.apply_intent
                 A tick with nothing queued costs no query: the queue is
                 read from the Orc already in hand (observe.py).
  expire_queued  A.44 and A.42: every intent still queued expires with one
                 code, `row_closed` at step_bars' first walk after the
                 close, `arm_closed` at a tick once the arm has closed
  _write         the writes, in their own savepoint, the Orc tables only:
                 the Orc's lock first (journal.merge_seen: the ids leave
                 seen["intents_queued"] by a callable run on the LOCKED
                 memory, so an id the settle queued meanwhile stays), then
                 each status (only from `queued`), one `intent` entry each
                 (author code, off the card's lines) and the card's three
                 newest. On the tick it runs inside the tick's lock budget
                 (observe.after_care, N8). Every price is drawn before it
                 opens, and the arm takes its new state only once it
                 committed: a write refused leaves the arm and the queue for
                 the next tick

THE PRICES. A tighten applies at its would-stop (the level's own stop
beyond the crowd, or the BE row's price: V7, P33); a trim and an exit at
pricing.market_exit_px of the tick; a lock waiver at the tick's closing-
side mark. applied_r is that price's R per unit of the arm's risk.
"""
import copy
import logging
import re
from decimal import Decimal

from django.db import transaction

from bot_program.orcs import pricing
from bot_program.orcs.constants import (EXPIRY_ARM_CLOSED, EXPIRY_MOVED,
                                        EXPIRY_TTL, EXPIRY_WORDS,
                                        INTENT_APPLIED_KINDS,
                                        INTENT_STATUS_EXPIRED,
                                        INTENT_STATUS_QUEUED,
                                        INTENT_STATUS_RECORDED,
                                        INTENT_STATUS_REFUSED,
                                        INTENT_STATUS_SIMULATED,
                                        MIN_STOP_ROOM_ATR, MOVED_WORDS,
                                        STATE_CARE_OWNED)

logger = logging.getLogger(__name__)

#: The proposals' words (A.41): "tighten to S4h-L1 (2,612.00)".
INTENT_WORDS = {"tighten": "tighten to {lv}", "trim": "trim at {lv}",
                "exit": "exit at {lv}", "lock_waive": "waive the lock for {ev}",
                "add": "add at {lv}"}
#: An event as code names it (dossier.events_of): a print "C<calendar
#: id>", a shut "SH<yymmddHHMM>". A lock waiver's words name its event
#: only in this form; anything else, "unknown" or a model's own text read
#: from an older row alike, reads EVENT_UNLISTED (N5; 2026-11-05,
#: completing O2a).
EVENT_CODE = re.compile(r"(?:C\d{1,12}|SH\d{10})")
EVENT_UNLISTED = "an unlisted event"
#: An intent's status on the card (A.41, A.62).
STATUS_T = {INTENT_STATUS_QUEUED: "queued for the shadow arm",
            INTENT_STATUS_RECORDED: "recorded, never applied",
            INTENT_STATUS_REFUSED: "would be refused",
            INTENT_STATUS_SIMULATED: "applied to the shadow arm",
            INTENT_STATUS_EXPIRED: "expired"}
#: The card keeps the newest intents (A.41).
CARD_INTENTS = 3
#: The row's statuses whose state a tick can read (wake.OPEN_STATUSES).
READABLE_STATUSES = ("OPEN", "CLOSE_PENDING")
#: The memory key of the queue (mind._write_intent writes it).
QUEUE_KEY = "intents_queued"


class _Lost(Exception):
    """An intent this pass decided on was taken meanwhile by another
    writer: the savepoint rolls back and the next tick reads the queue
    again."""


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and v not in (float("inf"), float("-inf")) else None


# ── the words and the card ───────────────────────────────────────────────

def _level_words(target, level) -> str:
    from bot_program.orcs.facts import px
    level = level if isinstance(level, dict) else {}
    if not level.get("level_id"):
        return "market"
    return f"{level['level_id']} ({px(target, level.get('price'))})"


def intent_words(target, intent) -> str:
    """A proposal in fixed words, its price drawn by code (A.41); a lock
    waiver's event by its code id only (EVENT_CODE), never a model's
    text."""
    tpl = INTENT_WORDS.get(str(intent.get("kind") or ""), "{lv}")
    ev = str(intent.get("event_id") or "")
    return tpl.format(lv=_level_words(target, intent.get("level")),
                      ev=ev if EVENT_CODE.fullmatch(ev) else EVENT_UNLISTED)


def _words_of(target, it) -> str:
    return intent_words(target, {"kind": it.kind, "level": it.level,
                                 "event_id": it.event_id})


def card_intents(orc) -> list:
    """The card's newest CARD_INTENTS intents, read again (one query),
    oldest first, each {kind_t, mode, status_t}, as mind._write_intent
    shows a new one."""
    from bot_program.orcs.models import OrcIntent
    newest = list(OrcIntent.objects.filter(orc_id=orc.pk)
                  .order_by("-created_at", "-id")[:CARD_INTENTS])
    return [{"kind_t": f"proposed in shadow: {_words_of(orc, it)}",
             "mode": it.mode,
             "status_t": STATUS_T.get(it.status, it.status)}
            for it in reversed(newest)]


# ── what the tick can judge (P32's second clause) ────────────────────────

def queued(orc) -> list:
    """The ids in seen["intents_queued"] of the Orc in hand: no query."""
    seen = orc.seen if isinstance(orc.seen, dict) else {}
    out = []
    for x in seen.get(QUEUE_KEY) or []:
        if isinstance(x, int) and x not in out:
            out.append(x)
    return out


def fresh(env, tick) -> bool:
    """The mark, the first of the integrity verdict's critical items a
    tick can judge: the tick's own price, read in an open market (a shut
    market's price is its last print before the shut). An unreadable
    clock is not fresh: the intent waits."""
    p = _f(getattr(tick, "p", None))
    if p is None or p <= 0:
        return False
    try:
        from core.exchange_status import market_clock
        clock = market_clock(str(getattr(env.row, "asset_class", "") or ""),
                             "", str(getattr(env.row, "symbol", "") or ""),
                             now_utc=env.now)
    except Exception as e:  # noqa: BLE001 — an unread clock waits
        logger.info("[orcs] the market's clock unread: %s", e)
        return False
    return bool(clock.get("is_open"))


def readable(env) -> bool:
    """The row, the second: its state readable (open, its metadata a
    dict, an entry price and a side), as the dossier's row_ok reads it.
    The bars item stays as the dossier judged it (A.42)."""
    return (isinstance(getattr(env.row, "metadata", None), dict)
            and str(getattr(env.row, "status", "") or "")
            in READABLE_STATUSES
            and (_f(getattr(env.row, "entry_price", None)) or 0.0) > 0
            and str(getattr(env.row, "side", "") or "").upper()
            in ("BUY", "SELL"))


def _vctx(it) -> dict:
    """The validation context the intent's wake kept (A.8): its ATR and
    its events, as of the dossier."""
    comps = (it.wake.components if it.wake is not None
             and isinstance(it.wake.components, dict) else {})
    vctx = comps.get("vctx")
    return vctx if isinstance(vctx, dict) else {}


def _room(work, tick, stop, level, vctx) -> str:
    """A tighten at the tick (A.42): "" when its would-stop keeps 0.5 ATR
    of its timeframe (the ATR the wake measured, as V7 did) from the
    tick's own price and closing-side mark and is still tighter than the
    arm's effective stop; else MOVED_WORDS' key."""
    from bot_program.orcs.ghost import arm_effective
    side = work.get("side")
    cf = _f(work.get("cf")) or 0.0
    sign = pricing.d(side)
    atr = vctx.get("atr") if isinstance(vctx.get("atr"), dict) else {}
    tf = str((level or {}).get("tf") or "") or "4h"
    a = _f(atr.get(tf)) or _f(atr.get("4h"))
    if stop is None or not a:
        return "unmeasured"
    room = MIN_STOP_ROOM_ATR * a
    m = pricing.closing_mark(tick, side, cf)
    if sign * (tick.p - stop) < room or sign * (m - stop) < room:
        return "room"
    eff = arm_effective(work)
    if eff is not None and sign * (stop - eff) <= 0:
        return "tighter"
    return ""


def _event_at(vctx, event_id):
    """A lock waiver's event moment, from the wake's own events (A.8)."""
    ev = (vctx.get("events") or {}).get(str(event_id or "")) \
        if isinstance(vctx.get("events"), dict) else None
    return ev.get("at") if isinstance(ev, dict) else None


# ── the outcomes ─────────────────────────────────────────────────────────

def _expired(orc, it, code, why="") -> dict:
    why = str(why or EXPIRY_WORDS.get(code, code))
    return {"pk": it.pk,
            "fields": {"status": INTENT_STATUS_EXPIRED, "rule": code[:16],
                       "why": why[:200]},
            "headline": f"Expired in shadow: {_words_of(orc, it)}: {why}.",
            "body": {"intent": it.pk, "kind": it.kind,
                     "status": INTENT_STATUS_EXPIRED, "rule": code,
                     "why": why, "wake": it.wake_id,
                     "decision": it.decision_id}}


def _simulated(orc, it, price, r, *, now) -> dict:
    from bot_program.orcs.facts import px
    r_t = f"{r:+.2f}R" if r is not None else "its R not measured"
    return {"pk": it.pk,
            "fields": {"status": INTENT_STATUS_SIMULATED, "rule": "",
                       "applied_at": now,
                       "applied_price": Decimal(str(round(price, 8))),
                       "applied_r": r, "why": STATUS_T[
                           INTENT_STATUS_SIMULATED]},
            "headline": (f"Applied in shadow: {_words_of(orc, it)}, at "
                         f"{px(orc, price)} ({r_t}); nothing was sent."),
            "body": {"intent": it.pk, "kind": it.kind,
                     "status": INTENT_STATUS_SIMULATED, "rule": "",
                     "applied_price": round(price, 8), "applied_r": r,
                     "wake": it.wake_id, "decision": it.decision_id}}


def _apply(orc, work, env, tick, it) -> dict:
    """One queued intent on the arm's working state (a copy the caller
    keeps only when it applied): {applied, exit, outcome}. Every price is
    drawn here, before any lock."""
    from bot_program.orcs.ghost import apply_intent
    side = work.get("side")
    cf = _f(work.get("cf")) or 0.0
    level = it.level if isinstance(it.level, dict) else {}
    vctx = _vctx(it)
    stop = _f(it.would_stop)
    if it.kind == "tighten":
        why = _room(work, tick, stop, level, vctx)
        if why:
            return {"applied": False, "exit": None,
                    "outcome": _expired(orc, it, EXPIRY_MOVED,
                                        MOVED_WORDS[why])}
        price = stop
    elif it.kind == "lock_waive":
        price = pricing.closing_mark(tick, side, cf)
    else:
        price = pricing.market_exit_px(tick, side, cf)
    applied, out = apply_intent(
        work, env, tick, kind=it.kind, intent=it.pk, would_stop=stop,
        level_id=str(level.get("level_id") or it.level_id or ""),
        share=_f(it.share), event_id=it.event_id,
        event_at=_event_at(vctx, it.event_id))
    if not applied:
        return {"applied": False, "exit": None,
                "outcome": _expired(orc, it, EXPIRY_MOVED,
                                    MOVED_WORDS["trim"])}
    r = pricing.r_of(price, work.get("entry"), work.get("rpu"), side)
    record = list(work.get("intents_applied") or [])
    record.append({"intent": it.pk, "kind": it.kind,
                   "at": env.now.isoformat(), "px": round(price, 8)})
    work["intents_applied"] = record[-50:]
    return {"applied": True, "exit": out,
            "outcome": _simulated(orc, it, price, r, now=env.now)}


# ── the tick ─────────────────────────────────────────────────────────────

def take(orc, state, env, tick):
    """A.42: the queued intents of `orc` at this tick, on the O arm's
    `state` (the tick's working copy, which ghost.step_tick saves). The
    arm's exit when an applied exit closed it, else None. Never raises:
    a write refused leaves the queue and the arm for the next tick."""
    ids = queued(orc)
    if not ids:
        return None
    from bot_program.orcs.models import OrcIntent
    items = list(OrcIntent.objects.filter(orc_id=orc.pk, pk__in=ids)
                 .select_related("wake").order_by("created_at", "id"))
    now = env.now
    # A.53: while the care holds the idea it holds the would-world too: a
    # proposal queued before the takeover waits, and expires with its time
    ok = (str(getattr(orc, "state", "") or "") != STATE_CARE_OWNED
          and fresh(env, tick) and readable(env))
    work = copy.deepcopy(state)
    found = {it.pk for it in items}
    gone = [i for i in ids if i not in found]
    outcomes, out = [], None
    for it in items:
        if it.status != INTENT_STATUS_QUEUED or \
                it.kind not in INTENT_APPLIED_KINDS:
            # never applied: an add is recorded, a taken one has left
            gone.append(it.pk)
            continue
        if it.expires_at is not None and now >= it.expires_at:
            outcomes.append(_expired(orc, it, EXPIRY_TTL))
            continue
        if out is not None:
            outcomes.append(_expired(orc, it, EXPIRY_ARM_CLOSED))
            continue
        if not ok:
            continue
        trial = copy.deepcopy(work)
        done = _apply(orc, trial, env, tick, it)
        outcomes.append(done["outcome"])
        if done["applied"]:
            work = trial
            out = done["exit"] or out
    if not outcomes and not gone:
        return None
    try:
        _write(orc, outcomes, gone, now=now)
    except Exception as e:  # noqa: BLE001 — the next tick reads it again
        logger.warning("[orcs] Orc %s: the queued intents were not taken: "
                       "%s", orc.pk, e)
        return None
    state.clear()
    state.update(work)
    return out


def expire_queued(orc, code, *, now) -> int:
    """A.44 and A.42: every intent still queued for `orc` expired with
    `code` (row_closed, arm_closed). No query while nothing is queued.
    Returns how many it expired."""
    ids = queued(orc)
    if not ids:
        return 0
    from bot_program.orcs.models import OrcIntent
    items = list(OrcIntent.objects.filter(orc_id=orc.pk, pk__in=ids)
                 .order_by("created_at", "id"))
    found = {it.pk for it in items}
    outcomes = [_expired(orc, it, code) for it in items
                if it.status == INTENT_STATUS_QUEUED]
    gone = [i for i in ids if i not in found] + [
        it.pk for it in items if it.status != INTENT_STATUS_QUEUED]
    _write(orc, outcomes, gone, now=now)
    return len(outcomes)


def _unqueue(done):
    """journal.merge_seen's callable, run on the LOCKED memory: the queue
    less `done`; it returns the ids of `done` the queue still held."""
    done = set(done)

    def fn(seen):
        cur = [x for x in (seen.get(QUEUE_KEY) or []) if isinstance(x, int)]
        seen[QUEUE_KEY] = [x for x in cur if x not in done]
        return set(cur) & done
    return fn


def _write(orc, outcomes, gone, *, now) -> None:
    """The outcomes' writes, in their own savepoint, the Orc tables only
    (above). Raises when nothing could be written; nothing is then."""
    from bot_program.orcs import journal
    from bot_program.orcs.models import OrcIntent
    mine = {o["pk"] for o in outcomes}
    done = mine | {int(x) for x in gone}
    seen0, card0 = copy.deepcopy(orc.seen), copy.deepcopy(orc.card)
    try:
        with transaction.atomic():
            held = journal.merge_seen(orc, _unqueue(done))
            lost = mine - set(held or ())
            if lost:
                raise _Lost(sorted(lost))
            for o in outcomes:
                n = OrcIntent.objects.filter(
                    pk=o["pk"], status=INTENT_STATUS_QUEUED).update(
                    **o["fields"])
                if n != 1:
                    raise _Lost([o["pk"]])
            card = card_intents(orc) if outcomes else None
            for i, o in enumerate(outcomes):
                last = i == len(outcomes) - 1
                journal.append(orc, "intent", o["headline"], author="code",
                               body=o["body"], at=now, card=False,
                               card_extra={"intents": card} if last
                               else None)
    except Exception:
        orc.seen, orc.card = seen0, card0
        raise

