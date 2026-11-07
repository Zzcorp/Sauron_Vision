"""What became of one TAKE TRADE send, for a page whose answer was lost.

2026-11-06, a live forex ticket: the operator sent a LIVE order, entered
the PIN, and the page said "Network error". The order had gone: eToro had
filled it. Words that read like "nothing happened" after the PIN invite a
second order, and the page had no way to find out what the first one did.

So each send now carries a ref the page made for it (`ticket_ref`, 32
lowercase hex characters), and the two execute views
(dashboard.views.take_trade_execute and asset_trade_execute) keep a small
record of it here:

    received  written BEFORE the executor is called, with the time
    booked    the executor answered ok: the row's id, symbol, side, size,
              entry, venue and the notes the answer carried
    refused   the executor answered an error: its words, the funding
              closes already made, and `in_doubt` when the words say the
              order MAY have reached the broker (the broker call raised
              before its answer arrived): no refusal, so the page never
              tells it "nothing opened"

and GET /api/take-trade/outcome/<ref>/ reads it back for the caller, and
only the caller: the key carries the user's id. "unknown" is the absence
of a record, which is not proof that nothing was sent (the line may have
dropped before the request reached Sauron, or the record may not have been
written), so the page never reads it as such.

The record is BEST-EFFORT. It lives in the Django cache (Redis in
production, where the live path already keeps its double-click claim and
the PIN counter), for two hours, written through its own alias
(CACHE_ALIAS): the same store, with socket timeouts of half a second, so a
Redis that stalls holds a send about half a second before the executor and
again after it, not redis-py's default 5 s each way (MEASURED against a
port that accepts and never answers: 0.56 s a call through the alias, 5.0
to 6.2 s through the default one). Every call is fenced: a cache that
fails is logged by its exception's type and swallowed, and the order goes
on as if no ref had been sent. Nothing here reads, changes or answers for
the executor: its arguments and its answer are the same with or without a
ref.

A request whose executor raises (a 500 after the order may have left)
writes no final state: the record stays "received", which says only that
Sauron got the order and wrote no result for it — not that the broker has
not answered. eToro may have filled it before the view died, so the page
sends the operator to the eToro app first. The same holds when the line
drops while the view's thread is inside an async_to_sync call made after
the commit (the fill's push to the Eye): asgiref raises CancelledError
into that call, a BaseException that passes the executor's fences, and
the record stays "received" although the row is booked.

One ref, one record. The request that wrote "received" is the one that
writes the result. A second request carrying the same ref (a browser that
replays a POST sends the same body) finds the record there and leaves it
alone, so the replay's own refusal ("already in flight", "already taken")
never replaces what became of the first.
"""
from __future__ import annotations

import logging
import re

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)

#: How long a record is kept: far past any answer the page waits for.
TTL_SECONDS = 2 * 3600

RECEIVED = "received"
BOOKED = "booked"
REFUSED = "refused"
UNKNOWN = "unknown"
STATES = (RECEIVED, BOOKED, REFUSED, UNKNOWN)

#: What a booked record keeps of the executor's answer: what the page
#: prints when it finds the order went (manual_trade._execute's `out`).
BOOKED_FIELDS = ("trade_id", "symbol", "side", "qty", "entry", "stop",
                 "target", "venue", "working", "protection_note",
                 "readback_note", "closed")

#: The cache alias the record writes through (config/settings.py
#: TICKET_RECORD_CACHE): the default store with a short fuse. Settings that
#: name no such alias (a test's own CACHES) write through the default.
CACHE_ALIAS = "ticket_outcome"

#: manual_trade._execute's words when the live leg's broker call raised
#: before its answer arrived: the order may be at the broker. The page
#: reads the same words in an answer that did come back (base.html,
#: mayHaveReached); tests/test_ticket_lost_answer.py runs the executor's
#: own sentence through both.
IN_DOUBT = re.compile(r"MAY have reached the broker", re.I)

