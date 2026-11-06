"""The eToro account re-read after the platform's own orders and closes
(2026-10-31).

The operator: "The 15min etoro refresh is way too long, to operate in a
market (wait 15min to make another trade...)". Before every eToro order
the bots and the TAKE TRADE ticket ask AssetBot._leverage_headroom, which
reads the free cash and the used margin from the cells the sync stores.
An order sent since the read is charged at once (_pledged_since); a close
since the read was never credited, so "close one, then open another" was
refused until the next sync.

So every order and every close the platform books asks for ONE re-read of
the account (tasks.refresh_etoro_cells: the sync's own aggregate-portfolio
GET; the cash and the used margin under one stamp taken before the GET),
on the fast queue SETTLE_S after the booking commits. The cells move
within the same second as a fill (MEASURED 2026-09-23); the holdings list
lags about 60 s and is not read here. The equity and its age stay the
sync's: the pools that follow the account are retuned from it by the
sync alone, and freeze on its age; the gate refuses on an equity over an
hour old whatever the cells' age (AssetBot._cash_gate, review 2026-10-31),
so fresh cells never lift the hour rule over an old equity.

The gate itself is unchanged and still reads stored cells: no broker I/O
on an entry path. Money direction: after a close the freed cash is
credited a sync sooner (looser in effect, by what eToro has already
freed); after an open the gate reads eToro's own margin and fees instead
of the platform's estimate (slightly tighter). No limit moves.

ONE READ PER PASS (the eToro request budget, 2026-10-31). A pass that
books several closes or orders (the bot tick, the reconcile, the
pending-close drain, the kill switch: one_read_per_pass) holds the asks
of its bookings and asks ONE read per account once it has finished,
never one per close inside it: the read never runs beside the pass's
own closes and their proofs, which share the account's key. A single
booking outside a pass (the TAKE TRADE ticket, the CLOSE button) asks at
once.

PACED PER ACCOUNT. At most one read starts per COALESCE_S, and every
request is read by one that starts SETTLE_S or more after it (review,
2026-10-31): a request that finds a queued read starting SETTLE_S or
more from now needs nothing more; any other request queues the next read,
SETTLE_S from now or COALESCE_S after the latest read, whichever is
later, and that read covers every request until SETTLE_S before it
starts. A read that starts sooner than SETTLE_S after a booking is not
that booking's read: it may not carry the fill yet, and
AssetBot._pledged_since charges such a row on top of it. The
eToro quota on this endpoint is unmeasured (no 429 has been recorded on
it); bounded like this an account costs at most about three of these
reads a minute in a burst of orders, and none when nothing trades. A 429
or a 5xx here counts on the venue's health like the sync's own reads:
they are the same request.

Every function is fenced: a re-read is beside the trade, never in it.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from contextlib import ContextDecorator

logger = logging.getLogger(__name__)

#: Seconds after the booking commits before the re-read starts; the read
#: that covers a booking starts at least this long after it.
SETTLE_S = 3
#: At most one re-read starts per account in this many seconds.
COALESCE_S = 20
#: Past this age the TAKE TRADE preview asks for a re-read and says so.
TICKET_FRESH_S = 60

#: The earliest a further read may start (epoch seconds): the latest
#: read's start, planned or actual, plus COALESCE_S.
_WINDOW_KEY = "etoro_cells:window:{pk}"
#: The latest read queued and not yet started: its planned start (epoch
#: seconds). A request finding it SETTLE_S or more away needs nothing more.
_NEXT_KEY = "etoro_cells:next:{pk}"
#: A read starts at its planned second or later (the queue's countdown),
#: never sooner: within this of now, the queued read is the one starting.
_STARTING_SLACK_S = 1.0


def _cache():
    from django.core.cache import cache
    return cache


def _now() -> float:
    """The pacing clock (a seam: tests move it without moving time.time
    for every other caller)."""
    return time.time()


def _num(value):
    """A stored instant as a float, or None."""
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _ttl(until: float, now: float) -> int:
    """Whole seconds a key about `until` is kept: past it by COALESCE_S."""
    return max(1, int(math.ceil(until - now))) + COALESCE_S


def account_pk_for(user):
    """The pk of this user's keyed eToro account, or None."""
    try:
        from bot_program.models import EtoroAccount
        return (EtoroAccount.objects.filter(user_id=getattr(user, "pk", None))
                .exclude(api_key_enc="")
                .values_list("pk", flat=True).first())
    except Exception as e:  # noqa: BLE001
        logger.warning("eToro re-read: account lookup failed: %s", e)
        return None


