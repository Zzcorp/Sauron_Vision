"""THE HARM COUNTERS (the eToro feed spec, F1, §6.2; 2026-11-07).

Evidence before any PIN. Each time today's code does one of the harms the
later phases remove, one FeedHarmEvent row says so, and `manage.py
feed_harms --days N` prints the counts by kind — never a price, an account
figure or an id. It is the baseline F2a, F2b, F5 and F8 are judged on:

  mark_skip_*            mark sanity suspended a REAL row's management this
                         tick (mark_sanity.check): a disagreeing outside
                         quote, an unconfirmed jump, a frozen mark — with
                         why, the levels, and whether eToro's closing side
                         had crossed the stop or the target (F2a);
  close_no_mark,         the CLOSE button refused a close for "no usable
  close_preview_no_mark  price mark", and its dialog said so first (F2b);
  kill_switch_wait       the seconds the kill switch read a price before a
                         close (F2b);
  poller_previous_close  a poller wrote Yahoo's previous close as a fresh
                         last; poller_out_of_session, a poller's price
                         outside the market clock's session; quote_bad_sides,
                         a zero or crossed side stored (F5);
  exit_*                 a real exit booked at Sauron's mark, at an outside
                         quote, at a level the venue held, with no price,
                         or left CLOSE_PENDING for the drain (F8).

EVERY HOOK STAYS OUT OF THE MONEY PATH IT WATCHES. A hook reads only what
the path already holds — no request, no query on the path — and is called
inside two fences: the path calls it only through bot_program.feed_fence
.count, and its body catches what it raises itself; either way a failure
is logged once at WARNING (later failures of the same kind at DEBUG), and
the path's answer, its timing and its commit are untouched. Its row is
never written inside the path's transaction: it is handed to
transaction.on_commit (the pattern the Orcs' journal hooks use) and only
queued once the path's work has committed — never if the path rolls back.

NO ROW IS WRITTEN ON A MONEY PATH'S THREAD (2026-11-07, the review of F1:
a synchronous insert after each booking stood between two closes of the
drain). On PostgreSQL, a committed row joins this process's queue and its
writer thread writes it — the pattern of the rates cache's writer
(engine/etoro_rates: one thread per process, a bounded queue, reset after
a fork) — in a short transaction of its own with a statement and lock
timeout, and closes its connection after each batch. On any other
database (SQLite: one writer at a time, so a concurrent insert would make
the path's own next write wait) and inside an open transaction (a test),
the row is written at once in its own savepoint. A full queue drops the
row and says so once; a row still queued when the process ends is lost —
a lost count, never a lost close. During a kill-switch sweep every row is
held in memory (hold) and queued once the sweep's last close has been
sent (release).
"""
from __future__ import annotations

import collections
import contextvars
import os
import threading
import time
from datetime import timedelta

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from bot_program import feed_fence
from market_data.venue_source import EXACT, is_venue_source

MARK_SKIP_REFERENCE = "mark_skip_reference"
MARK_SKIP_JUMP = "mark_skip_jump"
MARK_SKIP_FROZEN = "mark_skip_frozen"
CLOSE_NO_MARK = "close_no_mark"
CLOSE_PREVIEW_NO_MARK = "close_preview_no_mark"
KILL_SWITCH_WAIT = "kill_switch_wait"
POLLER_PREVIOUS_CLOSE = "poller_previous_close"
POLLER_OUT_OF_SESSION = "poller_out_of_session"
QUOTE_BAD_SIDES = "quote_bad_sides"
EXIT_AT_MARK = "exit_at_mark"
EXIT_AT_OUTSIDE_QUOTE = "exit_at_outside_quote"
EXIT_AT_LEVEL = "exit_at_level"
EXIT_UNPRICED = "exit_unpriced"
EXIT_CLOSE_PENDING = "exit_close_pending"

