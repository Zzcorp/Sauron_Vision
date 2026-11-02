"""THE eTORO RATES, BATCHED AND SHARED (2026-11-01): one batched read per
pass, a shared cache the marks take at 30 s, one read per half hour
through a weekend shut.

Until today every open real row cost one GET /market-data/instruments/rates
per 5-minute tick (instrumentIds=<one id>), every proposal one more, and a
Saturday asked eToro for every live row and every signal of a shut market
all weekend. The marks, the proposals and the candles share one
market-data quota per user key (engine/etoro_budget), and their 429s held
the research entries (venue_health's SICK).

THE BATCH. EtoroTrader.tickers(symbols) sends ONE GET with instrumentIds as
a comma list, in chunks of at most BATCH_MAX_IDS (a guess, until eToro's
limit is measured), and matches every row to its symbol by the row's OWN
instrumentId, never by its position. Each symbol keeps the single read's
three states: a row missing for it raises for it alone (RowMissing: its
caller takes the single read, and no later batch of the pass carries it
again — the missing memo, MISSING_MEMO_S, this process), a zero row is
the platform's "0" sentinel, a priced row is the price. An answer this
adapter does not trust (a row with no instrumentId, more rows than asked,
an id that was not asked, no row at all for two ids or more, a shape the
parser does not know, a 4xx) is logged once with its keys, never a price,
and the batch is UNPROVEN for UNPROVEN_TTL_S in the shared cache: every
symbol takes the single read meanwhile (BatchUnproven).

THE BATCH WAITS FOR ITS MEASUREMENT (2026-11-02, review; MEASURED_FIRST):
the plan landed it "only after its demo measurement" (one call with two
ids, the row keys and their order recorded), and it was sent from the
first pass. Nothing is sent in batch now until the operator's
measurement, `manage.py etoro_rates_shape` (the demo key by default), has
read an answer the parser trusts and written its proof (prove, kept with
no expiry in the shared cache): every symbol takes the single read
meanwhile, as before the batch, the shared cache still serving the marks.
An answer the batch itself does not trust still turns it off for
UNPROVEN_TTL_S, proof or none.

A FAILED BATCH IS ONE REQUEST, AND ITS N FAILURES. A 429, a 5xx or a
transport failure of one batched GET is one request, noted on the
venue's health once per instrument it carried (EtoroTrader._read the
first, tickers the rest; 2026-11-02, review: it was noted ONCE, so a
failing venue was SICK three failed batches later than N rows read alone
made it, and the new real entries SICK holds went meanwhile): its
symbols answer BatchFailed, and the readers of this pass do not ask them
again one by one (the failure memo, FAILED_MEMO_S, this process). A budget refusal (etoro_budget.Refused:
nothing sent, never a failure) is kept the same way, for the readers at
its priority or below only (closed_for): a proposal's refusal never keeps
a mark, whose floor is lower, from asking.

THE SHARED CACHE, keyed (world, instrument id), kept CACHE_TTL_S (the
shut-market cadence's half hour), in Django's cache (Redis in
production): every rates answer writes it, single or batch — an answer
read at P0 or P1 through this process's writer thread, off its path (the
write queue, below). Each reader bounds the age it takes:

  the marks and the care (AssetBot.manage_positions)   MARK_MAX_AGE_S
  the same marks on a market the cadence holds shut     shut_max_age
  the proposals, the TAKE TRADE dialog's preview, the
  last look before an order, the order itself, the
  send's own previews, the kill switch, the CLOSE
  button, the pending-close mark (pending_closes) and
  the reconcile's orphan mark (reconcile_asset)         never: the wire

THE PROPOSALS AND THE DIALOG READ THE WIRE AGAIN (2026-11-02, review):
from 2026-11-01 the proposals past the clock were read off one batched
snapshot (30 s) and the TAKE TRADE dialog's preview off the cache (10 s).
A proposal's quote is its order's price (the stop, the target and the
size are built on it, and the last look can only refuse), and an order is
never priced from a cache or a batch snapshot; and a page shows what it
showed before the budget. The snapshot serves the marks alone.

A CACHED MARK NEVER ACTS ALONE (2026-11-01, review; AssetBot._confirm_mark):
a stop move (the mirror's retry of an unchanged lock included), a care
close or a change of the care's state decided on a mark read off the
cache is decided again on ONE fresh read of the wire at the row's own
priority first, judged by the mark sanity as the row's own read was
(against its state from before the cached print), so what such a send
carries is decided on the row's own read, as before the cache. A
proposal priced off the cache or a batch is never ordered on that price
alone: its last look fails closed (AssetBot.execute_entry); and since
2026-11-02 no proposal is priced so (above).

The plan let the pending-close mark and the orphan mark read it at 30 s;
they do not: both are P0, and a cache read on the drain's path between
two closes is a round trip a stalled cache could hold the next close
behind (engine/etoro_budget's rule: none on a P0 or P1 path).

A cached answer says so ("cached", its "age_s" and "read_at"), and
wherever one is booked or shown its age is recorded: the venue stamp is
dated at the read, and a close the manage tick books at it carries
exit_mark_cached_age_s (a proposal priced off it carried
proposal_quote_age_s, and the dialog's preview mark_cached_age_s, until
neither read it, 2026-11-02).

THE SHUT-MARKET CADENCE (shut_max_age). The live mark of a row whose stop
rests at eToro, on a market the exchange clock says is shut (the clock the
paper rows already use, core.exchange_status.market_clock), is read off
the newest answer received SINCE THE SHUT BEGAN while it is younger than
SHUT_EVERY_S: one read per half hour serves every row of it, whenever the
pass reaches the row, and every row is still marked and managed on the
shut market's own price every tick. Full cadence (MARK_MAX_AGE_S) from
SHUT_REOPEN_EARLY_S before the scheduled reopen. A row with no such answer
is read, batched with the walk's other rows — a row the batch left out,
a batch that failed or a read the budget refused counts nothing, and the
next tick asks again. Narrowed on review (2026-11-01) to the shuts whose
clock is the venue's: forex and commodity only (SHUT_CADENCE_CLASSES) —
crypto never shuts, an index CFD trades through the night its cash
session sleeps, and eToro trades US share CFDs out of the NYSE's session
(it filled one 22 minutes before the open, bot_program/entry_timing), so
stocks and ETFs keep full cadence; forex only while eToro's own 17:00 New
York week is shut too (ForexBot.forex_market_open — the FOREX row's UTC
hours shut an hour earlier from November to March); a commodity only on
a venue a table names (an unknown exchange reads CME by default: a clock
stated, never known); and only through a shut longer than SHUT_MIN_SPAN_S
(a weekend or a holiday, never a nightly or a daily break, which eToro's
own hours for a CFD may not keep). A missing, unknown or failing clock
means full cadence. Bounded: no mark is older than the half hour, and a
cached mark never acts alone (above).

CACHE, SHUT_CADENCE and MEASURED_FIRST are read at call time:
tests/__init__.py turns them off (the suite's fake wires count reads, and its rows run at whatever hour
the wall clock says); tests/test_etoro_rates_batch.py turns them on. Django
is imported inside the helpers, so the adapter that imports this stays
importable without it. Never a key: the failure and missing memos are
keyed by the budget's key hash.
"""
from __future__ import annotations