_REF = re.compile(r"[0-9a-f]{32}")


def clean_ref(raw):
    """The ref when it is exactly 32 lowercase hex characters, else None.
    fullmatch, not match with "$": "$" lets a trailing newline through."""
    if isinstance(raw, str) and _REF.fullmatch(raw):
        return raw
    return None


def _cache():
    from django.conf import settings
    from django.core.cache import caches
    return caches[CACHE_ALIAS if CACHE_ALIAS in settings.CACHES
                  else "default"]


def _key(uid, ref) -> str:
    return f"ticket_ref:{uid}:{ref}"


def _warn(what: str, e: Exception) -> None:
    # The type only: an exception's text can carry a cache address.
    logger.warning("ticket record: %s (%s)", what, type(e).__name__)


class Note:
    """One send's record, opened before the executor runs. `result` writes
    the executor's answer, and only when this request opened the record."""

    __slots__ = ("uid", "ref", "opened")

    def __init__(self, uid, ref, opened: bool):
        self.uid = uid
        self.ref = ref
        self.opened = opened

    def result(self, res) -> None:
        """'booked' or 'refused' off the answer the view returns. Anything
        else (not a dict, neither ok nor an error) leaves 'received'."""
        if not self.opened:
            return
        try:
            if not isinstance(res, dict):
                return
            now = timezone.now().isoformat()
            if res.get("ok"):
                rec = {"state": BOOKED, "at": now}
                rec.update({k: res[k] for k in BOOKED_FIELDS if k in res})
            elif res.get("error"):
                error = str(res["error"])
                rec = {"state": REFUSED, "at": now, "error": error,
                       "in_doubt": bool(IN_DOUBT.search(error)),
                       "closed": list(res.get("closed") or [])}
            else:
                return
            _cache().set(_key(self.uid, self.ref), rec, TTL_SECONDS)
        except Exception as e:  # noqa: BLE001 — never the order's problem
            _warn("the result could not be written", e)


def received(uid, ref) -> Note:
    """Open the record of one send: 'received', now, BEFORE the executor
    is called. `ref` is the parsed ticket_ref (None when absent or not 32
    lowercase hex: nothing is recorded). Never raises."""
    ref = clean_ref(ref)
    if uid is None or ref is None:
        return Note(uid, ref, False)
    try:
        opened = bool(_cache().add(
            _key(uid, ref),
            {"state": RECEIVED, "at": timezone.now().isoformat()},
            TTL_SECONDS))
    except Exception as e:  # noqa: BLE001 — never the order's problem
        _warn("'received' could not be written", e)
        opened = False
    return Note(uid, ref, opened)


def read(uid, ref):
    """The record of `ref` for this user, or None. Raises when the cache
    cannot be read: the caller says so rather than answer 'unknown'."""
    ref = clean_ref(ref)
    if uid is None or ref is None:
        return None
    rec = _cache().get(_key(uid, ref))
    if not isinstance(rec, dict) or rec.get("state") not in STATES:
        return None
    return rec


@login_required
@never_cache
@require_GET
def take_trade_outcome(request, ref):
    """GET /api/take-trade/outcome/<ref>/ — what became of one send.

    {"state": "received" | "booked" | "refused" | "unknown", ...}, read
    from the caller's own record only. Reads one cache key: no broker, no
    database, no write. Under /api/ so a locked tab's ask is answered 423
    (core.idle_lock) instead of a redirect, and is never counted as the
    operator's own activity. A record that cannot be read is a 503 with no
    state, never "unknown": the page keeps its "may have gone" words."""
    if clean_ref(ref) is None:
        return JsonResponse({"state": UNKNOWN})
    try:
        rec = read(request.user.pk, ref)
    except Exception as e:  # noqa: BLE001
        _warn("a record could not be read", e)
        return JsonResponse(
            {"error": "The ticket's record could not be read just now."},
            status=503)
    return JsonResponse(rec if rec is not None else {"state": UNKNOWN})
