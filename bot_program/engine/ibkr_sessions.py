"""One IBKR session per process and purpose — held on purpose, closed on purpose.

The defect this replaces
------------------------
broker_router built a NEW IBKRTrader on every call, and every IBKRTrader
opened its own ib_insync ``IB()`` socket on the SAME trading clientId.
Nothing on the trading path ever called ``disconnect()``: manage_positions
per open trade, the scan per symbol, the capital reading, the pending-close
retry, the kill switch and the ten-minute bar writer all left their socket
to the garbage collector. IBKR does not evict the earlier holder of a
clientId — it REFUSES the newcomer (error 326, "clientId already in use"),
which ib_insync surfaces as a connect timeout. So the first connection a
worker child made held the slot until the collector happened to run, and
every later call in the same or a sibling process waited five seconds and
then degraded silently: a '0' mark, an empty klines list, a market_order
refused as ``ibkr_unavailable``. Nothing was logged at a level anyone read.

What this module does instead
-----------------------------
* ONE ``IBKRTrader`` per (host, port, base id, purpose) per process, cached
  here and handed back on every call. It reconnects when the Gateway has
  dropped it (its nightly restart, a re-login) and is disconnected
  explicitly when the Celery worker child shuts down or the process exits.
* THE TRADING SESSION IS EXCLUSIVE AND SHORT-LIVED, and that is not a
  performance decision — it is the only shape IBKR permits. **An order is
  visible only to the clientId that placed it.** ib_insync seeds its order
  table with ``reqOpenOrders`` (this client's orders; ib.py:1762), and its
  own ``openOrder`` wrapper documents that another client's orders arrive
  only when the session holds the Gateway's MASTER client id
  (wrapper.py:342-352). So ``openTrades()`` — which
  ``IBKRTrader.resting_order_ids``, ``order_status`` and ``cancel_order``
  all read — answers about THIS session's orders and nobody else's.

  Handing each process its own trading clientId would therefore have made
  every stored orderId unreadable from the next tick that happened to land
  in a sibling process, and the readers cannot tell "not mine" from
  "gone": a resting stop would read as vanished, a queued parent as
  cancelled, and a cancel as already done. That is worse than the
  collision it would have fixed — it turns a loud failure into a
  confident wrong answer about money.

  So every process uses the SAME trading clientId (``base``, exactly what
  the operator configured), takes it EXCLUSIVELY through a short cache
  lease, and disconnects at the end of the unit of work — a Celery task
  (``task_postrun``) or an HTTP request (``request_finished``). Order ids
  then live in one namespace that whoever holds the session can read in
  full. A process that cannot get the lease is handed None; the router
  falls back to PaperTrader, and every live path already refuses to trade
  through that, loudly. Waiting behind one tick is the cost; a stop nobody
  can see is not an acceptable alternative.
* DATA and PROBE sessions are pooled per process and slotted, because
  neither reads an orderId — bars, quotes, account values and positions
  are all account-scoped, so concurrent readers only need distinct
  clientIds::

      clientId = base + purpose offset + 300 x slot     (data, probe)
      clientId = base                                   (trade, exclusive)

  Bases stay below 100 and purposes are 0/100/200 apart, so every
  (base, purpose) pair owns one id inside a 300-wide band and each slot
  shifts the band.
* In a WEB request every session is per request: opened on first use on
  the request's thread and disconnected on ``request_finished`` on that
  same thread. A web process never holds a socket between two clicks, and
  the operator's "Test IBKR" can no longer knock a worker off its socket.

Callers that used to disconnect in a ``finally`` (the sync beat, the
unknown-position sweep, the HQ ping) may keep doing so: disconnecting a
pooled trader closes its socket and leaves the object in the pool, where
the next call reconnects it.
"""
from __future__ import annotations

import atexit
import logging
import os
import socket
import threading
import time
from typing import Optional

log = logging.getLogger(__name__)

# The purpose whose session is exclusive across processes: only the holder
# can read back the orders it placed (see the module docstring).
TRADE_PURPOSE = "trade"