#: The kinds, in the order the report prints them, and their words.
KIND_WORDS = {
    MARK_SKIP_REFERENCE: "real row left unmanaged: an outside quote "
                         "disagreed",
    MARK_SKIP_JUMP: "real row left unmanaged: an unconfirmed jump",
    MARK_SKIP_FROZEN: "real row left unmanaged: a frozen mark",
    CLOSE_NO_MARK: "CLOSE refused: no usable price mark",
    CLOSE_PREVIEW_NO_MARK: "CLOSE dialog refused: no usable price mark",
    KILL_SWITCH_WAIT: "kill switch: price read before a close",
    POLLER_PREVIOUS_CLOSE: "poller wrote a previous close as fresh",
    POLLER_OUT_OF_SESSION: "poller wrote outside its market's session",
    QUOTE_BAD_SIDES: "quote stored with a zero or crossed side",
    EXIT_AT_MARK: "real exit booked at Sauron's mark",
    EXIT_AT_OUTSIDE_QUOTE: "real exit booked at an outside quote",
    EXIT_AT_LEVEL: "real exit booked at a level the venue held",
    EXIT_UNPRICED: "real exit booked with no price (pending)",
    EXIT_CLOSE_PENDING: "real close left pending for the drain",
}
KINDS = tuple(KIND_WORDS)

#: The pollers (market_data.tasks and its adapters): the session count
#: reads these sources only; a stream writes while its venue trades.
POLLER_SOURCES = ("yfinance", "alpha_vantage", "binance_public", "coingecko")

#: The write's bounds on PostgreSQL, local to its own short transaction.
STATEMENT_TIMEOUT_MS = 250
LOCK_TIMEOUT_MS = 100
#: The most rows one sweep holds: a runaway never grows a process.
HOLD_MAX = 5000
#: The most rows this process's queue keeps for its writer; past it a row
#: is dropped (told once).
QUEUE_MAX = 5000
#: The most rows one insert writes.
BATCH_MAX = 500
#: The writer's sleep when nothing wakes it, in seconds.
WRITER_IDLE_S = 1.0
#: Rows go to the writer thread (PostgreSQL, outside a transaction). Off,
#: every row is written at once in its own block (tests may say so).
BACKGROUND = True
#: The window `feed_harms --days` may ask for: whole days, at most ten
#: years (a larger one is no window, and overflows a date).
MAX_DAYS = 3650
#: A CLOSED save counts as a booking only while the row's close is this
#: recent: a later re-save of an old booking (a grade, a backfill) is not
#: one. Generous: a long kill-switch sweep books with its start time.
BOOKED_RECENT_S = 1800

_HOLD: contextvars.ContextVar = contextvars.ContextVar("feed_harms_hold",
                                                       default=None)


def _reset_warnings() -> None:
    """Forget which failures were already told (tests)."""
    feed_fence.forget()


def _warn(stage, kind, exc) -> None:
    """The fence's rule (feed_fence.told): one WARNING per (stage, kind,
    error type) and process, DEBUG after; the error's type only, never a
    value of the row."""
    feed_fence.told("the counter", f"the {stage} of one {kind} row", exc)


def _num(value):
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) != float("inf") else None


def _after_commit(fn) -> None:
    """Run `fn` once the caller's transaction commits (at once when it
    holds none). `fn` catches everything itself; robust=True is a second
    fence, never the first (Django's robust handler formats the callback's
    __qualname__, which a functools.partial lacks: the review of F1)."""
    transaction.on_commit(fn, robust=True)


def _record(kind, *, real=None, symbol="", source="", seconds=None,
            detail=None, ref="") -> None:
    """Queue one harm row (see the module docstring). Its callers fence
    it: anything raised here stays in the hook that called it."""
    row = {"at": timezone.now(), "kind": kind, "real": real,
           "symbol": str(symbol or "")[:40], "source": str(source or "")[:50],
           "seconds": None if seconds is None else float(seconds),
           "detail": dict(detail or {}), "ref": str(ref or "")[:64]}

    def deliver_after_commit():
        try:
            _deliver(row)
        except Exception as e:  # noqa: BLE001 — never into the committer
            _warn("write", kind, e)
    _after_commit(deliver_after_commit)