import collections
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone as dt_timezone

log = logging.getLogger(__name__)

#: The switches, read at call time (see the module docstring).
CACHE = True
SHUT_CADENCE = True
#: The batch waits for the operator's measurement (proven, below).
MEASURED_FIRST = True

#: THE SHUT-MARKET CADENCE: one read per SHUT_EVERY_S, full cadence from
#: SHUT_REOPEN_EARLY_S before the scheduled reopen, on these classes only,
#: through a shut longer than SHUT_MIN_SPAN_S only (the module docstring).
SHUT_EVERY_S = 30 * 60
SHUT_REOPEN_EARLY_S = 10 * 60
SHUT_MIN_SPAN_S = 24 * 3600
SHUT_CADENCE_CLASSES = frozenset({"forex", "commodity"})
#: How long a rates answer lives in the shared cache: the cadence's half
#: hour, the oldest any reader takes. Each reader bounds its own age.
CACHE_TTL_S = SHUT_EVERY_S
#: The oldest answer each reader takes (the table above). The proposals'
#: 30 s and the TAKE TRADE preview's 10 s went with their cache reads
#: (2026-11-02): both read the wire.
MARK_MAX_AGE_S = 30
#: A symbol answered more recently than this is not asked again by a batch.
PREFETCH_FRESH_S = 15
#: The most ids one batched GET carries. A GUESS, said as one: eToro's own
#: limit is unmeasured; 20 keeps one URL short and one bad answer small.
BATCH_MAX_IDS = 20
#: How long an untrusted answer keeps the batch unproven.
UNPROVEN_TTL_S = 24 * 3600
#: How long a failed or refused batch answers for its symbols, this process.
FAILED_MEMO_S = 30
#: How long a row a trusted batch left out is read alone, never batched
#: again, this process (2026-11-01, review).
MISSING_MEMO_S = 30