#: THE SYNC THE eTORO BUDGET DEFERRED (2026-11-02): the instant (epoch
#: seconds, taken before the read) of the newest pass that did not send
#: an account's aggregate. AssetBot._cash_gate refuses the account's eToro
#: entries while it is newer than the account's last_sync: the cells and
#: the equity a deferred pass did not read would have been fresher.
_DEFERRED_KEY = "etoro_cells:sync_deferred:{pk}"
#: Kept an hour: past it the cells' own hour rule refuses anyway.
DEFERRED_KEEP_S = 3600


def note_sync_deferred(account_pk, at) -> None:
    """The sync did not send `account_pk`'s aggregate (a budget refusal)
    in its pass stamped `at` (an aware datetime). Never raises: a note
    that cannot be written holds nothing (2026-11-02)."""
    try:
        _cache().set(_DEFERRED_KEY.format(pk=account_pk), at.timestamp(),
                     DEFERRED_KEEP_S)
    except Exception as e:  # noqa: BLE001
        logger.warning("eToro sync: the deferral of account %s could not be "
                       "noted (%s)", account_pk, type(e).__name__)


def sync_deferred_at(account_pk):
    """The newest deferred pass of `account_pk` within DEFERRED_KEEP_S, as
    an aware UTC datetime, or None. Never raises."""
    try:
        from datetime import datetime, timezone as dt_timezone
        held = _num(_cache().get(_DEFERRED_KEY.format(pk=account_pk)))
        return (None if held is None
                else datetime.fromtimestamp(held, tz=dt_timezone.utc))
    except Exception:  # noqa: BLE001 — unreadable: nothing deferred
        return None


def note_read_started(account_pk) -> None:
    """Called by the task as its read starts: the window runs COALESCE_S
    from now, or from a later read already queued behind this one, which
    stays queued (2026-10-31); this read leaves the queue."""
    try:
        cache = _cache()
        now = _now()
        next_key = _NEXT_KEY.format(pk=account_pk)
        window_key = _WINDOW_KEY.format(pk=account_pk)
        queued = _num(cache.get(next_key))
        if queued is None or queued <= now + _STARTING_SLACK_S:
            cache.delete(next_key)
        ends = max(now + COALESCE_S, _num(cache.get(window_key)) or 0.0)
        cache.set(window_key, ends, _ttl(ends, now))
    except Exception as e:  # noqa: BLE001
        logger.debug("eToro re-read: window not noted: %s", e)


def _reads_allowed() -> bool:
    """The re-read runs under the sync's own switches (platform_master,
    broker_account_sync; tasks.refresh_etoro_cells asks them again as it
    starts). With either off nothing would read, so nothing is promised."""
    try:
        from core.platform_control import is_component_enabled
        return bool(is_component_enabled("platform_master")
                    and is_component_enabled("broker_account_sync"))
    except Exception as e:  # noqa: BLE001 — unreadable reads as off
        logger.debug("eToro re-read: switches unreadable: %s", e)
        return False


def request_refresh(account_pk, *, why: str = ""):
    """Queue one re-read of this account; the seconds until the read that
    covers this request starts, or None when nothing could be queued (the
    sync's switches off, or the queue refused it: then the keys are left
    as they were, so no later request is told a read is coming).

    COVERED ONLY BY A READ SETTLE_S AWAY (review, 2026-10-31). A queued
    read covers this request when it starts SETTLE_S or more from now: it
    reads this request's order or close. One that starts sooner did not:
    the TAKE TRADE ticket's own checks queued a read seconds before the
    order was sent, the booking found it queued, and the only read after
    the fill started a second later, stamped after the row — a fill the
    payload did not carry yet was counted nowhere until the next sync. So
    any other request queues the next read: SETTLE_S from now, or
    COALESCE_S after the latest read, whichever is later. The first one
    of a quiet spell is claimed with cache.add, so two passes ending
    together queue one; two requests racing inside the same few seconds
    after a read may queue one read each — a GET more, never one less."""
    if not account_pk or not _reads_allowed():
        return None
    next_key = _NEXT_KEY.format(pk=account_pk)
    window_key = _WINDOW_KEY.format(pk=account_pk)
    restore = []
    try:
        cache = _cache()
        now = _now()
        queued = _num(cache.get(next_key))
        if queued is not None and queued - now >= SETTLE_S:
            return queued - now
        ends = _num(cache.get(window_key))
        start = now + float(SETTLE_S)
        if ends is not None:
            start = max(start, ends + 0.5)
        if queued is None:
            if not cache.add(next_key, start, _ttl(start, now)):
                # a request racing this one claimed the read a moment ago
                held = _num(cache.get(next_key))
                return (float(SETTLE_S) if held is None
                        else max(0.0, held - now))
            restore.append((next_key, None))
        else:
            restore.append((next_key, queued))
            cache.set(next_key, start, _ttl(start, now))
        restore.append((window_key, ends))
        cache.set(window_key, start + COALESCE_S,
                  _ttl(start + COALESCE_S, now))
        from bot_program.tasks import refresh_etoro_cells
        refresh_etoro_cells.apply_async(
            args=[account_pk], kwargs={"why": str(why or "")[:40]},
            countdown=start - now, queue="fast")
        return start - now
    except Exception as e:  # noqa: BLE001 — a lost re-read is a sync's wait
        logger.warning("eToro re-read not queued (%s): %s", why, e)
        # nothing was queued: the keys go back to what they promised
        for key, old in restore:
            try:
                if old is None:
                    _cache().delete(key)
                else:
                    _cache().set(key, old, _ttl(old, _now()))
            except Exception:  # noqa: BLE001
                pass
        return None