# A slot lease outlives any single tick by a wide margin, and a process
# that dies without releasing blocks its slot for at most this long. The
# Gateway frees the clientId the moment the dead socket closes, so the
# only cost of a stale lease is one unusable slot out of CLIENT_ID_SLOTS.
LEASE_TTL_S = 30 * 60
# Renew no more often than this — a lease write per ticker() call would
# be a Redis round trip for nothing.
LEASE_RENEW_AFTER_S = 5 * 60

# The TRADING lease is deliberately short: it is released at the end of
# every task and request, so the only reason it is still held is a process
# that died mid-tick. Long enough to cover the slowest tick (a fleet of
# positions, each with a broker round trip), short enough that a crashed
# worker does not lock the fleet out for half an hour.
TRADE_LEASE_TTL_S = 5 * 60
# How long a caller waits for the trading session before giving up and
# letting the router fall back to paper (which every live path refuses,
# loudly). One tick's wait, not one tick's worth of silence.
TRADE_LEASE_WAIT_S = 8.0
TRADE_LEASE_POLL_S = 0.4

_process_sessions: dict = {}          # (host, port, base, purpose) -> IBKRTrader
_thread_state = threading.local()     # .in_request: bool, .sessions: dict
_mode = {"worker": False}
_lock = threading.RLock()


# ── identity ───────────────────────────────────────────────────────────────

def _token() -> str:
    """Who holds a lease: this host, this process, this thread."""
    return f"{socket.gethostname()}:{os.getpid()}:{threading.get_ident()}"


def _lease_key(host, port, base, purpose, slot) -> str:
    return f"ibkr:cid:{host}:{port}:{base}:{purpose}:{slot}"


def _cache():
    from django.core.cache import cache
    return cache


def _bucket() -> dict:
    """Where this call's sessions live: the request's thread, or the process."""
    if getattr(_thread_state, "in_request", False):
        sessions = getattr(_thread_state, "sessions", None)
        if sessions is None:
            sessions = _thread_state.sessions = {}
        return sessions
    return _process_sessions


def in_worker() -> bool:
    """True once Celery's worker_process_init has fired in this process."""
    return bool(_mode["worker"])


# ── leases ─────────────────────────────────────────────────────────────────

def _lease_slot(host, port, base, purpose) -> Optional[tuple]:
    """Claim a clientId for (gateway, base, purpose).

    The TRADE purpose has exactly one slot and is exclusive across
    processes — the orders it places are readable from nowhere else — so a
    caller waits briefly for it and is refused if the holder does not let
    go. DATA and PROBE take the lowest free slot of CLIENT_ID_SLOTS.

    Returns (slot, cache_key), or None when nothing is free. A cache that
    cannot be reached at all degrades to slot 0 with an empty key — the
    single-process behaviour the platform had before — but a cache that
    ANSWERED "held" is believed: handing out an id another process was
    just seen to own is how two sessions end up on one clientId.
    """
    from .ibkr_client import IBKRTrader

    exclusive = (purpose == TRADE_PURPOSE)
    slots = 1 if exclusive else getattr(IBKRTrader, "CLIENT_ID_SLOTS", 8)
    if not isinstance(slots, int) or slots < 1:
        slots = 8       # a test stand-in without the constant
    ttl = TRADE_LEASE_TTL_S if exclusive else LEASE_TTL_S
    tok = _token()
    deadline = time.monotonic() + (TRADE_LEASE_WAIT_S if exclusive else 0.0)
    seen_held = False

    while True:
        try:
            cache = _cache()
            for slot in range(slots):
                if _slot_is_avoided(host, port, base, purpose, slot):
                    continue
                key = _lease_key(host, port, base, purpose, slot)
                if cache.add(key, tok, timeout=ttl):
                    return slot, key
                if cache.get(key) == tok:
                    # Ours already — the trader was dropped from the bucket
                    # (a re-saved account, a rebuild) but the lease is still
                    # this process's. Re-stamp it so it cannot lapse under
                    # the session we are about to hand back.
                    cache.set(key, tok, timeout=ttl)
                    return slot, key
                seen_held = True
        except Exception as e:  # noqa: BLE001 — a cache fault must not stop
            if seen_held:
                # We already learned someone holds one. Guessing past that
                # would put two sessions on one clientId, which IBKR
                # answers by refusing whichever connects second — silently,
                # as a connect timeout.
                log.error("[ibkr sessions] lease cache failed mid-scan (%s) "
                          "after seeing a held slot — refusing rather than "
                          "reusing a clientId another process owns", e)
                return None
            log.warning("[ibkr sessions] lease cache unavailable (%s) — "
                        "slot 0 unleased", e)
            return 0, ""
        if time.monotonic() >= deadline:
            return None
        time.sleep(TRADE_LEASE_POLL_S)