def _deliver(row) -> None:
    try:
        held = _HOLD.get()
        if held is not None:
            held.keep(row)
            return
        _write([row])
    except Exception as e:  # noqa: BLE001 — a lost count, never a raise
        _warn("write", row.get("kind"), e)


def _background() -> bool:
    """The writer thread takes the rows: PostgreSQL, outside any open
    transaction (no query: the connection's vendor and state)."""
    if not BACKGROUND:
        return False
    conn = transaction.get_connection()
    return conn.vendor == "postgresql" and not conn.in_atomic_block


def _write(rows) -> None:
    """Hand `rows` to this process's writer thread, or write them now
    (see the module docstring). Raises only what an at-once write raises:
    its callers fence it."""
    if _background():
        _enqueue(rows)
    else:
        _insert(rows)


# ── the writer thread: no harm row on a money path's thread ─────────────

#: the rows waiting for the writer, oldest first
_ROWS: collections.deque = collections.deque()
#: held by whoever writes the queue (the writer thread, flush)
_ROWS_LOCK = threading.Lock()
_WAKE = threading.Event()
#: this process's writer: {"pid", "thread"}
_WRITER: dict = {}
_WRITER_START = threading.Lock()


class QueueFull(Exception):
    """The writer's queue is full: a harm row was dropped."""


def _enqueue(rows) -> None:
    """Leave `rows` for the writer thread. Never waits; past QUEUE_MAX a
    row is dropped and the drop told once."""
    for row in rows:
        if len(_ROWS) >= QUEUE_MAX:
            _warn("queue", row.get("kind"), QueueFull())
            continue
        _ROWS.append(row)
    _wake_writer()


def _wake_writer() -> None:
    """Start this process's writer if none runs, then wake it. Never waits
    on a lock."""
    pid = os.getpid()
    held = _WRITER.get("thread")
    if held is None or _WRITER.get("pid") != pid or not held.is_alive():
        if _WRITER_START.acquire(blocking=False):
            try:
                held = _WRITER.get("thread")
                if held is None or _WRITER.get("pid") != pid \
                        or not held.is_alive():
                    t = threading.Thread(target=_writer_loop, daemon=True,
                                         name="feed-harms-writer")
                    _WRITER.update(pid=pid, thread=t)
                    t.start()
            finally:
                _WRITER_START.release()
    _WAKE.set()


def _writer_loop() -> None:
    while True:
        _WAKE.wait(WRITER_IDLE_S)
        _WAKE.clear()
        try:
            _drain()
        finally:
            _close_connection()


def _close_connection() -> None:
    """The writer holds no connection between batches."""
    try:
        from django.db import connection
        connection.close()
    except Exception:  # noqa: BLE001 — a connection already gone
        pass


def _drain(wait=None) -> None:
    """Write every queued row, BATCH_MAX at a time. `wait`: the most to
    wait for a drain another thread is in; None waits as long as it takes.
    Never raises."""
    if not _ROWS_LOCK.acquire(timeout=-1 if wait is None
                              else max(0.0, wait)):
        return
    try:
        while True:
            batch = []
            while len(batch) < BATCH_MAX:
                try:
                    batch.append(_ROWS.popleft())
                except IndexError:
                    break
            if not batch:
                return
            try:
                _insert(batch)
            except Exception as e:  # noqa: BLE001 — a lost count
                _warn("write", "queued", e)
    finally:
        _ROWS_LOCK.release()


def flush(wait=None) -> None:
    """Write what this process queued, now, on the caller's thread (tests;
    the process's exit). Never raises."""
    _drain(wait)


def _after_fork_in_child() -> None:
    """A forked worker writes what IT counts: the parent's queue, locks and
    thread are the parent's."""
    global _ROWS, _ROWS_LOCK, _WAKE, _WRITER_START
    _ROWS = collections.deque()
    _ROWS_LOCK = threading.Lock()
    _WAKE = threading.Event()
    _WRITER_START = threading.Lock()
    _WRITER.clear()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_after_fork_in_child)