#: The asks held by the pass running on this thread (one_read_per_pass):
#: `depth` (passes inside passes), `held` {account pk: [why, ...]}.
_PASS = threading.local()


def holding() -> bool:
    """True while a pass on this thread holds its re-read asks."""
    return getattr(_PASS, "depth", 0) > 0


class one_read_per_pass(ContextDecorator):
    """Hold the re-read asks of every booking inside, and ask ONE read per
    account when the outermost pass ends (2026-10-31). A context manager
    and a decorator; passes nest (the fleet tick runs each config's tick).
    A pass that raises still asks for what it booked before it broke, and
    the exception goes on. Never raises itself."""

    def __enter__(self):
        depth = getattr(_PASS, "depth", 0)
        if depth == 0:
            _PASS.held = {}
        _PASS.depth = depth + 1
        return self

    def __exit__(self, *exc):
        _PASS.depth = max(0, getattr(_PASS, "depth", 1) - 1)
        if _PASS.depth:
            return False
        held, _PASS.held = (getattr(_PASS, "held", None) or {}), None
        for pk, whys in held.items():
            try:
                why = whys[0] + (f" +{len(whys) - 1} more" if len(whys) > 1
                                 else "")
                request_refresh(pk, why=why)
            except Exception as e:  # noqa: BLE001 — beside the pass
                logger.warning("eToro re-read after a pass not asked: %s", e)
        return False


def _ask(account_pk, why: str):
    """The booking's ask, once it committed: held by a running pass, or
    queued at once."""
    held = getattr(_PASS, "held", None)
    if holding() and held is not None:
        held.setdefault(account_pk, []).append(str(why or ""))
        return None
    return request_refresh(account_pk, why=why)


def refresh_after_commit(user, *, why: str = "") -> None:
    """Queue the re-read once the current transaction commits (at once
    outside one); inside a pass, held until the pass ends. Nothing for a
    user with no keyed eToro account."""
    try:
        pk = account_pk_for(user)
        if not pk:
            return
        from django.db import transaction
        transaction.on_commit(lambda: _ask(pk, why))
    except Exception as e:  # noqa: BLE001
        logger.warning("eToro re-read not registered (%s): %s", why, e)


def refresh_for_trade(trade, *, why: str = "") -> None:
    """The re-read after a row's close was booked, when eToro carried the
    row: stamped "etoro", or an unstamped real-money row of a user who
    keys eToro (refresh_after_commit asks that)."""
    try:
        stamp = str((getattr(trade, "metadata", None) or {}).get("broker")
                    or "")
        if stamp == "etoro" or (not stamp and not getattr(trade, "paper",
                                                          True)):
            refresh_after_commit(trade.config.user, why=why)
    except Exception as e:  # noqa: BLE001
        logger.warning("eToro re-read for a close not registered: %s", e)


def refresh_for_client(user, client, *, why: str = "") -> None:
    """The re-read after an order sent through `client`, when it is the
    eToro adapter (either world: the cells gate demo orders as well)."""
    try:
        from bot_program.engine.capabilities import adapter_key
        if adapter_key(client) == "etoro":
            refresh_after_commit(user, why=why)
    except Exception as e:  # noqa: BLE001
        logger.warning("eToro re-read for an order not registered: %s", e)
