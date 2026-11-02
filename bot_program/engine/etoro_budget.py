"""THE eTORO REQUEST BUDGET (2026-11-01): one budget per USER KEY, shared by
every process, with priorities, and the 429 pause beside it.

eToro meters the public API per user key, and one key opens both worlds
(MEASURED 2026-09-23: the pair saved with Demo ticked answered 200 on the
live world too), so the demo and the live world spend ONE budget. Until
today nothing counted: the marks, the proposals and the bar refresh shared
the key's market-data quota unpaced, the bar refresh yielded only AFTER the
trading lane had met a 429, and the 429 pause lived in one process's
memory, so the worker that met a 429 paused while the next one asked again.

FOUR FAMILIES, one window each per key and per minute (WINDOW_S):

  market      rates, /search, candles
  account     aggregate-portfolio, portfolio, pnl, eligibility
  execution   the order POST, the close POST, the PATCH, the DELETE
  lookups     orders:lookup: fill polls, close proofs, the cancel's proof

SIX PRIORITIES. Every request is taken at the priority its caller set with
`at()` (a context manager, or `scoped()` as a decorator); a scope never
lowers an outer one, and a request no caller classified counts at P1:

  P0  closes, stop and target moves, close proofs, order cancels, the
      pending-close drain, the kill switch, the CLOSE button
  P1  orders, their last look, their fill lookups, the TAKE TRADE ticket,
      and the mark of a live row eToro holds NO stop for (its bot-side
      stop is the only one it has: AssetBot.manage_positions)
  P2  account reads: the sync, the re-read, the reconcile, the pool check,
      the /brokers/ key probe, Telegram /status, the digests
  P3  marks of the rows whose stop rests at eToro (the manage tick)
  P4  proposals
  P5  candles, the Orcs' tape, etoro_smoke, etoro_candle_headroom

P0 AND P1 ARE NEVER REFUSED, NEVER DELAYED, NEVER QUEUED: the request goes
at once. It is counted AFTER it is sent (`spend`), and off its path: a
spend only queues the COUNT for this process's flusher thread (the spend
queue, below), so not one cache round trip stands between a close and
the wire, between a close and its proofs, or between two closes of the
kill switch. A family they take past its rate logs its overrun once per
window. The shared pause a P0 read's 429 grants goes through the same
queue (`later`, 2026-11-02, review): it was a read and a write of the
cache on that read's thread, before the next close. P2 to P5 are taken
BEFORE (`take`): a take is
granted only while the family keeps its floor (FLOOR_P2 .. FLOOR_P5 of its
rate) for the priorities above, and P3 to P5 also skip while the shared
429 pause holds for that key and world. A refused take sends nothing and
raises `Refused`, whose words the caller files in its own skip vocabulary;
it is never a venue failure: never noted on the venue's health (so never
SICK), never a mute of a feed, never a failed row, never an alarm.

ATOMIC ACROSS PROCESSES: cache.add then cache.incr on one key per (key
hash, family, second) — Redis' INCR in production (config/settings.py
CACHES), LocMemCache's lock in the suite. A take refused after its
increment gives the token back (cache.decr); in that instant a take at a
higher limit may read one token too many and be refused, the safe way
round.

A ROLLING MINUTE (2026-11-02, review), not a fixed one: a take is judged
on every request of its family sent in the last WINDOW_S seconds, read in
one GET of the minute's SLOT_S slots (get_many, Redis' MGET). Fixed
windows let a family spend its rate on both sides of a minute's edge,
twice its rate inside one rolling minute — the 429 the budget is there to
spare. A request counts 60 to 61 s after it was sent, so no rolling minute
holds more than a priority's limit, and the family's rate is still spent
minute after minute. The plan's token bucket with an atomic Lua take is
not used: Django's cache API (Redis in production, LocMem in the suite)
runs no script, and these INCRs bound what the bucket bounds. The minute
windows name the command's report and the overruns' once-a-window line.

THE CACHE UNREACHABLE: P0 and P1 go through unbudgeted and that is logged
once per window per process (by the flusher, which meets the failure);
P2 to P5 are not asked until it answers.

THE KEY IS NEVER STORED, LOGGED OR PRINTED: the budget, the pause and the
registry the command reads are keyed by `key_hash`, twelve hex characters
of a SHA-256 of the user key.

Django is imported inside the helpers, so the adapter that imports this
stays importable without it. BUDGET is read at call time:
tests/__init__.py turns it off for the suite, tests/test_etoro_budget.py
turns it on.
"""
from __future__ import annotations