PREFIX = "etoro_rates"
UNPROVEN_KEY = f"{PREFIX}:batch_unproven"
#: The operator's measurement read an answer the parser trusts (prove).
PROVEN_KEY = f"{PREFIX}:batch_proven"


def _now() -> float:
    """The cache's clock: the wall clock every process reads alike (a
    seam: tests move it)."""
    return time.time()


def _mono() -> float:
    """The failure memo's clock (this process only; a seam)."""
    return time.monotonic()


def _cache():
    from django.core.cache import cache
    return cache


def _key(world, iid) -> str:
    return f"{PREFIX}:r:{world}:{int(iid)}"


def _iso(ts) -> str:
    try:
        return datetime.fromtimestamp(float(ts), tz=dt_timezone.utc
                                      ).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


# ── the answers a batch gives a symbol that is not a rate ───────────────

class RowMissing(LookupError):
    """A trusted batched answer carried no row for this symbol: its caller
    takes the single read (EtoroTrader.ticker), which keeps the three
    states, and no later batch of the pass carries it again (the missing
    memo, MISSING_MEMO_S)."""

    batch_fallback = True


class BatchUnproven(LookupError):
    """The batch is unproven (an untrusted answer within UNPROVEN_TTL_S,
    or this very answer): nothing more was asked in batch, and the symbol
    takes the single read."""

    batch_fallback = True


class BatchFailed(RuntimeError):
    """The batched GET carrying this symbol failed at the venue (a 429, a
    5xx after its retry, a transport failure): ONE request, noted on the
    venue's health once per instrument it carried, as the reads alone it
    replaced were (2026-11-02, review: once for all of them, so a failing
    venue needed three failed batches to be SICK where three rows read
    alone made it, and an entry SICK would hold could go). Its symbols
    are not asked again one by one."""

    def __init__(self, detail: str, n: int):
        super().__init__(
            f"the batched rates read failed ({detail}) — one request for "
            f"{int(n)} instrument{'s' if int(n) != 1 else ''}, noted once per "
            f"instrument on the venue's health")
        self.detail = detail


def final(answer) -> bool:
    """True when `answer` closes the symbol for this pass: a budget
    refusal (nothing sent) or a failed batch (one failure noted). A
    RowMissing, a BatchUnproven or any other error takes the single
    read."""
    return bool(getattr(answer, "budget_refused", False)) \
        or isinstance(answer, BatchFailed)


# ── the write queue: a P0 or P1 read writes nothing on its own path ─────
#
# NOT ONE CACHE ROUND TRIP ON A CLOSE'S OR AN ORDER'S PATH (2026-11-01,
# review; engine/etoro_budget's spend queue, the same rule): a rates answer
# read at P0 or P1 — the kill switch's and the drain's marks, the CLOSE
# button's, the last look before an order, a bare row's mark, a read no
# caller classified — is queued here with the instant it arrived, and this
# process's writer thread writes it to the cache (the shut-market cadence
# keeps no memo of its own: the answer is its memory, 2026-11-01, review).
# A stalled cache (a BGSAVE fork, an fsync, a frozen container) then holds
# none of them. A read at P2 to P5 (the marks, the proposals) writes on
# its own path, where the budget's take already reads the cache. Every
# reader of the cache drains this process's queue first (at most
# WRITE_WAIT_S of waiting), so a reader here is answered by every answer
# this process received. A write still queued when the process ends is
# lost: its reader asks the wire.