def _bound() -> None:
    conn = transaction.get_connection()
    if conn.vendor != "postgresql":
        return
    with conn.cursor() as cur:
        cur.execute("SELECT set_config('statement_timeout', %s, true), "
                    "set_config('lock_timeout', %s, true)",
                    [f"{STATEMENT_TIMEOUT_MS}ms", f"{LOCK_TIMEOUT_MS}ms"])


def _insert(rows) -> None:
    """Write `rows` in one short transaction of their own (bounded on
    PostgreSQL; never the timeouts of a caller's transaction: inside one,
    a savepoint and no bound). A row whose (kind, ref) is already counted
    is skipped."""
    from bot_program.feed_harm_models import FeedHarmEvent
    outermost = not transaction.get_connection().in_atomic_block
    with transaction.atomic():
        if outermost:
            _bound()
        FeedHarmEvent.objects.bulk_create(
            [FeedHarmEvent(**r) for r in rows], ignore_conflicts=True)


class Hold:
    """A kill-switch sweep's harm rows, kept in memory until release()."""

    def __init__(self):
        self.rows = []
        self._token = _HOLD.set(self)

    def keep(self, row) -> None:
        if len(self.rows) < HOLD_MAX:
            self.rows.append(row)

    def release(self) -> None:
        """Stop holding and hand what was held to the writer (written at
        once off PostgreSQL). Never raises."""
        try:
            _HOLD.reset(self._token)
        except Exception:  # noqa: BLE001 — another context's token
            _HOLD.set(None)
        rows, self.rows = self.rows, []
        if not rows:
            return
        try:
            _write(rows)
        except Exception as e:  # noqa: BLE001
            _warn("write", "held", e)


def hold() -> Hold:
    """Hold every harm row of this context until release()."""
    return Hold()


def release(held) -> None:
    """Write what `held` (a Hold) kept: the kill switch's sweep is over."""
    held.release()


# ── the hooks ─────────────────────────────────────────────────────────────

def on_mark_verdict(bot, trade, price, reference, verdict) -> None:
    """mark_sanity.check suspended a REAL row this tick: why, the levels,
    and whether eToro's closing side (the bid for a long, the ask for a
    short, off the tick the engine kept; else the mark) had crossed the
    stop or the target — the cost F2a's shadow will weigh."""
    try:
        if getattr(trade, "paper", True) or (verdict or {}).get("ok", True):
            return
        from bot_program.mark_sanity import bar_for
        p, ref = _num(price), _num(reference)
        bar = bar_for(getattr(trade, "asset_class", ""))
        if verdict.get("frozen"):
            kind = MARK_SKIP_FROZEN
        elif ref and p and bar and abs(p - ref) / ref > bar:
            kind = MARK_SKIP_REFERENCE
        else:
            kind = MARK_SKIP_JUMP
        side = str(getattr(trade, "side", "") or "").upper()
        long_ = side in ("BUY", "LONG")
        tick = ((getattr(bot, "_last_ticks", None) or {})
                .get(getattr(trade, "symbol", "")) or {})
        basis = "bid" if long_ else "ask"
        closing = _num(tick.get(basis)) if isinstance(tick, dict) else None
        if not closing or closing <= 0:
            closing, basis = p, "last"
        stop = _num(getattr(trade, "stop_loss", None))
        target = _num(getattr(trade, "take_profit", None))
        crossed_stop = bool(stop and closing and (
            closing <= stop if long_ else closing >= stop))
        crossed_target = bool(target and closing and (
            closing >= target if long_ else closing <= target))
        meta = getattr(trade, "metadata", None) or {}
        _record(kind, real=True, symbol=getattr(trade, "symbol", ""),
                detail={"why": str(verdict.get("why") or "")[:300],
                        "price": p, "reference": ref, "bar": bar,
                        "side": side, "closing_side": closing,
                        "closing_basis": basis, "stop": stop,
                        "target": target, "crossed_stop": crossed_stop,
                        "crossed_target": crossed_target,
                        "protected": bool(meta.get("protected"))})
    except Exception as e:  # noqa: BLE001 — never the verdict
        _warn("count", "mark_skip", e)