def _renew_lease(trader) -> bool:
    """Keep this process's claim on the trader's slot alive.

    Returns False when ANOTHER process now holds the slot — the lease
    expired while this session sat idle and a sibling leased it. The
    caller must then stop using this clientId, or the sibling's connects
    fail on it for as long as this socket stays open. Rate-limited to one
    cache read per LEASE_RENEW_AFTER_S; a cache fault reads as held.
    """
    lease = getattr(trader, "_sv_lease", None)
    if not lease or not lease["key"]:
        return True
    ttl = TRADE_LEASE_TTL_S if lease.get("exclusive") else LEASE_TTL_S
    # The trading lease is short, so it is re-stamped on every use rather
    # than on a timer: a tick that runs longer than the TTL must not have
    # its session leased away underneath it.
    after = 0.0 if lease.get("exclusive") else LEASE_RENEW_AFTER_S
    if time.monotonic() - lease["renewed"] < after:
        return True
    try:
        cache = _cache()
        holder = cache.get(lease["key"])
        if holder not in (None, lease["token"]):
            return False
        cache.set(lease["key"], lease["token"], timeout=ttl)
        lease["renewed"] = time.monotonic()
    except Exception as e:  # noqa: BLE001
        log.debug("[ibkr sessions] lease renew failed: %s", e)
    return True


def _drop(bucket: dict, key, trader, *, release: bool) -> None:
    """Forget a pooled trader: close its socket, optionally free its slot."""
    bucket.pop(key, None)
    try:
        disconnect = getattr(trader, "disconnect", None)
        if callable(disconnect):
            disconnect()
    except Exception as e:  # noqa: BLE001
        log.debug("[ibkr sessions] disconnect failed: %s", e)
    if release:
        _release_lease(trader)


# Slots this process could not connect on, and when to try them again.
# A clientId whose connect is refused is one another process still has a
# SOCKET on (its lease may have lapsed, but IBKR answers the newcomer with
# error 326 either way), so retrying the same slot forever — which
# `_lease_slot`'s "ours already" branch would do — leaves this process
# permanently on paper. Stepping to the next slot is the whole point of
# having several.
_slot_backoff: dict = {}
SLOT_AVOID_S = 5 * 60


def _avoid_slot(host, port, base, purpose, slot) -> None:
    _slot_backoff[(str(host), int(port), int(base), str(purpose), int(slot))] = (
        time.monotonic() + SLOT_AVOID_S)


def _slot_is_avoided(host, port, base, purpose, slot) -> bool:
    key = (str(host), int(port), int(base), str(purpose), int(slot))
    until = _slot_backoff.get(key)
    if until is None:
        return False
    if time.monotonic() >= until:
        _slot_backoff.pop(key, None)
        return False
    return True


def _failed_and_backoff_lapsed(trader) -> bool:
    """A trader whose last connect failed and whose backoff has run out.

    Rebuilding it takes a fresh lease, so a clientId that another process
    has meanwhile taken is not retried forever from a cached object.
    """
    try:
        if trader.is_connected():
            return False
        next_at = float(getattr(trader, "_next_connect_at", 0.0) or 0.0)
    except Exception:  # noqa: BLE001 — a stand-in without the attribute
        return False
    return bool(next_at) and time.monotonic() >= next_at


def _release_lease(trader) -> None:
    lease = getattr(trader, "_sv_lease", None)
    if not lease or not lease["key"]:
        return
    try:
        cache = _cache()
        if cache.get(lease["key"]) == lease["token"]:
            cache.delete(lease["key"])
    except Exception as e:  # noqa: BLE001
        log.debug("[ibkr sessions] lease release failed: %s", e)


# ── the pool ───────────────────────────────────────────────────────────────