#: (the writer, its arguments), oldest first
_WRITES: collections.deque = collections.deque()
#: Held by whoever writes the queue (the writer thread, a reader, flush).
_WRITES_LOCK = threading.Lock()
_WRITE_WAKE = threading.Event()
#: This process's writer thread: {"pid", "thread"}.
_WRITER: dict = {}
_WRITER_START = threading.Lock()
#: The writer's sleep when nothing wakes it, in seconds.
WRITER_IDLE_S = 1.0
#: The most a reader waits for a drain another thread is in.
WRITE_WAIT_S = 0.5
#: The queue's bound: a writer stuck on a dead cache never grows a process
#: without end; a write past it is dropped (its reader asks the wire).
WRITES_MAX = 10_000


def _off_path() -> bool:
    """True inside a P0 or P1 scope of the budget, and outside every scope
    (a read no caller classified counts at P1)."""
    try:
        from bot_program.engine import etoro_budget
        return etoro_budget.current(etoro_budget.P1)[0] <= etoro_budget.P1
    except Exception:  # noqa: BLE001 — unreadable: never on the path
        return True


def _writer_loop() -> None:
    while True:
        _WRITE_WAKE.wait(WRITER_IDLE_S)
        _WRITE_WAKE.clear()
        _drain_writes()


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
                                         name="etoro-rates-writer")
                    _WRITER.update(pid=pid, thread=t)
                    t.start()
            finally:
                _WRITER_START.release()
    _WRITE_WAKE.set()


def _queue(fn, *args) -> None:
    """Leave one write for the writer thread. Never raises, never waits."""
    try:
        if len(_WRITES) >= WRITES_MAX:
            return
        _WRITES.append((fn, args))
        _wake_writer()
    except Exception:  # noqa: BLE001 — a lost write is a later read
        pass


def _drain_writes(wait=None) -> None:
    """Write everything this process queued. `wait`: the most to wait for
    a drain another thread is in; None waits as long as it takes. Never
    raises."""
    lock, queue = _WRITES_LOCK, _WRITES
    if not lock.acquire(timeout=-1 if wait is None else max(0.0, wait)):
        return
    try:
        while True:
            try:
                fn, args = queue.popleft()
            except IndexError:
                return
            try:
                fn(*args)
            except Exception:  # noqa: BLE001
                pass
    finally:
        lock.release()


def flush_writes() -> None:
    """Write everything this process queued, now (tests, a reader)."""
    _drain_writes(None)


def _after_fork_in_child() -> None:
    """A forked worker writes what IT reads: the parent's queue, locks and
    thread are the parent's."""
    global _WRITES, _WRITES_LOCK, _WRITE_WAKE, _WRITER_START
    _WRITES = collections.deque()
    _WRITES_LOCK = threading.Lock()
    _WRITE_WAKE = threading.Event()
    _WRITER_START = threading.Lock()
    _WRITER.clear()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_after_fork_in_child)


# ── the shared cache: every answer writes it ────────────────────────────

def _value(tick, at) -> "dict | None":
    if not isinstance(tick, dict):
        return None
    last = str(tick.get("lastPrice") or "0")
    try:
        if not float(last) >= 0:
            return None
    except (TypeError, ValueError):
        return None
    out = {"lastPrice": last, "at": float(at)}
    for side in ("bid", "ask"):
        if tick.get(side) is not None:
            out[side] = str(tick[side])
    return out


def _put_many_now(world, ticks: dict, at: float) -> None:
    try:
        values = {}
        for iid, tick in ticks.items():
            v = _value(tick, at)
            if v is not None:
                values[_key(world, iid)] = v
        if values:
            _cache().set_many(values, CACHE_TTL_S)
    except Exception as e:  # noqa: BLE001
        log.debug("eToro rates cache not written (%s)", type(e).__name__)


def put_many(world, ticks: dict, *, at=None) -> None:
    """Keep the answers {iid: ticker dict} of `world` for CACHE_TTL_S,
    dated `at` (the answer's arrival, default now): at P0 or P1 through
    the writer thread, off the read's path; else at once. Never raises:
    a lost write is a later read."""
    if not CACHE or not ticks:
        return
    at = _now() if at is None else float(at)
    if _off_path():
        _queue(_put_many_now, world, dict(ticks), at)
    else:
        _put_many_now(world, ticks, at)