def on_close_refused(trade, stage) -> None:
    """The CLOSE button's dialog ("preview") or its close ("execute")
    refused for no usable price mark (manual_close)."""
    try:
        kind = CLOSE_NO_MARK if stage == "execute" else CLOSE_PREVIEW_NO_MARK
        _record(kind, real=not getattr(trade, "paper", True),
                symbol=getattr(trade, "symbol", ""),
                detail={"asset_class": str(getattr(trade, "asset_class", "")
                                           or "")})
    except Exception as e:  # noqa: BLE001
        _warn("count", "close_no_mark", e)


#: The note the kill switch leaves on a row: the seconds its close waited
#: on its price read. In memory, never saved.
WAIT_ATTR = "_feed_mark_wait_s"


def note_wait(trade, started) -> None:
    """The kill switch read `trade`'s exit price from `started` (a
    time.monotonic() reading) until now: noted on the row for
    on_kill_switch_wait."""
    try:
        setattr(trade, WAIT_ATTR, max(0.0, time.monotonic() - started))
    except Exception as e:  # noqa: BLE001
        _warn("note", KILL_SWITCH_WAIT, e)


def on_kill_switch_wait(trade, seconds=None) -> None:
    """The seconds the kill switch read a price before `trade`'s close
    (engine/kill_switch, counted once the sweep's closes are sent); by
    default the seconds note_wait left on the row, if any."""
    try:
        if seconds is None:
            seconds = getattr(trade, WAIT_ATTR, None)
        if seconds is None:
            return
        _record(KILL_SWITCH_WAIT, real=not getattr(trade, "paper", True),
                symbol=getattr(trade, "symbol", ""),
                seconds=max(0.0, float(seconds)))
    except Exception as e:  # noqa: BLE001
        _warn("count", KILL_SWITCH_WAIT, e)


def _bad_sides(bid, ask) -> str:
    b, a = _num(bid), _num(ask)
    if (bid is not None and (b is None or b <= 0)) or \
            (ask is not None and (a is None or a <= 0)):
        return "zero side"
    if b is not None and a is not None and b > a:
        return "crossed"
    return ""


def _session_shut(inst) -> str:
    """The market clock's session word when `inst`'s market is shut now,
    else ""."""
    from core.exchange_status import market_clock
    clock = market_clock(getattr(inst, "asset_class", "") or "",
                         getattr(inst, "exchange", "") or "",
                         symbol=getattr(inst, "symbol", "") or "",
                         now_utc=timezone.now())
    if clock.get("modelled") and not clock.get("is_open", True):
        return str(clock.get("session") or "shut")
    return ""


def on_quote_written(inst, source, bid, ask) -> None:
    """market_data.quotes.write_quote stored a quote: a zero or crossed
    side it kept, and a poller's price outside its market's session."""
    try:
        why = _bad_sides(bid, ask)
        if why:
            _record(QUOTE_BAD_SIDES, symbol=getattr(inst, "symbol", ""),
                    source=source,
                    detail={"why": why, "bid": _num(bid), "ask": _num(ask)})
        if str(source or "").strip().lower() in POLLER_SOURCES:
            shut = _session_shut(inst)
            if shut:
                _record(POLLER_OUT_OF_SESSION,
                        symbol=getattr(inst, "symbol", ""), source=source,
                        detail={"asset_class": str(getattr(
                            inst, "asset_class", "") or ""),
                            "session": shut})
    except Exception as e:  # noqa: BLE001
        _warn("count", "quote", e)


def on_previous_close(inst, source) -> None:
    """A poller wrote Yahoo's previousClose as the quote's last
    (market_data.tasks._yf_market_quote's fallback)."""
    try:
        _record(POLLER_PREVIOUS_CLOSE, symbol=getattr(inst, "symbol", ""),
                source=source)
    except Exception as e:  # noqa: BLE001
        _warn("count", POLLER_PREVIOUS_CLOSE, e)


