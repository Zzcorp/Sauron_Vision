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
    # THE ROW'S OWN CARRIER, BEFORE ANYTHING IS SENT. All three callers
    # rebuild `client` from TODAY's primary-for flag, and until now nothing
    # on the send side compared it with the venue that carried the row
    # (metadata["broker"], stamped by AssetBot.venue_stamps): reconcile and
    # the drain refuse a MISS at the wrong venue, but a moved checkbox still
    # sent the close itself elsewhere — an opposite order at a venue that
    # nets OPENS a position there, the row books CLOSED at that fill, and
    # the real position stays live where it was carried. Three states: a
    # row with no carrier, or a client the adapter map does not know,
    # refuses nothing — only two KNOWN and DIFFERENT names do. The raise
    # lands where this function's other raise lands: CLOSE_PENDING for the
    # engine, a recorded failure for the kill switch and the drain.
    from bot_program.engine.capabilities import adapter_key
    _meta = (trade.metadata
             if isinstance(getattr(trade, "metadata", None), dict) else {})
    carried = str(_meta.get("broker") or "")
    now_at = adapter_key(client)
    if carried and now_at and carried != now_at:
        log.error("venue_close: %s was carried by %s and the router now "
                  "answers %s — NOTHING has been sent, because a close at "
                  "the wrong venue is an opening order there",
                  symbol, carried, now_at)
        raise RuntimeError(
            f"this row was carried by {carried} and the router now answers "
            f"{now_at} — a close sent here would open a position at the "
            f"wrong venue; move the flag back or close it at {carried}")
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
        # AND THE OPEN ORDER'S ID where the adapter takes one. On eToro the
        # close order it answers with is findable nowhere (measured
        # 2026-09-23); the proof of the close is the OPEN order's execution
        # state, read by the id both lanes store as
        # AssetBotTrade.broker_order_id. Handed over here, once, so
        # EtoroTrader.close_position can prove what it sent; an adapter whose
        # signature has no seat for it is given nothing (a MagicMock's
        # signature is (*args, **kwargs) — no seat), and a row with no id
        # closes as before: PENDING, proven later by the drain.
        kw = {}
        try:
            import inspect
            params = inspect.signature(closer).parameters
            if "client_order_id" in params:
                kw["client_order_id"] = client_order_id
            if "open_order_id" in params:
                kw["open_order_id"] = str(
                    getattr(trade, "broker_order_id", "") or "")
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
