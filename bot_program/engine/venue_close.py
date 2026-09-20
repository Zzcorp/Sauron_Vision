"""One place that knows a close is not always an opposite order.

THREE PATHS SEND CLOSES in this platform — the bot's own exits
(asset_engine/base._submit_close_order), the retry drain
(pending_closes._submit_close) and the kill switch
(engine/kill_switch._try_broker_close) — and each of them ended in
`client.market_order(symbol, opposite_side, qty)`. On two of the three wired
venues that order does not close anything:

  * eToro's API separates opening from closing. market_order sends
    {"action": "open", ...} and has no close branch, so a SELL becomes
    `sellShort`: a short OPENED beside the long. The account then holds
    DOUBLE, hedged, paying both spreads, while the row books CLOSED at that
    fill and the platform's P&L becomes a fiction.
  * Saxo under the FifoEndOfDay netting profile keeps BOTH lots Open until
    the evening netting, so the row books CLOSED over live exposure.

So the venue is ASKED, once, here — and when it says a position id is needed
and the row has none, NOTHING IS SENT. That refusal is the whole point: an
opening order is not a degraded close, it is the opposite trade. The row goes
CLOSE_PENDING instead, where the retry drain reads the broker's own book and
either finalises a position that is really flat or blocks with an alert.

The three callers keep their own bookkeeping — idempotency ids, residuals,
options overrides — and share only this decision.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def venue_needs_position_id(client) -> bool:
    """Does this venue refuse to net an opposite order?

    A yes or a no, and nothing else: an adapter that answers with anything
    that is not a bool has not answered the question, and the honest reading
    of no answer is the ordinary close — the same reading a raise gets.
    Any truthy object would otherwise send every mock, sentinel and stray
    dict down the position-id path.
    """
    ask = getattr(client, "close_needs_position_id", None)
    if not callable(ask):
        return False
    try:
        answer = ask()
    except Exception as e:  # noqa: BLE001 — unknown: the ordinary close
        log.warning("venue_close: could not ask how %s nets (%s) — closing "
                    "with an opposite order", type(client).__name__, e)
        return False
    if not isinstance(answer, bool):
        log.warning("venue_close: %s answered %r when asked how it nets, "
                    "which is neither yes nor no — closing with an opposite "
                    "order", type(client).__name__, answer)
        return False
    return answer


def position_id_for(trade) -> str:
    """The venue handle this row can be closed BY, or "".

    str() of anything at all returns a non-empty string, and an id we
    invented is worse than no id: it closes some OTHER position, or nothing,
    and the row books CLOSED either way. So only a string or a real integer
    is accepted — a JSON round trip can leave a Saxo PositionId as an int —
    and metadata, being a JSONField, can hold neither.
    """
    meta = trade.metadata if isinstance(getattr(trade, "metadata", None), dict) else {}
    raw = meta.get("protective_trade_id") or meta.get("broker_position_id")
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, int) and not isinstance(raw, bool):
        return str(raw)
    return ""


def close_or_refuse(trade, client, qty: float, *, close_side: str,
                    client_order_id: str = "", extra: dict | None = None):
    """Send the close THIS venue understands, or raise rather than open a trade.

    Returns the broker's response. Raises when the venue needs a position id
    and the row has none, or when it needs one and the adapter has no
    close_position — because on that venue the fallback is not a close.
    """
    symbol = trade.symbol
    if not venue_needs_position_id(client):
        return client.market_order(symbol, close_side, float(qty),
                                   client_order_id=client_order_id,
                                   **(extra or {}))

    pid = position_id_for(trade)
    closer = getattr(client, "close_position", None)
    if pid and callable(closer):
        # The caller's deterministic id where the adapter takes one: three
        # call sites in this platform say "the broker itself refuses the
        # second copy", and that is only true when the close carries the
        # same reference the first one did.
        kw = {}
        try:
            import inspect
            if "client_order_id" in inspect.signature(closer).parameters:
                kw["client_order_id"] = client_order_id
        except (TypeError, ValueError):  # a builtin or a mock
            kw = {}
        return closer(pid, symbol, float(qty), **kw)

    why = ("the row carries no broker position id" if not pid
           else "the adapter carries no close_position")
    log.error("venue_close: %s does not net an opposite order and %s — "
              "NOTHING has been sent for %s, because an opposite order here "
              "OPENS a second position rather than closing this one",
              type(client).__name__, why, symbol)
    raise RuntimeError(
        f"this venue needs a position id to close and {why} — an opposite "
        f"market order would open a second position")