#: The note venue_mark.for_booking leaves on a real row it answered with
#: the platform's quote: that quote's source. In memory, never saved.
BOOKING_QUOTE_ATTR = "_feed_booking_quote"


def note_booking_quote(trade, quote) -> None:
    """venue_mark.for_booking answered a real row's booking with the
    platform's quote (the kill switch's and the reconcile's fallback)."""
    try:
        setattr(trade, BOOKING_QUOTE_ATTR,
                str(getattr(quote, "source", "") or ""))
    except Exception as e:  # noqa: BLE001
        _warn("count", "booking_quote", e)


def on_exit_saved(trade) -> None:
    """A REAL row was saved CLOSED or CLOSE_PENDING: what its exit was
    booked at, counted once per row and kind. eToro's own fill (the broker
    price) is no harm."""
    meta = trade.metadata if isinstance(trade.metadata, dict) else {}
    fill = str(meta.get("exit_fill_source") or "")
    source = ""
    if trade.status == "CLOSED":
        closed = getattr(trade, "closed_at", None)
        if closed is not None and (timezone.now() - closed
                                   ).total_seconds() > BOOKED_RECENT_S:
            return                      # a re-save of an old booking
    if trade.status == "CLOSE_PENDING":
        kind = EXIT_CLOSE_PENDING
    elif meta.get("exit_price_unavailable"):
        kind = EXIT_UNPRICED
    elif fill == "broker":
        return
    elif fill in ("venue_stop", "venue_target"):
        kind, source = EXIT_AT_LEVEL, fill
    else:
        quoted = getattr(trade, BOOKING_QUOTE_ATTR, None)
        if quoted is not None and not is_venue_source(
                quoted, str(meta.get("broker") or ""), reading=EXACT):
            kind, source = EXIT_AT_OUTSIDE_QUOTE, quoted
        else:
            kind, source = EXIT_AT_MARK, quoted or fill or "mark"
    _record(kind, real=True, symbol=trade.symbol, source=source,
            ref=f"trade:{trade.pk}",
            detail={"exit_fill_source": fill,
                    "inferred": meta.get("exit_price_inferred"),
                    "mark_age_s": meta.get("exit_mark_age_s")})


@receiver(post_save, sender="bot_program.AssetBotTrade",
          dispatch_uid="feed_harms_exit_saved")
def _exit_saved(sender, instance, created=False, update_fields=None,
                **kwargs):
    """Every booking path's save (the bot's close, the kill switch, the
    drain, the reconcile) passes here. No query and no write on the
    save's path; never raises."""
    try:
        if getattr(instance, "paper", True):
            return
        if getattr(instance, "status", "") not in ("CLOSED", "CLOSE_PENDING"):
            return
        if update_fields is not None and "status" not in update_fields:
            return
        on_exit_saved(instance)
    except Exception as e:  # noqa: BLE001 — never the booking
        _warn("count", "exit", e)


# ── the report ────────────────────────────────────────────────────────────

def report(days, *, now=None) -> dict:
    """{"since", "counts": {kind: n}, "waits": {"n", "p50", "max"} | None}
    over the last `days` days: counts and seconds, nothing else."""
    from bot_program.feed_harm_models import FeedHarmEvent
    from django.db.models import Count
    days = int(days)
    if not 1 <= days <= MAX_DAYS:
        raise ValueError(f"days must be 1 to {MAX_DAYS}")
    now = now or timezone.now()
    since = now - timedelta(days=days)
    qs = FeedHarmEvent.objects.filter(at__gte=since, at__lte=now)
    counts = {k: 0 for k in KINDS}
    for row in qs.values("kind").annotate(n=Count("id")):
        counts[row["kind"]] = counts.get(row["kind"], 0) + row["n"]
    waits = sorted(s for s in qs.filter(kind=KILL_SWITCH_WAIT)
                   .values_list("seconds", flat=True) if s is not None)
    w = None
    if waits:
        w = {"n": len(waits), "p50": waits[(len(waits) - 1) // 2],
             "max": waits[-1]}
    return {"since": since, "counts": counts, "waits": w}