def put(world, iid, tick, *, at=None) -> None:
    put_many(world, {iid: tick}, at=at)


def get(world, iid, *, symbol, max_age_s, now=None) -> "dict | None":
    """The answer `world` holds for `iid`, no older than `max_age_s`, as a
    ticker dict that says it is cached ({lastPrice, symbol[, bid, ask],
    "cached": True, "age_s", "read_at"}); None when none is, the switch is
    off, or the cache cannot be read. A "0" answer stays "0". Never
    raises."""
    if not CACHE or iid is None or not max_age_s or max_age_s <= 0:
        return None
    _drain_writes(WRITE_WAIT_S)
    try:
        held = _cache().get(_key(world, iid))
    except Exception:  # noqa: BLE001 — unreadable is a miss
        return None
    if not isinstance(held, dict):
        return None
    try:
        at = float(held.get("at"))
        last = str(held.get("lastPrice") or "0")
        float(last)
    except (TypeError, ValueError):
        return None
    now = _now() if now is None else float(now)
    age = now - at
    # a stamp from a host whose clock runs ahead is taken as now, a stamp
    # far ahead is not taken at all
    if age < -5.0 or age > float(max_age_s):
        return None
    tick = {"lastPrice": last, "symbol": symbol}
    for side in ("bid", "ask"):
        if held.get(side) is not None:
            tick[side] = str(held[side])
    tick.update(cached=True, age_s=round(max(0.0, age), 1),
                read_at=_iso(at))
    return tick


def cached(client, symbol, *, max_age_s) -> "dict | None":
    """`get` for `symbol` through `client`'s world and the id it can name
    without asking the wire. Never raises."""
    try:
        iid = client._known_id(symbol)
        if iid is None:
            return None
        return get(client._world(), iid, symbol=symbol, max_age_s=max_age_s)
    except Exception:  # noqa: BLE001
        return None


# ── the shut-market cadence: how old a shut market's mark may be ────────

def _clock_known(exchange, symbol) -> bool:
    """True when a table names the instrument's clock — a product session
    or a cash index by symbol, an exchange by its code or an alias
    (core.exchange_status.session_code_for's order) — and False for the
    class's default, a clock stated, never known (2026-11-01, review: the
    legacy sync writes 'ETORO', /setup/ writes '')."""
    from core import exchange_status as xs
    sym = str(symbol or "").strip().upper()
    if sym in xs.PRODUCT_SESSIONS or sym in xs.SYMBOL_VENUE:
        return True
    venue = str(exchange or "").strip().upper()
    return (venue in xs.SESSION_ALIASES
            or venue in {ex["code"] for ex in xs.EXCHANGES})


def _fx_venue_close(now):
    """The last Friday 17:00 New York at or before `now`, as an aware UTC
    datetime: the close of eToro's own FX week (ForexBot.forex_market_open's
    rule), which from November to March is 22:00 UTC, an hour after the
    FOREX row's."""
    from datetime import time as _time

    import pytz
    ny = pytz.timezone("America/New_York")
    local = now.astimezone(ny)
    friday = local.date() - timedelta(days=(local.weekday() - 4) % 7)
    close = ny.localize(datetime.combine(friday, _time(17, 0)))
    if close > local:
        close = ny.localize(datetime.combine(friday - timedelta(days=7),
                                             _time(17, 0)))
    return close.astimezone(dt_timezone.utc)