import collections
import contextlib
import contextvars
import functools
import hashlib
import logging
import math
import os
import threading
import time

log = logging.getLogger(__name__)

# ── the priorities ──────────────────────────────────────────────────────
P0, P1, P2, P3, P4, P5 = 0, 1, 2, 3, 4, 5
PRIORITIES = (P0, P1, P2, P3, P4, P5)
PRIORITY_NAMES = {P0: "P0 close", P1: "P1 order", P2: "P2 account",
                  P3: "P3 mark", P4: "P4 proposal", P5: "P5 candles"}

# ── the families ────────────────────────────────────────────────────────
MARKET, ACCOUNT, EXECUTION, LOOKUPS = "market", "account", "execution", \
    "lookups"
FAMILIES = (MARKET, ACCOUNT, EXECUTION, LOOKUPS)
#: The family of each request site the adapter names (EtoroTrader._read's
#: `where`, and the writes and lookups it sends itself). A site this map
#: does not know is market data. "rates" is the batched rates read
#: (2026-11-01, EtoroTrader.tickers): one token a request, whatever the
#: number of ids it carries.
FAMILY_OF = {"ticker": MARKET, "rates": MARKET, "search": MARKET,
             "candles": MARKET,
             "account": ACCOUNT, "portfolio": ACCOUNT, "pnl": ACCOUNT,
             "eligibility": ACCOUNT, "probe": ACCOUNT,
             "order": EXECUTION, "close": EXECUTION, "patch": EXECUTION,
             "cancel": EXECUTION, "lookup": LOOKUPS}

#: THE START RATES, per user key, per family, per minute. GUESSES, said as
#: guesses: eToro's quota is written nowhere this tree has read (deploy/
#: ETORO_DEPARTURE.md §7, "STILL UNMEASURED"); the public reference is
#: quoted two ways (120 per 60 s across the market-data endpoints, or 60 a
#: minute for GETs), and the lookups' 20 per 60 s was "not hit at <= 18".
#: Replace each with what the quota headers say: _on_429 logs them on
#: every 429 and the bar refresh once a pass ("[bars] eToro's quota
#: headers on a candle answer").
RATE_MARKET_PER_MIN = 60
RATE_ACCOUNT_PER_MIN = 30
RATE_EXECUTION_PER_MIN = 20
RATE_LOOKUPS_PER_MIN = 18

#: THE FLOORS: the share of a family's rate a take below P1 must leave
#: untaken for the priorities above it (rounded up to whole tokens). At
#: the start rates, on market data: a mark leaves 6 of 60 for the last
#: looks, the drain's and the kill switch's marks; a proposal leaves 24,
#: so the marks keep 18 tokens a minute no proposal can take; the candles
#: leave 30, so P5 never takes more than half the family. On the account
#: family P2 leaves 2 of 30 for the drain's book reads and the entry's
#: eligibility reads. P0 and P1 have none: they are never refused.
#: FLOOR_P4 WAS 0.20 UNTIL REVIEW (2026-11-01): the fleet tick manages
#: then proposes one config at a time, so when the bar pass already held
#: its half of a minute, an earlier config's proposals could leave a later
#: config's marks 6 tokens, and its rows were clock-managed for the tick:
#: entries asked while the care of open rows waited. At 0.40 the marks
#: keep 18 tokens over the proposals; it only defers entries.
FLOOR_P2 = 0.05
FLOOR_P3 = 0.10
FLOOR_P4 = 0.40
FLOOR_P5 = 0.50

#: One window per minute, aligned on the epoch minute: the length of the
#: rolling minute a take is judged on, and the minutes the command reports.
WINDOW_S = 60
#: THE ROLLING MINUTE'S SLOTS (2026-11-02): each request is counted in the
#: second it was sent, and a take reads the slots of the last WINDOW_S
#: seconds (a request counts 60 to 61 s, the safe way round).
SLOT_S = 1
#: How long a window's counters stay readable: this one and the one before
#: for the command, with a minute to spare.
KEEP_S = 3 * WINDOW_S
#: The switch, read at call time (tests/__init__.py turns it off).
BUDGET = True

PREFIX = "etoro_budget"
#: {key hash: epoch seconds last seen} — what the read-only command lists.
REGISTRY_KEY = f"{PREFIX}:keys"
REGISTRY_TTL_S = 2 * 86400

#: Refusal reasons, as stored and printed.
FLOOR, PAUSE, CACHE = "floor", "pause", "cache"
REASONS = (FLOOR, PAUSE, CACHE)


