"""THE SCHEDULER (the O2 spec A.24-A.27; O2a, 2026-11-05). This commit
builds its settle only: admission, the merge, the claim and the
watchdogs come with the queue. Nothing reaches it in production yet: no
wake is ever claimed, so none is ever settled.

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
call settling late) books its real cost on an error entry, drops its
hold, and writes nothing else (A.55).

THE MONEY HELD (OrcSetting "minds_inflight"): {key: {kind, usd, high,
orc, wake, rung, at, until}}. Every hold counts in the line's in-flight
sum (mind_gateway.inflight_usd) until it expires at 00:00 UTC, never
earlier; a late settle with usage drops its own.
"""
import logging
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from bot_program.orcs.constants import (HIGH, HOLD_LEDGER_GAP, HOLD_UNBILLED,
                                        LINE_LOCK_TIMEOUT_MS,
                                        MINDS_INFLIGHT_KEY, MINDS_LOCK_KEY,
                                        ORC_STATEMENT_TIMEOUT_MS,
                                        PER_ORC_HIGH_KEY, REPLY_ANSWER,
                                        REPLY_UNBILLED, WAKE_STATUS_PENDING,
                                        WAKE_STATUS_RECORDED,
                                        WAKE_STATUS_RUNNING)

logger = logging.getLogger(__name__)

#: The four day counters (models.py) and the memory key of their day.
COUNTERS = ("llm_wakes_today", "routine_wakes_today", "spend_today_usd",
            "routine_spend_today_usd")
COUNTERS_DAY = "counters_day"
#: A wake is routine when every reason is one of these, or a plan's watch.
ROUTINE_CODES = ("W2", "W11")


def _utc(now):
    return now.astimezone(dt_tz.utc)


def utc_day(now) -> str:
    """The UTC date the line's day and the counters' day are (A.12)."""
    return _utc(now).date().isoformat()


def next_midnight(now) -> datetime:
    """00:00 UTC after `now`: when every hold expires (A.25)."""
    day = _utc(now).date() + timedelta(days=1)
    return datetime(day.year, day.month, day.day, tzinfo=dt_tz.utc)


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
    """Drop the hold of `wake`'s call, if any (a late settle with usage
    books the real cost instead); the entry dropped, or {}."""
    store = _inflight_row()
    value = _pruned(store.value if isinstance(store.value, dict) else {},
                    now)
    gone = value.pop(f"w{wake.pk}", None) or {}
    store.value = value
    store.save(update_fields=["value"])
    return gone


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
    from bot_program.orcs.constants import (CODE_DEAD, CODE_ROW_CLOSED,
                                            STATE_DEAD)
    from bot_program.orcs.wake import OPEN_STATUSES
    if _row_status(locked) not in OPEN_STATUSES:
        return CODE_ROW_CLOSED
    if locked.state == STATE_DEAD:
        return CODE_DEAD
    return switches.gate_code()


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
    (`outcome`, mind.judge's), in one short transaction (A.24-A.26).
    Returns {status, code, held, sent_back, late}."""
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
            # a late settle (A.55): the real cost booked once, its hold
            # dropped, nothing else written
            gone = drop_hold(w, now)
            fields, keys = _counters(locked, now, cost=cost, routine=routine,
                                     unbilled_drop=float(gone.get("high")
                                                         or 0.0))
            mind.write_late_settle(locked, w, outcome, now=now,
                                   fields=fields, keys=keys)
            out.update(status=w.status, late=True)
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
        if late:
            mind.write_late(locked, w, outcome, now=now, code=late,
                            fields=fields, keys=keys)
        else:
            mind.write_outcome(locked, w, outcome, now=now, fields=fields,
                               keys=keys)
        w.save(update_fields=["status", "skipped_reason", "est_usd",
                              "finished_at"])
        out.update(status=w.status, code=w.skipped_reason, late=bool(late))
        out["sent_back"] = _send_back(locked, now)
    return out