def shut_max_age(symbol, asset_class, *, now=None) -> int:
    """THE SHUT-MARKET CADENCE (the module docstring): the oldest answer,
    in seconds, the live mark of `symbol` may be read off this tick — at
    most SHUT_EVERY_S, and never one received before its market shut — or
    0 for full cadence (MARK_MAX_AGE_S, as on an open market). 0 for a
    class outside SHUT_CADENCE_CLASSES, a commodity whose venue no table
    names, forex while eToro's 17:00 New York week is open, a market the
    clock says is open, a shut whose start or reopen it cannot name, one
    shorter than SHUT_MIN_SPAN_S, the last SHUT_REOPEN_EARLY_S before the
    reopen, and any clock that cannot be read. Never raises."""
    if not SHUT_CADENCE:
        return 0
    try:
        from django.utils import timezone

        from core.exchange_status import market_clock
        from bot_program.engine.paper_trader import _instrument_key
        cls, exchange = _instrument_key(symbol, asset_class)
        cls = str(cls or "").strip().lower()
        if cls not in SHUT_CADENCE_CLASSES:
            return 0
        if cls == "commodity" and not _clock_known(exchange, symbol):
            return 0
        now = now or timezone.now()
        clock = market_clock(cls, exchange or "", symbol=symbol or "",
                             now_utc=now)
        if not clock.get("modelled") or clock.get("is_open", True):
            return 0
        reopens, closed = clock.get("reopens"), clock.get("closed")
        if reopens is None or closed is None:
            return 0
        if cls == "forex":
            # eToro's own week, Friday 17:00 to Sunday 17:00 New York: the
            # FOREX row's UTC hours shut an hour earlier in winter, an hour
            # the venue trades (and the care's weekend window runs in)
            from bot_program.asset_engine.forex_bot import forex_market_open
            if clock.get("session") != "FOREX" or forex_market_open(now):
                return 0
            closed = max(closed, _fx_venue_close(now))
        if (reopens - closed).total_seconds() < SHUT_MIN_SPAN_S:
            return 0                  # a nightly or a daily break
        if (reopens - now).total_seconds() <= SHUT_REOPEN_EARLY_S:
            return 0
        age = int(min(SHUT_EVERY_S, (now - closed).total_seconds()))
        return age if age > MARK_MAX_AGE_S else 0
    except Exception as e:  # noqa: BLE001 — a failing clock: full cadence
        log.debug("eToro rates: shut cadence unread for %s (%s)", symbol,
                  type(e).__name__)
        return 0


# ── the batch's trust ───────────────────────────────────────────────────

#: This process's copy of the unproven mark: kept when the cache cannot
#: hold it, so a cache down never re-enables an untrusted batch.
_UNPROVEN_HERE: dict = {}


def unproven(now=None) -> "dict | None":
    """{"at", "until", "why", "shape"} while the batch is unproven (the
    shared cache, or this process's copy), else None. Never raises."""
    now = _now() if now is None else float(now)
    try:
        if _UNPROVEN_HERE and now < float(_UNPROVEN_HERE.get("until", 0)):
            return dict(_UNPROVEN_HERE)
    except (TypeError, ValueError):
        pass
    try:
        held = _cache().get(UNPROVEN_KEY)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(held, dict):
        return None
    try:
        if now >= float(held.get("until", 0)):
            return None
    except (TypeError, ValueError):
        return None
    return held