def _now() -> float:
    """The budget's and the shared pause's clock: the wall clock, which
    every process and host reads alike (a seam: tests move it)."""
    return time.time()


def _cache():
    from django.core.cache import cache
    return cache


def key_hash(user_key) -> str:
    """Twelve hex characters standing for a user key in every cache key,
    log line and printout of the budget. Never the key."""
    raw = "" if user_key is None else str(user_key)
    return hashlib.sha256(b"etoro-budget\x00"
                          + raw.encode("utf-8")).hexdigest()[:12]


def family_of(where: str) -> str:
    return FAMILY_OF.get(str(where or ""), MARKET)


def rate(family: str) -> int:
    """The family's tokens per window, read at call time."""
    return int({MARKET: RATE_MARKET_PER_MIN, ACCOUNT: RATE_ACCOUNT_PER_MIN,
                EXECUTION: RATE_EXECUTION_PER_MIN,
                LOOKUPS: RATE_LOOKUPS_PER_MIN}.get(family,
                                                   RATE_MARKET_PER_MIN))


def floor_tokens(family: str, priority: int) -> int:
    """The tokens a take at `priority` must leave in `family`'s window."""
    share = {P2: FLOOR_P2, P3: FLOOR_P3, P4: FLOOR_P4,
             P5: FLOOR_P5}.get(int(priority), 0.0)
    return int(math.ceil(rate(family) * float(share) - 1e-9))


def limit(family: str, priority: int) -> int:
    """The most takes `family`'s window may hold for a take at `priority`
    to be granted (the rate itself for P0 and P1, which are counted past
    it)."""
    return rate(family) - floor_tokens(family, priority)