def acquire_trader(host, port, base_client_id, purpose: str,
                   account_id: str = "", paper: bool = True):
    """The IBKRTrader this process uses for (host, port, base, purpose).

    Returns the cached trader when one exists, else leases a slot and builds
    one. Returns None when no slot is free — the router treats that like
    any other missing broker and falls back to PaperTrader, which every
    live path refuses to trade through, loudly.

    The account id and paper flag are re-stamped on every call: an operator
    who re-saves the account must reach the session that is already open.
    """
    from . import ibkr_client as _mod

    try:
        base = int(base_client_id)
    except (TypeError, ValueError):
        base = 1
    key = (str(host), int(port), base, str(purpose))

    trader = _pooled(key, account_id, paper, host, port, base, purpose)
    if trader is not None:
        return trader

    # The lease is taken OUTSIDE the process lock. It can block for up to
    # TRADE_LEASE_WAIT_S waiting for the exclusive trading slot, and holding
    # the lock across that would stall every other thread in this process —
    # including ones asking for a data session, and the release paths that
    # also take the lock, which is how N waiters would cost N x the wait.
    leased = _lease_slot(host, port, base, purpose)
    if leased is None:
        log.error(
            "[ibkr sessions] no clientId available for %s:%s base %s purpose "
            "%s — another process holds it; refusing rather than colliding "
            "with a live session", host, port, base, purpose)
        return None
    slot, cache_key = leased

    with _lock:
        # Re-check: another thread may have installed one while we waited.
        existing = _pooled(key, account_id, paper, host, port, base, purpose)
        if existing is not None:
            _release_lease(_LeaseHolder(cache_key))
            return existing
        bucket = _bucket()
        client_id = _mod.purpose_client_id(base, purpose, slot)
        trader = _mod.IBKRTrader(
            host=host, port=port, client_id=client_id,
            account_id=account_id or "", paper=bool(paper),
        )
        log.info("[ibkr sessions] %s session for %s:%s on clientId %s "
                 "(base %s, slot %s)", purpose, host, port, client_id, base,
                 slot)
        try:
            trader._sv_lease = {"key": cache_key, "token": _token(),
                                "slot": slot, "renewed": time.monotonic(),
                                "exclusive": purpose == TRADE_PURPOSE}
        except Exception:  # noqa: BLE001 — a stand-in may refuse attributes
            pass
        bucket[key] = trader
        return trader


class _LeaseHolder:
    """Just enough of a trader for _release_lease to free a key."""

    def __init__(self, cache_key):
        self._sv_lease = {"key": cache_key, "token": _token(),
                          "slot": 0, "renewed": 0.0, "exclusive": False}


def _pooled(key, account_id, paper, host, port, base, purpose):
    """The pooled trader for `key`, or None. Drops one that must not be
    reused (a foreign stand-in, a lost lease, a dead connect)."""
    from . import ibkr_client as _mod

    with _lock:
        bucket = _bucket()
        trader = bucket.get(key)
        # Tests replace ibkr_client.IBKRTrader with a stand-in; a trader
        # built by an earlier stand-in must not be handed to a later one.
        if trader is not None and type(trader) is not _mod.IBKRTrader:
            bucket.pop(key, None)
            trader = None
        if trader is not None and not _renew_lease(trader):
            log.warning("[ibkr sessions] slot for %s:%s base %s purpose %s "
                        "was leased by another process while this session "
                        "sat idle — closing it and taking a fresh slot",
                        host, port, base, purpose)
            _drop(bucket, key, trader, release=False)
            trader = None
        if trader is not None and _failed_and_backoff_lapsed(trader):
            # This clientId is refused (another process still has a socket
            # on it). Step off it rather than retrying it forever.
            lease = getattr(trader, "_sv_lease", None)
            if lease and not lease.get("exclusive"):
                _avoid_slot(host, port, base, purpose, lease.get("slot", 0))
            _drop(bucket, key, trader, release=True)
            trader = None
        if trader is not None:
            trader.account_id = account_id or ""
            trader.paper = bool(paper)
        return trader


def _release_bucket(bucket: dict) -> int:
    n = 0
    for key in list(bucket.keys()):
        trader = bucket.pop(key, None)
        if trader is None:
            continue
        n += 1
        try:
            disconnect = getattr(trader, "disconnect", None)
            if callable(disconnect):
                disconnect()
        except Exception as e:  # noqa: BLE001
            log.debug("[ibkr sessions] disconnect failed: %s", e)
        _release_lease(trader)
    return n