def mark_unproven(why: str, shape: str) -> bool:
    """An answer this adapter does not trust: the batch is unproven for
    UNPROVEN_TTL_S, in the shared cache and in this process, and the
    answer is logged ONCE with its shape — the keys only, never a price,
    never an account figure. True when this call marked it (and logged).
    Never raises."""
    now = _now()
    value = {"at": now, "until": now + UNPROVEN_TTL_S,
             "why": str(why or "")[:200], "shape": str(shape or "")[:600]}
    try:
        first = bool(_cache().add(UNPROVEN_KEY, value, UNPROVEN_TTL_S))
    except Exception:  # noqa: BLE001 — the cache down: once per process
        first = not _UNPROVEN_HERE
    if first or not _UNPROVEN_HERE:
        _UNPROVEN_HERE.clear()
        _UNPROVEN_HERE.update(value)
    if first:
        log.warning("eToro batched rates: an answer this adapter does not "
                    "trust (%s; shape: %s) — the batch is unproven for %d h "
                    "and every symbol takes the single read meanwhile; "
                    "manage.py etoro_rates_shape measures it", value["why"],
                    value["shape"], UNPROVEN_TTL_S // 3600)
    return first


def proven() -> "dict | None":
    """{"at", "world", "shape"} once the operator's measurement (manage.py
    etoro_rates_shape) has read a batched answer the parser trusts, else
    None — and None when the cache cannot be read: the batch waits
    (2026-11-02). Never raises."""
    try:
        held = _cache().get(PROVEN_KEY)
    except Exception:  # noqa: BLE001 — unreadable: not proven
        return None
    return held if isinstance(held, dict) else None


def batch_waits() -> bool:
    """True while the batch waits for its measurement (MEASURED_FIRST and
    no proof)."""
    return bool(MEASURED_FIRST) and proven() is None


def prove(world: str, shape: str) -> bool:
    """The measurement's trusted answer: the batch may be sent from now on
    (an answer it does not trust still marks it unproven for a day). Kept
    with no expiry; the shape is the parser's words for the answer's keys,
    never a price or an id. True when written. Never raises."""
    try:
        _cache().set(PROVEN_KEY, {"at": _now(), "world": str(world or ""),
                                  "shape": str(shape or "")[:600]}, None)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("eToro batched rates: the measurement's proof could not "
                    "be written (%s) — the batch keeps waiting",
                    type(e).__name__)
        return False


def forget_proof() -> None:
    """Delete the proof (tests). Never raises."""
    try:
        _cache().delete(PROVEN_KEY)
    except Exception:  # noqa: BLE001
        pass


# ── this pass's failures: a failed batch is asked again by no reader ────

#: (key hash, world, SYMBOL) -> (_mono() at, the answer)
_FAILED: dict = {}
_FAILED_LOCK = threading.Lock()


def note_failure(kh, world, symbol, answer) -> None:
    now = _mono()
    with _FAILED_LOCK:
        for old in [k for k, v in _FAILED.items()
                    if now - v[0] > FAILED_MEMO_S]:
            _FAILED.pop(old, None)
        _FAILED[(kh, world, str(symbol).upper())] = (now, answer)


def failure(kh, world, symbol):
    """The failed batch's (or the refusal's) answer for `symbol` within
    FAILED_MEMO_S, else None."""
    key = (kh, world, str(symbol).upper())
    with _FAILED_LOCK:
        held = _FAILED.get(key)
        if held is None:
            return None
        if _mono() - held[0] > FAILED_MEMO_S:
            _FAILED.pop(key, None)
            return None
        return held[1]


#: (key hash, world, SYMBOL) -> _mono() at: a trusted batch left the row out
_MISSING: dict = {}


def note_missing(kh, world, symbol) -> None:
    """A trusted batch carried no row for `symbol` (RowMissing): its readers
    take the single read, and no batch carries it again for MISSING_MEMO_S
    (2026-11-01, review: each later row of a walk re-batched the rows the
    last batch had just left out, then read them alone)."""
    now = _mono()
    with _FAILED_LOCK:
        for old in [k for k, v in _MISSING.items()
                    if now - v > MISSING_MEMO_S]:
            _MISSING.pop(old, None)
        _MISSING[(kh, world, str(symbol).upper())] = now


def missing(kh, world, symbol) -> bool:
    """True while a trusted batch's RowMissing for `symbol` is younger than
    MISSING_MEMO_S."""
    key = (kh, world, str(symbol).upper())
    with _FAILED_LOCK:
        held = _MISSING.get(key)
        if held is None:
            return False
        if _mono() - held > MISSING_MEMO_S:
            _MISSING.pop(key, None)
            return False
        return True


def closed_for(kh, world, symbol):
    """The answer that closes `symbol` for the reader in the current budget
    scope, or None: a failed batch closes it for every reader (the venue
    failed, and one note was made); a budget refusal only for a reader at
    its priority or below — a proposal's refusal never closes a mark,
    whose floor is lower."""
    held = failure(kh, world, symbol)
    if held is None or not getattr(held, "budget_refused", False):
        return held
    from bot_program.engine import etoro_budget
    now_p = etoro_budget.current(etoro_budget.P1)[0]
    try:
        return held if now_p >= int(getattr(held, "priority", 0)) else None
    except (TypeError, ValueError):
        return None


def reset() -> None:
    """Forget this process's memory, its queued writes, the unproven mark
    and the measurement's proof (tests; the cache's entries go with
    cache.clear()). Waits for a drain in progress, so no write of a test
    lands in the next."""
    with _WRITES_LOCK:
        _WRITES.clear()
    with _FAILED_LOCK:
        _FAILED.clear()
        _MISSING.clear()
    _UNPROVEN_HERE.clear()
    try:
        _cache().delete(UNPROVEN_KEY)
    except Exception:  # noqa: BLE001
        pass
    forget_proof()


# ── the readers' one door ───────────────────────────────────────────────

def _etoro(client) -> bool:
    try:
        from bot_program.engine.capabilities import adapter_key
        return adapter_key(client) == "etoro" \
            and callable(getattr(client, "tickers", None))
    except Exception:  # noqa: BLE001
        return False


def _wanted(client, symbols, *, fresh_s, first=None) -> list:
    """The symbols of `symbols` a batch should carry: each once, its id
    nameable without the wire (a cold id is read by its own request, as
    before, so a batch never costs a /search), not answered within
    `fresh_s`, not closed by a failure this pass, not left out by a
    trusted batch this pass (its readers read it alone). `first`, when
    given, is carried whatever its cache says: its reader just missed."""
    world, kh = client._world(), client._bkey()
    out, seen = [], set()
    for s in ([first] if first else []) + list(symbols or []):
        key = str(s or "").upper()
        if not key or key in seen:
            continue
        seen.add(key)
        iid = client._known_id(key)
        if iid is None:
            continue
        if key != first:
            if get(world, iid, symbol=key, max_age_s=fresh_s) is not None:
                continue
            if closed_for(kh, world, key) is not None:
                continue
            if missing(kh, world, key):
                continue
        out.append(key)
    return out


def _remember(client, answers: dict) -> None:
    world, kh = client._world(), client._bkey()
    for s, a in (answers or {}).items():
        if isinstance(a, dict):
            continue
        if final(a):
            note_failure(kh, world, s, a)
        elif isinstance(a, RowMissing):
            note_missing(kh, world, s)


def prefetch(client, symbols, *, fresh_s=PREFETCH_FRESH_S) -> dict:
    """ONE batched read (chunks of BATCH_MAX_IDS) for the `symbols` an
    eToro `client` will be asked for this pass: {symbol: answer} for those
    it asked (a ticker dict, or the exception for that symbol), {} when
    nothing needed asking or the switch is off. At the caller's priority
    in the budget. Never raises."""
    if not CACHE or not _etoro(client):
        return {}
    try:
        ask = _wanted(client, symbols, fresh_s=fresh_s)
        if not ask:
            return {}
        got = client.tickers(ask)
        _remember(client, got)
        return got
    except Exception as e:  # noqa: BLE001 — a prefetch never costs a pass
        log.warning("eToro rates: the batched prefetch failed (%s) — each "
                    "reader asks for itself", type(e).__name__)
        return {}


def quote(client, symbol, *, max_age_s, refill=None) -> dict:
    """The rate of `symbol` for a reader that may take an answer up to
    `max_age_s` old (the table in the module docstring). Through a client
    that is not eToro's, with the switch off, or for a reader that takes
    no cached answer (`max_age_s` 0): `client.ticker(symbol)`, exactly as
    before.

    The shared cache first. On a miss, a reader of a pass (`refill`: the
    other symbols of its pass, or a callable answering them) is answered
    by its pass's batch: a failure of that batch within FAILED_MEMO_S is
    raised (nothing asked again, no second health note), and so is a
    refusal, for a reader at its priority or below (closed_for); else ONE
    batched GET carries this symbol and up to BATCH_MAX_IDS - 1 of the
    others (its answer says "batched"). A row missing from it — or from any trusted batch
    of the pass (the missing memo) —, an unproven batch, a cold id and
    every reader without a pass take the single read. Raises what the
    single read raises."""
    if not CACHE or not max_age_s or max_age_s <= 0 or not _etoro(client):
        return client.ticker(symbol)
    key = str(symbol or "").upper()
    hit = cached(client, key, max_age_s=max_age_s)
    if hit is not None:
        hit["symbol"] = symbol
        return hit
    if refill is not None and client._known_id(key) is not None:
        kh, world = client._bkey(), client._world()
        held = closed_for(kh, world, key)
        if held is not None:
            raise held
        if not missing(kh, world, key):
            others = refill() if callable(refill) else refill
            ask = _wanted(client, others, fresh_s=PREFETCH_FRESH_S,
                          first=key)
            if len(ask) > 1:
                got = client.tickers(ask[:BATCH_MAX_IDS])
                _remember(client, got)
                answer = got.get(key)
                if isinstance(answer, dict):
                    answer["symbol"] = symbol
                    answer["batched"] = True
                    return answer
                if answer is not None and final(answer):
                    raise answer
    return client.ticker(symbol)