def window(now=None) -> int:
    return int((_now() if now is None else float(now)) // WINDOW_S)


def window_left_s(now=None) -> float:
    """Seconds until the current window ends."""
    now = _now() if now is None else float(now)
    return max(0.0, (window(now) + 1) * WINDOW_S - now)


# ── the scope: the caller's priority ────────────────────────────────────

_SCOPE: contextvars.ContextVar = contextvars.ContextVar(
    "etoro_budget_scope", default=None)


@contextlib.contextmanager
def at(priority: int, why: str = ""):
    """Every eToro request inside is taken at `priority` (and named `why`
    in the budget's lines) — unless an outer scope is more urgent: a scope
    never lowers one, so a mark read inside the kill switch stays P0 and a
    close sent inside the manage tick's P3 is P0 (the close sets its own).
    Per thread and per context."""
    p = int(priority)
    outer = _SCOPE.get()
    inner = outer if outer is not None and outer[0] <= p else (
        p, str(why or ""))
    token = _SCOPE.set(inner)
    try:
        yield inner[0]
    finally:
        _SCOPE.reset(token)


def scoped(priority: int, why: str = ""):
    """`at(priority, why)` around a whole function, as a decorator."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            with at(priority, why):
                return fn(*args, **kwargs)
        return wrapper
    return deco


def current(default: int = P1) -> tuple:
    """(priority, why) of the innermost scope, or (default, "") outside
    every scope."""
    held = _SCOPE.get()
    return (held[0], held[1]) if held is not None else (int(default), "")


# ── the refusal ─────────────────────────────────────────────────────────

class Refused(Exception):
    """A take the budget refused: NOTHING WAS SENT. Not the venue's
    failure: read duck-typed (`budget_refused`) by every caller that files
    it as a skip — the mark (clock-managed this tick, its last stamp kept),
    the proposal (a NO_PRICE skip), the bar refresh (the public feed, no
    mute), the sync (deferred, not a miss)."""

    budget_refused = True

    def __init__(self, family: str, priority: int, reason: str, why: str):
        super().__init__(f"{why} — not asked")
        self.family = family
        self.priority = int(priority)
        self.reason = reason
        #: the words without their "— not asked" tail, for a caller that
        #: says "not asked" in its own sentence (the mark's skip)
        self.why = why


def _words(reason, family, priority, *, n=None, left=None, world="",
           error="") -> str:
    """Why a take was refused, LEADING with the budget (skips.record keeps
    200 characters and why_no_trade prints 88). No figure but token
    counts."""
    name = PRIORITY_NAMES.get(int(priority), f"P{priority}")
    if reason == PAUSE:
        return (f"eToro budget: the 429 pause holds ({world or '?'}, "
                f"{float(left or 0):.0f}s left; {name})")
    if reason == CACHE:
        return (f"eToro budget: its cache is unreachable ({error or '?'}; "
                f"{name})")
    return (f"eToro budget: {family} {int(n or 0)}/{rate(family)} this "
            f"minute, {floor_tokens(family, priority)} kept for higher "
            f"priorities ({name})")


# ── the keys ────────────────────────────────────────────────────────────

def _n_key(kh, family, win) -> str:
    """The family's count in a minute window: what the command reports.
    Takes are judged on the rolling minute (_s_key) since 2026-11-02."""
    return f"{PREFIX}:n:{kh}:{family}:{win}"


def _s_key(kh, family, slot) -> str:
    """The family's count in one SLOT_S slot: what the rolling minute a
    take is judged on adds up (2026-11-02)."""
    return f"{PREFIX}:s:{kh}:{family}:{slot}"


def _slot(now) -> int:
    return int(math.floor(float(now) / SLOT_S))


def _slot_keys(kh, family, now) -> list:
    """The slots of the rolling minute ending at `now`, oldest first: every
    request of the family sent within the last WINDOW_S seconds is counted
    in one of them (and one sent up to SLOT_S earlier may be, the safe way
    round)."""
    first, last = _slot(float(now) - WINDOW_S), _slot(now)
    return [_s_key(kh, family, s) for s in range(first, last + 1)]


def _rolled(c, keys) -> tuple:
    """(the count of every slot of `keys` but the last, the last one's), in
    one get_many. Raises what the cache raises."""
    got = c.get_many(keys) or {}

    def n(key):
        try:
            return int(got.get(key) or 0)
        except (TypeError, ValueError):
            return 0
    return sum(n(k) for k in keys[:-1]), n(keys[-1])


def rolling(kh: str, family: str, now=None) -> int:
    """The requests of `family` the rolling minute ending at `now` holds
    for key hash `kh`: what a take is judged on. 0 when the cache cannot be
    read. Never raises."""
    try:
        past, here = _rolled(_cache(), _slot_keys(
            kh, family, _now() if now is None else now))
        return past + here
    except Exception:  # noqa: BLE001
        return 0


def _p_key(kh, family, win, p) -> str:
    """Takes granted (or counted) at one priority in a window."""
    return f"{PREFIX}:p:{kh}:{family}:{win}:{int(p)}"


def _r_key(kh, family, win, p, reason) -> str:
    """Refusals at one priority, for one reason, in a window."""
    return f"{PREFIX}:r:{kh}:{family}:{win}:{int(p)}:{reason}"


def _w_key(kh, family, win, p) -> str:
    """The last refusal's words at one priority in a window."""
    return f"{PREFIX}:w:{kh}:{family}:{win}:{int(p)}"


def _o_key(kh, family, win) -> str:
    """P0 and P1 requests past the family's rate in a window."""
    return f"{PREFIX}:o:{kh}:{family}:{win}"


def _once_key(kh, family, win, what) -> str:
    """Set once a window's line for `what` was logged."""
    return f"{PREFIX}:once:{kh}:{family}:{win}:{what}"


def _pause_key(kh, world) -> str:
    return f"{PREFIX}:pause:{kh}:{world}"


def _incr(c, key) -> int:
    """Atomic count: create at 0 if absent, then INCR."""
    c.add(key, 0, KEEP_S)
    try:
        return int(c.incr(key))
    except ValueError:                 # gone between the add and the incr
        c.add(key, 0, KEEP_S)
        return int(c.incr(key))


# ── process-local memory: what this process already said ────────────────

#: key hash -> the window this process last registered it in.
_NOTED: dict = {}
#: The (window, sent) pairs this process logged "the cache is
#: unreachable" for: once for what it sent unbudgeted, once for what it
#: did not ask.
_DOWN_SAID: set = set()
#: Requests this process sent unbudgeted because the cache was unreachable
#: ({priority: count}): the record of a fail-open, beside its log line.
UNBUDGETED: dict = {}
#: The pause keys this process wrote (or a test seeded): the suite deletes
#: them (forget_pauses) — LocMem is kept across tests in one process.
_PAUSE_KEYS: set = set()

# ── the spend queue: P0 and P1 counted off the request path ─────────────
#
# NOT ONE CACHE ROUND TRIP ON A REQUEST'S PATH (2026-11-01, review). A
# spend used to count in the caller's thread, in the `finally` right after
# its request was sent and BEFORE its answer was read: six cache round
# trips a request (Django's RedisCache.incr is EXISTS then INCRBY), eight
# on a process's first of a window — between a close POST and its proofs,
# between the proofs, and between two closes of the kill switch or the
# drain. A cache that stalls (the fork of a BGSAVE, an fsync, a frozen
# container) held them as long as redis-py's socket timeout: 5 s on 8.x,
# none at all on the 5.x to 7.x the requirements allow. A spend now only
# APPENDS to this process's queue and wakes its flusher thread, which does
# the counting; every take (P2 to P5, off any P0 path) drains the queue
# first, in its own thread, so it is judged on every request this process
# sent. A count still queued when the process ends is lost: the rates are
# guesses, and a lost count only ever leaves a lower priority one token
# more, never a P0 or P1 request refused.

#: (key hash, family, priority, where, why, the instant it was sent)
_SPENT: collections.deque = collections.deque()
#: Held by whoever counts the queue (the flusher, a take, flush()): a
#: drain that returns has counted everything queued before it began.
_DRAIN = threading.Lock()
#: Set by every spend; the flusher waits on it.
_WAKE = threading.Event()
#: This process's flusher: {"pid", "thread"}.
_FLUSHER: dict = {}
_FLUSHER_START = threading.Lock()
#: The flusher's sleep when no spend wakes it, in seconds.
FLUSH_IDLE_S = 1.0
#: The most a take waits for a drain another thread is in (a stalled
#: cache) before it is judged on what the cache already holds.
DRAIN_WAIT_S = 0.5
#: The queue's bound: a flusher stuck on a dead cache never grows a
#: process without end; a spend past it is dropped and counted here,
#: {priority: count}, beside UNBUDGETED.
SPENT_MAX = 10_000
DROPPED: dict = {}
#: OTHER CACHE WORK A P0 REQUEST LEAVES BEHIND (2026-11-02, review): the
#: shared 429 pause a P0 read's 429 grants (etoro_client._on_429), queued
#: as (fn, args) for the same flusher and drained with the counts, so no
#: grant stands between that answer and the next close (`later`).
_LATER: collections.deque = collections.deque()


def _flush_loop() -> None:
    """The flusher thread: count the queue whenever a spend wakes it, and
    at least once every FLUSH_IDLE_S."""
    while True:
        _WAKE.wait(FLUSH_IDLE_S)
        _WAKE.clear()
        _drain()


def _wake_flusher() -> None:
    """Start this process's flusher if none runs, then wake it. Never
    waits on a lock: a start another thread is making is left to it, and
    the queue is drained by the next take or the next wake."""
    pid = os.getpid()
    held = _FLUSHER.get("thread")
    if held is None or _FLUSHER.get("pid") != pid or not held.is_alive():
        if _FLUSHER_START.acquire(blocking=False):
            try:
                held = _FLUSHER.get("thread")
                if held is None or _FLUSHER.get("pid") != pid \
                        or not held.is_alive():
                    t = threading.Thread(target=_flush_loop, daemon=True,
                                         name="etoro-budget-flusher")
                    _FLUSHER.update(pid=pid, thread=t)
                    t.start()
            finally:
                _FLUSHER_START.release()
    _WAKE.set()


def _drain(wait=None) -> None:
    """Count every request this process queued (`spend`). `wait`: the most
    to wait, in seconds, for a drain another thread is in; None waits as
    long as it takes. Never raises."""
    # bound here: a fork rebinds them in the child, and a lock is released
    # by whoever took that very lock
    lock, queue, later_q = _DRAIN, _SPENT, _LATER
    if not lock.acquire(timeout=-1 if wait is None else max(0.0, wait)):
        return
    try:
        while True:
            try:
                item = queue.popleft()
            except IndexError:
                break
            _count(*item)
        while True:
            try:
                fn, args = later_q.popleft()
            except IndexError:
                return
            try:
                fn(*args)
            except Exception:  # noqa: BLE001 — off every path, never raises
                pass
    finally:
        lock.release()


def flush() -> None:
    """Count every request this process queued, now, waiting for a drain
    in progress: what the read-only report and the tests read after.
    Never raises."""
    _drain(None)


def _after_fork_in_child() -> None:
    """A forked child (a Celery or gunicorn worker) counts what IT sends:
    its parent's queue is the parent's, and so are its locks (one held at
    the fork would never be released here) and its flusher thread (which
    does not exist here)."""
    global _SPENT, _DRAIN, _WAKE, _FLUSHER_START, _LATER
    _SPENT = collections.deque()
    _LATER = collections.deque()
    _DRAIN = threading.Lock()
    _WAKE = threading.Event()
    _FLUSHER_START = threading.Lock()
    _FLUSHER.clear()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_after_fork_in_child)


def _note_key(c, kh, win) -> None:
    """Register `kh` for the read-only command, at most once a window per
    process. Never raises."""
    if _NOTED.get(kh) == win:
        return
    try:
        seen = c.get(REGISTRY_KEY)
        seen = dict(seen) if isinstance(seen, dict) else {}
        now = _now()
        seen[kh] = now
        seen = {k: v for k, v in seen.items()
                if isinstance(v, (int, float)) and now - v < REGISTRY_TTL_S}
        c.set(REGISTRY_KEY, seen, REGISTRY_TTL_S)
        _NOTED[kh] = win
    except Exception:  # noqa: BLE001 — the registry is the command's only
        pass


def _cache_down(kh, priority, where, error, *, sent: bool) -> None:
    """The cache did not answer: a request sent unbudgeted (P0, P1) and a
    request not asked (P2 to P5) are each said once a window per process,
    and every one sent is counted in UNBUDGETED. Never raises."""
    try:
        if sent:
            UNBUDGETED[int(priority)] = UNBUDGETED.get(int(priority), 0) + 1
        win = window()
        said = (win, bool(sent))
        if said in _DOWN_SAID:
            return
        for old in [s for s in _DOWN_SAID if s[0] != win]:
            _DOWN_SAID.discard(old)
        _DOWN_SAID.add(said)
        log.warning("eToro budget [%s]: its cache is unreachable (%s) — %s "
                    "at %s %s; P0 and P1 go through unbudgeted, P2 to P5 "
                    "are not asked until it answers", kh,
                    type(error).__name__,
                    PRIORITY_NAMES.get(int(priority), priority),
                    where or "?", "sent unbudgeted" if sent else "not asked")
    except Exception:  # noqa: BLE001
        pass


# ── the take (P2 to P5) and the spend (P0, P1, every retry) ─────────────

def take(kh: str, family: str, priority: int, *, world: str = "",
         where: str = "", why: str = "", pause: bool = True) -> None:
    """Take one token of `family` for a request at `priority`, BEFORE it is
    sent; returns when granted, raises Refused (nothing to send) when not.

    For P2 to P5 only: P0 and P1 are counted after their send (`spend`)
    and return here at once. P3 to P5 skip while the shared 429 pause of
    (kh, world) holds (`pause` False skips that read: the adapter's
    RATE_PAUSE off). Every cache failure is a refusal here: a budget that
    cannot be read sends nothing below P1. The spend queue is drained
    first (at most DRAIN_WAIT_S of waiting), so the take is judged on
    every request this process sent."""
    p = int(priority)
    if not BUDGET or p <= P1:
        return
    _drain(DRAIN_WAIT_S)
    now = _now()
    win = window(now)
    try:
        c = _cache()
        if pause and p >= P3:
            left = _pause_left(c, kh, world, now)
            if left > 0:
                raise _refused(c, kh, family, p, win, PAUSE, where=where,
                               why=why, left=left, world=world)
        cap = limit(family, p)
        # THE ROLLING MINUTE (2026-11-02): every request of the family sent
        # in the last WINDOW_S seconds, this second's slot last
        keys = _slot_keys(kh, family, now)
        past, here = _rolled(c, keys)
        if past + here >= cap:
            raise _refused(c, kh, family, p, win, FLOOR, n=past + here,
                           where=where, why=why)
        n = past + _incr(c, keys[-1])
        if n > cap:
            try:
                c.decr(keys[-1])
            except Exception:  # noqa: BLE001 — a token lost is a refusal more
                pass
            raise _refused(c, kh, family, p, win, FLOOR, n=n - 1,
                           where=where, why=why)
        try:
            _incr(c, _n_key(kh, family, win))
            _incr(c, _p_key(kh, family, win, p))
        except Exception:  # noqa: BLE001 — the stats are the command's only
            pass
        _note_key(c, kh, win)
    except Refused:
        raise
    except Exception as e:  # noqa: BLE001 — the cache is unreachable
        _cache_down(kh, p, where, e, sent=False)
        raise Refused(family, p, CACHE,
                      _words(CACHE, family, p, error=type(e).__name__)) \
            from None


def _refused(c, kh, family, p, win, reason, *, n=None, left=None,
             world="", where="", why="") -> Refused:
    """The Refused to raise, its count and words stored and its line
    logged once a window per (priority, reason). Never raises itself."""
    words = _words(reason, family, p, n=n, left=left, world=world)
    try:
        _incr(c, _r_key(kh, family, win, p, reason))
        c.set(_w_key(kh, family, win, p), words, KEEP_S)
        if c.add(_once_key(kh, family, win, f"r{p}{reason}"), 1, KEEP_S):
            log.info("eToro budget [%s]: %s (%s%s)", kh, words,
                     where or "?", f", {why}" if why else "")
    except Exception:  # noqa: BLE001 — the refusal stands without its stats
        pass
    return Refused(family, p, reason, words)


def spend(kh: str, family: str, priority: int, *, where: str = "",
          why: str = "") -> None:
    """Count one request ALREADY SENT: every P0 and P1 request, and the one
    bounded retry of any read (the read was granted; its retry belongs to
    it). Never refuses, never raises, never waits: the count is QUEUED,
    with the instant it was sent, for this process's flusher thread (the
    spend queue, above), so no cache call stands on the request's path.
    A family taken past its rate logs the overrun once per window: P0 and
    P1 go over budget, never wait."""
    if not BUDGET:
        return
    try:
        p = int(priority)
        if len(_SPENT) >= SPENT_MAX:
            DROPPED[p] = DROPPED.get(p, 0) + 1
            return
        _SPENT.append((kh, family, p, where, why, _now()))
        _wake_flusher()
    except Exception:  # noqa: BLE001 — a count never costs a request
        pass


def later(fn, *args) -> None:
    """Run `fn(*args)` OFF the calling request's path (2026-11-02, review):
    queued for this process's flusher thread, as a spend's count is, and
    run by every drain (the flusher, a take, flush()), so no cache round
    trip stands between a P0 answer and the next close. For the shared
    429 pause a P0 read's 429 grants (etoro_client._on_429), whatever
    BUDGET says: the pause has its own switch. Never raises, never
    waits."""
    try:
        if len(_LATER) >= SPENT_MAX:
            return
        _LATER.append((fn, args))
        _wake_flusher()
    except Exception:  # noqa: BLE001 — a lost grant is a later 429
        pass


def _count(kh, family, p, where, why, at) -> None:
    """Count one queued request in the second and the window it was SENT
    in: the rolling minute's slot, the family's minute count, its
    priority's, the overrun (the rolling minute past the family's rate,
    2026-11-02) logged once a window, the key registered. Off every
    request's path (the flusher, a take's drain, flush()). Never
    raises."""
    try:
        c = _cache()
        win = window(at)
        keys = _slot_keys(kh, family, at)
        _incr(c, keys[-1])
        try:
            _incr(c, _n_key(kh, family, win))
            _incr(c, _p_key(kh, family, win, p))
        except Exception:  # noqa: BLE001
            pass
        r = rate(family)
        n = 0
        if p <= P1:
            past, here = _rolled(c, keys)
            n = past + here
        if n > r and p <= P1:
            try:
                _incr(c, _o_key(kh, family, win))
                if c.add(_once_key(kh, family, win, "over"), 1, KEEP_S):
                    log.warning(
                        "eToro budget [%s]: %s over its %d a minute (%d "
                        "this minute) — %s at %s%s sent anyway: P0 and P1 "
                        "are never refused", kh, family, r, n,
                        PRIORITY_NAMES.get(p, p), where or "?",
                        f" ({why})" if why else "")
            except Exception:  # noqa: BLE001
                pass
        _note_key(c, kh, win)
    except Exception as e:  # noqa: BLE001 — sent, and counted nowhere
        _cache_down(kh, p, where, e, sent=True)


# ── the shared 429 pause ────────────────────────────────────────────────

def _pause_left(c, kh, world, now) -> float:
    held = c.get(_pause_key(kh, world))
    if not isinstance(held, dict):
        return 0.0
    try:
        return max(0.0, float(held.get("end")) - float(now))
    except (TypeError, ValueError):
        return 0.0


def pause_left(kh: str, world: str, now=None) -> float:
    """Seconds left of the shared 429 pause of (kh, world); 0.0 when none
    holds or the cache cannot be read. Never raises."""
    try:
        return _pause_left(_cache(), kh, world,
                           _now() if now is None else now)
    except Exception:  # noqa: BLE001 — unreadable holds nothing
        return 0.0


def pause_read(kh: str, world: str) -> "dict | None":
    """The stored pause of (kh, world) ({"end", "at"}), or None. Never
    raises."""
    try:
        held = _cache().get(_pause_key(kh, world))
        return held if isinstance(held, dict) else None
    except Exception:  # noqa: BLE001
        return None


def pause_write(kh: str, world: str, *, end: float, at: float,
                keep_s: float, fresh: bool) -> bool:
    """Store a pause of (kh, world) ending at `end`, kept `keep_s` (its
    length and the streak after it). `fresh`: only where none is stored
    (cache.add, so two processes meeting one 429 grant one pause). False
    when another process stored one first or the cache refused. Never
    raises."""
    try:
        c = _cache()
        key = _pause_key(kh, world)
        _PAUSE_KEYS.add(key)
        value = {"end": float(end), "at": float(at)}
        ttl = max(1, int(math.ceil(keep_s)))
        if fresh:
            return bool(c.add(key, value, ttl))
        c.set(key, value, ttl)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("eToro budget [%s]: the 429 pause for %s could not be "
                    "stored (%s)", kh, world, type(e).__name__)
        return False


def forget_pauses() -> None:
    """Delete every pause this process wrote (tests). Never raises."""
    try:
        c = _cache()
        for key in list(_PAUSE_KEYS):
            c.delete(key)
    except Exception:  # noqa: BLE001
        pass
    _PAUSE_KEYS.clear()


def reset() -> None:
    """Forget this process's own memory, its queued counts and its pauses
    (tests; the window counters go with cache.clear()). Waits for a drain
    in progress, so no count of a test lands in the next."""
    with _DRAIN:
        _SPENT.clear()
        _LATER.clear()
    _NOTED.clear()
    _DOWN_SAID.clear()
    UNBUDGETED.clear()
    DROPPED.clear()
    forget_pauses()


# ── the read-only view (manage.py etoro_budget) ─────────────────────────

def report(now=None) -> dict:
    """What the budget holds, per key hash and family, for this window and
    the one before: {"ok", "error", "now", "windows", "rates", "floors",
    "keys": {kh: {"seen", "pause": {world: {"end", "left"} | None},
    "rolling": {family: the last WINDOW_S seconds' count, what a take is
    judged on (2026-11-02)}, "families": {family: {win: {"taken", "by",
    "refused", "last", "overruns"}}}}}}. Token counts, instants and words
    only: no account figure and no key. This process's queued counts are
    counted first. Never raises."""
    flush()
    now = _now() if now is None else float(now)
    win = window(now)
    out = {"ok": True, "error": "", "now": now, "windows": [win, win - 1],
           "rates": {f: rate(f) for f in FAMILIES},
           "floors": {p: {f: floor_tokens(f, p) for f in FAMILIES}
                      for p in (P2, P3, P4, P5)},
           "keys": {}, "unbudgeted_here": dict(UNBUDGETED),
           "dropped_here": dict(DROPPED)}
    try:
        c = _cache()
        seen = c.get(REGISTRY_KEY)
        seen = dict(seen) if isinstance(seen, dict) else {}
    except Exception as e:  # noqa: BLE001
        out.update(ok=False, error=type(e).__name__)
        return out
    for kh in sorted(seen):
        entry = {"seen": seen.get(kh), "pause": {}, "rolling": {},
                 "families": {}}
        try:
            for family in FAMILIES:
                past, here = _rolled(c, _slot_keys(kh, family, now))
                entry["rolling"][family] = past + here
            for world in ("live", "demo"):
                held = c.get(_pause_key(kh, world))
                if isinstance(held, dict) and held.get("end") is not None:
                    end = float(held["end"])
                    entry["pause"][world] = {"end": end,
                                             "left": max(0.0, end - now)}
                else:
                    entry["pause"][world] = None
            for family in FAMILIES:
                rows = {}
                for w in out["windows"]:
                    names = [_n_key(kh, family, w), _o_key(kh, family, w)]
                    names += [_p_key(kh, family, w, p) for p in PRIORITIES]
                    names += [_r_key(kh, family, w, p, r)
                              for p in PRIORITIES for r in REASONS]
                    names += [_w_key(kh, family, w, p) for p in PRIORITIES]
                    got = c.get_many(names)
                    rows[w] = {
                        "taken": int(got.get(_n_key(kh, family, w)) or 0),
                        "overruns": int(got.get(_o_key(kh, family, w)) or 0),
                        "by": {p: int(got.get(_p_key(kh, family, w, p)) or 0)
                               for p in PRIORITIES},
                        "refused": {
                            (p, r): int(got.get(_r_key(kh, family, w, p, r))
                                        or 0)
                            for p in PRIORITIES for r in REASONS
                            if got.get(_r_key(kh, family, w, p, r))},
                        "last": {p: str(got.get(_w_key(kh, family, w, p)))
                                 for p in PRIORITIES
                                 if got.get(_w_key(kh, family, w, p))}}
                entry["families"][family] = rows
        except Exception as e:  # noqa: BLE001
            out.update(ok=False, error=type(e).__name__)
        out["keys"][kh] = entry
    return out