def release_trade_sessions() -> int:
    """Disconnect this process's TRADING sessions and free their leases.

    Called at the end of every Celery task and every HTTP request, because
    the trading clientId is exclusive: holding it between units of work
    would lock every other process out of placing, reading or cancelling
    an order. Data and probe sessions are left pooled — they read nothing
    order-scoped and reconnecting them per task would be waste.
    """
    released = 0
    with _lock:
        for bucket in (_process_sessions, getattr(_thread_state, "sessions", None) or {}):
            for key in [k for k in bucket if k[3] == TRADE_PURPOSE]:
                trader = bucket.pop(key, None)
                if trader is None:
                    continue
                released += 1
                try:
                    disconnect = getattr(trader, "disconnect", None)
                    if callable(disconnect):
                        disconnect()
                except Exception as e:  # noqa: BLE001
                    log.debug("[ibkr sessions] disconnect failed: %s", e)
                _release_lease(trader)
    if released:
        log.debug("[ibkr sessions] released %d trading session(s)", released)
    return released


def release_all(*, forget_slot_backoff: bool = False) -> int:
    """Disconnect every session this process holds and free its slots.

    Wired to Celery's worker_process_shutdown and to atexit. Returns how
    many sessions were closed. `forget_slot_backoff` also clears the
    refused-slot memory — for tests, and for a caller that wants a truly
    clean slate.
    """
    with _lock:
        n = _release_bucket(_process_sessions)
        sessions = getattr(_thread_state, "sessions", None)
        if sessions:
            n += _release_bucket(sessions)
        if forget_slot_backoff:
            _slot_backoff.clear()
    if n:
        log.info("[ibkr sessions] released %d IBKR session(s)", n)
    return n


def held_sessions() -> list:
    """Diagnostic: the traders this process currently holds."""
    with _lock:
        out = list(_process_sessions.values())
        sessions = getattr(_thread_state, "sessions", None)
        if sessions:
            out.extend(sessions.values())
    return out


# ── lifecycle wiring ───────────────────────────────────────────────────────

def _on_request_started(**_kwargs) -> None:
    _thread_state.in_request = True


def _on_request_finished(**_kwargs) -> None:
    _thread_state.in_request = False
    sessions = getattr(_thread_state, "sessions", None)
    if sessions:
        with _lock:
            _release_bucket(sessions)


def _on_worker_process_init(**_kwargs) -> None:
    _mode["worker"] = True


def _on_worker_process_shutdown(**_kwargs) -> None:
    release_all()


def _on_task_postrun(**_kwargs) -> None:
    """Hand the exclusive trading session back after every task.

    One hook rather than a try/finally in each of the dozen tasks that can
    reach a broker (the bot tick, reconciliation, the pending-close drain,
    the option-chain refresh, a scenario run): the ones added next would
    have to remember, and the cost of forgetting is the whole fleet locked
    out of its own orders.
    """
    release_trade_sessions()


_installed = {"done": False}


def install_signal_handlers() -> None:
    """Connect the request and worker lifecycle hooks. Idempotent."""
    if _installed["done"]:
        return
    _installed["done"] = True

    from django.core.signals import request_finished, request_started
    request_started.connect(_on_request_started, weak=False,
                            dispatch_uid="ibkr-sessions-request-started")
    request_finished.connect(_on_request_finished, weak=False,
                             dispatch_uid="ibkr-sessions-request-finished")
    try:
        from celery import signals as celery_signals
        celery_signals.worker_process_init.connect(
            _on_worker_process_init, weak=False,
            dispatch_uid="ibkr-sessions-worker-init")
        celery_signals.worker_process_shutdown.connect(
            _on_worker_process_shutdown, weak=False,
            dispatch_uid="ibkr-sessions-worker-shutdown")
        celery_signals.task_postrun.connect(
            _on_task_postrun, weak=False,
            dispatch_uid="ibkr-sessions-task-postrun")
    except Exception as e:  # noqa: BLE001 — Celery absent in some contexts
        log.debug("[ibkr sessions] celery signals not wired: %s", e)
    atexit.register(release_all)
