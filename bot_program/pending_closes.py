"""Book AssetBotTrade exits from the broker, and drain the ones that stick.

Two jobs, in one module because they are the same problem seen twice.

**Booking an exit.** ``resolve_exit_fill`` turns a broker close response into
the price and the quantity to record. All three close paths — the bot's own
``AssetBot._close_trade``, the kill switch, and the retry loop below — go
through it, so a stop-out is booked the same way whichever of them fired.
The entry path already reads the fill back off the broker (``avgPrice`` /
``executedQty``); this is that same read on the way out. Without it every
exit is recorded at the mark the bot happened to see BEFORE the order, which
makes exit slippage invisible in ``realized_r`` and in every expectancy above
it — and exits are where slippage lives, because stop-outs fire into fast
one-sided markets.

**Draining CLOSE_PENDING.** A CLOSE_PENDING AssetBotTrade means the bot
decided to flatten but the position is **still open at the broker** — the
most dangerous state in the system, and the one the old code hid by marking
the row CLOSED regardless. A row gets there three ways: the broker rejected
the close, the broker only PARTLY filled it, or the broker accepted it and
had not printed it yet. This module resubmits on a 5-minute cadence, and
resubmits the RESIDUAL rather than the whole position — after cancelling any
order the previous attempt left working, because two live closes for one
position is how a flatten becomes a naked reverse.
A row leaves CLOSE_PENDING only when the broker accepts the close (-> CLOSED,
graded) or when reconciliation observes the position is genuinely gone.

Escalation: after `ALERT_AFTER_ATTEMPTS` failures the user is alerted again
(a stranded live position needs human eyes, not silent retries).
"""
from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Optional

from django.utils import timezone

logger = logging.getLogger(__name__)

# Alert again after this many consecutive failed retries.
ALERT_AFTER_ATTEMPTS = 3
# Stop resubmitting after this many failures. A close that can never succeed
# (delisted symbol, revoked credentials, closed account) must not fire a live
# market order every 5 minutes forever, nor storm the alert channel; the row
# moves to ERROR for a human instead.
MAX_RETRY_ATTEMPTS = 12


# ── shared exit booking ─────────────────────────────────────────────────
#
# Metadata keys the close paths write. Spelled once here because three
# modules write them and anything reading the ledger has to agree on them.
EXIT_FILL_SOURCE_KEY = "exit_fill_source"
CLOSE_FILLS_KEY = "close_fills"
CLOSE_FILLED_QTY_KEY = "close_filled_qty"
CLOSE_RESIDUAL_QTY_KEY = "close_residual_qty"
CLOSE_QTY_ASSUMED_KEY = "close_qty_assumed"
# The close order the broker accepted but had not finished when we last
# looked, and its id. The retry loop cancels that order before sending
# another, so one flatten never becomes two.
CLOSE_ORDER_WORKING_KEY = "close_order_working"
CLOSE_WORKING_ORDER_ID_KEY = "close_working_order_id"

# What `exit_fill_source` can say, and what each answer means:
#   broker — every unit was booked at a price the broker reported filling at.
#   mark   — at least one unit was booked at OUR mark, because the broker
#            reported no fill price. The exit price is an ASSUMPTION, and any
#            R computed from it is an assumption too.
#   paper  — a paper venue. There is no broker fill to read; `paper_fill_price`
#            charged the adverse half of the modelled round trip instead.
# `mark` and `paper` are both "not a real fill", but only `mark` is a data
# quality problem — hence two words rather than one.
EXIT_SOURCE_BROKER = "broker"
EXIT_SOURCE_MARK = "mark"
EXIT_SOURCE_PAPER = "paper"

# AssetBotTrade.exit_price is DecimalField(decimal_places=8). A blended fill
# price is a division and would otherwise carry 20+ digits into the column.
EXIT_PRICE_QUANTUM = Decimal("0.00000001")

# A close counts as complete when the residual is under the dust line: small
# enough to be the broker's own rounding rather than a position. "10" and
# "9.999999999" differ by a rounded print, not by something still held, and a
# row stranded in CLOSE_PENDING over that would fire a live market order every
# five minutes for a size no venue will accept.
#
# The line is ABSOLUTE and per asset class, because reporting precision is a
# count of decimal places rather than a share of the order. A proportional
# band gets the large sizes wrong in the direction that costs money: 0.1% of a
# 120,000 DOGE close is 120 DOGE, above both Binance's minQty and its
# MIN_NOTIONAL — a real, tradeable position, written off as rounding.
DUST_QTY_BY_CLASS = {
    # Binance prints base quantity to 8dp and no LOT_SIZE stepSize is finer,
    # so a residual in the last printed place cannot be ordered.
    "crypto": Decimal("0.00000001"),
    # Alpaca prints filled_qty to 9dp but will not trade less than 0.001 of a
    # share, so a millionth of a share can be neither held nor closed.
    "stock": Decimal("0.000001"),
    # OANDA prints units to 4dp and trades whole units: a genuine forex
    # residual is at least 1 unit, four orders of magnitude above this.
    "forex": Decimal("0.0001"),
    # Contracts are integers at every venue, so a genuine options residual is
    # at least one whole contract.
    "options": Decimal("0.0001"),
}
# An asset class with no wired venue yet gets the tightest line rather than
# the loosest. Calling a real residual dust hides a live position from every
# sweep permanently; calling dust a residual costs bounded retries and one
# operator alert, so the error we can afford is the second one.
DUST_QTY_UNKNOWN = Decimal("0.00000001")

# Statuses that mean the order is FINISHED — it will fill nothing more. A
# reported quantity next to one of these is a measurement. Anything else is
# what has printed SO FAR: Alpaca answers `accepted` with filled_qty 0 for a
# market close that its 3-second poll did not see fill.
TERMINAL_ORDER_STATUSES = frozenset({
    "FILLED", "CANCELED", "CANCELLED", "EXPIRED", "REJECTED", "DUPLICATE",
    "DONE_FOR_DAY", "REPLACED", "STOPPED", "SUSPENDED", "INACTIVE", "ERROR",
})


def dust_qty(asset_class) -> Decimal:
    """Largest residual that is broker rounding rather than a position."""
    return DUST_QTY_BY_CLASS.get(str(asset_class or "").lower(),
                                 DUST_QTY_UNKNOWN)


def _decimal(raw) -> Optional[Decimal]:
    """Parse a broker's number, or None when it is not one.

    None means NOT MEASURED and every caller here treats it that way — the
    one thing this must never do is turn an absent field into a confident 0.
    """
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return value if value.is_finite() else None


def _quantize(price: Decimal) -> Decimal:
    """Snap a price to the column's 8 decimal places."""
    try:
        return price.quantize(EXIT_PRICE_QUANTUM)
    except (InvalidOperation, ValueError):
        # Absurd magnitude. Hand back the real value and let the DB layer
        # complain about it rather than substituting a rounded fiction.
        return price


def broker_exit_price(result) -> Optional[Decimal]:
    """Average price the broker says the close filled at, or None.

    `avgPrice` is the field Alpaca, OANDA, IBKR and PaperTrader all fill in,
    and it is the same field the ENTRY path prefers over the ticker. Binance
    spot alone reports no average: it returns the quote-currency total and
    the base quantity, whose ratio IS the average fill. Without that second
    branch every live crypto exit would fall back to the mark and the whole
    asset class would report zero exit slippage forever.

    Anything that is not a dict (None, a stub client, a client that returns
    nothing) answers None — unmeasured, never guessed at.
    """
    if not isinstance(result, dict):
        return None
    price = _decimal(result.get("avgPrice"))
    if price is not None and price > 0:
        return price
    filled = _decimal(result.get("executedQty"))
    quote = _decimal(result.get("cummulativeQuoteQty"))
    if filled is not None and quote is not None and filled > 0 and quote > 0:
        return quote / filled
    return None


def broker_filled_qty(result) -> Optional[Decimal]:
    """How much the broker says has filled SO FAR, or None when it did not say.

    A reported number is what has printed at the moment we asked, which is a
    final answer only when the order is finished — see `order_still_working`.
    A reported 0 is therefore "nothing gone yet", which is still a very
    different answer from silence: it says the position is live, where silence
    says nothing at all.
    """
    if not isinstance(result, dict):
        return None
    filled = _decimal(result.get("executedQty"))
    if filled is None or filled < 0:
        return None
    return filled


def order_still_working(result) -> bool:
    """Is this order accepted at the broker but not finished?

    Alpaca's fill poll gives up after 5 × 0.6s and hands back an order that is
    `accepted` with filled_qty 0 — an order that is very much alive and will
    likely print seconds later. Reading that as "the close is dead, send
    another" is how one flatten becomes two: the first order prints while the
    second is in flight and the account ends up short the position it just
    closed.

    Only an EXPLICIT non-terminal status counts. A response carrying no status
    at all is not evidence of a working order, and treating it as one would
    stop the retry loop resubmitting for every client that simply says less.
    """
    if not isinstance(result, dict):
        return False
    status = str(result.get("status") or "").strip().upper()
    return bool(status) and status not in TERMINAL_ORDER_STATUSES


def is_paper_client(client) -> bool:
    """Is this the simulator standing in for a broker?

    `broker_router` hands back PaperTrader whenever credentials are missing or
    a broker library is not installed, so a LIVE row can be handed one. Its
    `market_order` answers `status: FILLED` at a simulated price in exactly
    the shape a real response has — nothing downstream can tell them apart, so
    the exit would be stamped `broker` in precisely the case that flag exists
    to catch, while the real position stays open at the real broker.
    """
    from bot_program.engine.paper_trader import PaperTrader
    return isinstance(client, PaperTrader)


def qty_str(value) -> str:
    """A quantity as a stable string, whatever Decimal it arrived as.

    `str(Decimal)` carries whatever exponent the value happens to hold, and
    a quantity read back from the DB carries the column's eight decimal
    places while the same number computed in memory does not — so the SAME
    residual was written as "4" on one path and "4.00000000" on another.
    Both parse back identically, but they are compared as strings by
    anything reading the metadata, and a reader cannot be expected to know
    which path wrote the row.

    `normalize()` alone would answer "1E+3" for a thousand units; the `f`
    format is what keeps it a plain decimal string.
    """
    if value is None:
        return ""
    try:
        return format(Decimal(value).normalize(), "f")
    except (InvalidOperation, TypeError, ValueError):
        return str(value)


def residual_qty(trade) -> Decimal:
    """How much of `trade` is still open at the broker.

    `trade.qty` minus whatever an earlier close attempt actually filled.
    Resubmitting the full size after a partial fill would sell units we no
    longer hold, which does not close anything — it opens a position the
    other way.
    """
    qty = _decimal(trade.qty) or Decimal(0)
    filled = _decimal((trade.metadata or {}).get(CLOSE_FILLED_QTY_KEY))
    if filled is None or filled <= 0:
        return qty
    return max(Decimal(0), qty - filled)


def paper_exit_fill(trade, price: Decimal) -> dict:
    """A paper venue's exit, in the same shape a broker's comes back in.

    A paper trade has no broker fill to read back, so there is nothing to
    prefer over `price` and nothing that can be partly filled: the caller has
    already charged the adverse half-spread through `paper_fill_price`, and
    that IS the paper venue's slippage model. Stamped `paper` rather than
    `mark` so a ledger reader can tell a modelled fill from a live exit whose
    price had to be assumed.
    """
    booked = _quantize(_decimal(price) or Decimal(0))
    return {
        "price": booked,
        "source": EXIT_SOURCE_PAPER,
        "filled_qty": _decimal(trade.qty),
        "residual_qty": Decimal(0),
        "complete": True,
        "metadata": {EXIT_FILL_SOURCE_KEY: EXIT_SOURCE_PAPER},
    }


def resolve_exit_fill(trade, result, *, mark) -> dict:
    """What a LIVE close actually got — price AND quantity — from the broker.

    Mirrors the entry path: prefer what the broker reports, fall back to the
    mark, and record which one was used. Returns::

        {"price":        Decimal — book this as exit_price
         "source":       "broker" | "mark"
         "filled_qty":   Decimal — cumulative filled across every attempt
         "residual_qty": Decimal — still live at the broker (0 when complete)
         "complete":     bool    — False means DO NOT mark the row CLOSED
         "metadata":     dict    — merge into trade.metadata}

    `result` is whatever the client returned. Anything that is not a dict —
    None, a stub, a client that hands back nothing — reads as "the broker
    told us nothing": the price falls back to `mark` and the filled quantity
    is ASSUMED to be the rest of the position, flagged `close_qty_assumed`.
    Assuming zero instead would be worse than useless — every close behind a
    client that omits the field would strand in CLOSE_PENDING and the retry
    loop would fire a live market order every five minutes at a broker that
    is already flat.

    A quantity the broker DID report is still only "so far" while the order is
    working (`order_still_working`); that case is recorded rather than closed
    over, so the retry loop cancels the resting order before sending another.

    Partial fills accumulate: each attempt appends a slice to `close_fills`,
    and the booked price is the quantity-weighted mean over all of them. The
    source is `broker` only when EVERY slice came from the broker — one
    assumed slice makes the blended price an assumption too.
    """
    qty = _decimal(trade.qty) or Decimal(0)
    mark_px = _decimal(mark)
    if mark_px is None or mark_px <= 0:
        # Callers all check their mark first; if one ever doesn't, the entry
        # price is the only number on the row that is certainly real. Say so
        # loudly rather than booking a zero.
        logger.error("exit booking for #%s got no usable mark (%r) — falling "
                     "back to the entry price", trade.id, mark)
        mark_px = _decimal(trade.entry_price) or Decimal(0)

    slice_price, slice_source = mark_px, EXIT_SOURCE_MARK
    broker_px = broker_exit_price(result)
    if broker_px is not None:
        slice_price, slice_source = broker_px, EXIT_SOURCE_BROKER

    prior = [f for f in ((trade.metadata or {}).get(CLOSE_FILLS_KEY) or [])
             if isinstance(f, dict)]
    already = sum(((_decimal(f.get("qty")) or Decimal(0)) for f in prior),
                  Decimal(0))

    slice_qty = broker_filled_qty(result)
    qty_assumed = slice_qty is None
    if qty_assumed:
        slice_qty = max(Decimal(0), qty - already)

    fills = list(prior)
    if slice_qty > 0:
        fills.append({"qty": str(slice_qty), "price": str(slice_price),
                      "source": slice_source})

    filled = already + slice_qty
    residual = max(Decimal(0), qty - filled)
    complete = residual <= dust_qty(getattr(trade, "asset_class", ""))

    # An order the broker has accepted but not finished has not measured
    # anything yet: `executedQty` is what printed so far. The entry path reads
    # the same unfinished 0 as "assume the size we asked for", and the two
    # paths agree on the rule underneath that — when the broker has not
    # spoken, ASSUME THE POSITION IS STILL THERE — which on the way in means
    # the requested size and on the way out means nothing gone. Assuming the
    # close filled instead would mark the row CLOSED over a live position,
    # which is the failure this module exists to prevent. What the flag buys
    # is the retry loop's next move: cancel that working order before sending
    # another, rather than stacking a second close on top of it.
    working = (not complete) and order_still_working(result)
    if working:
        logger.warning(
            "close for #%s is still working at the broker (status %r): %s of "
            "%s printed so far — the row stays CLOSE_PENDING until it prints "
            "or the position is observed gone",
            trade.id, result.get("status"), filled, qty)

    if fills and filled > 0:
        notional = sum((((_decimal(f.get("qty")) or Decimal(0))
                         * (_decimal(f.get("price")) or Decimal(0)))
                        for f in fills), Decimal(0))
        price = notional / filled
        source = (EXIT_SOURCE_BROKER
                  if all(f.get("source") == EXIT_SOURCE_BROKER for f in fills)
                  else EXIT_SOURCE_MARK)
    else:
        # Nothing filled at all — the broker accepted the order and reported
        # zero. There is no blended price yet; carry this attempt's numbers so
        # the caller has something to log, and `complete` is already False.
        price, source = slice_price, slice_source

    meta = {
        CLOSE_FILLS_KEY: fills,
        EXIT_FILL_SOURCE_KEY: source,
        CLOSE_FILLED_QTY_KEY: qty_str(filled),
        CLOSE_RESIDUAL_QTY_KEY: qty_str(residual),
        # Written on every attempt, not just the working ones: metadata is
        # MERGED into the row, so a True left behind by an earlier attempt
        # would stop the retry loop resubmitting for the rest of the row's
        # life.
        CLOSE_ORDER_WORKING_KEY: working,
        CLOSE_WORKING_ORDER_ID_KEY: (str(result.get("orderId") or "")
                                     if working else ""),
    }
    if qty_assumed:
        # The price may still be the broker's; it is the SIZE we had to
        # assume. Kept next to the numbers it qualifies, the same way
        # reconcile_asset flags `exit_price_inferred`.
        meta[CLOSE_QTY_ASSUMED_KEY] = True

    return {"price": _quantize(price), "source": source,
            "filled_qty": filled, "residual_qty": residual,
            "complete": complete, "metadata": meta}


# ── the CLOSE_PENDING retry loop ────────────────────────────────────────

def _mark_price(trade, client) -> Decimal:
    """Best-effort current price on the trade's own scale."""
    if trade.asset_class == "options":
        try:
            from bot_program.asset_engine.options_bot import current_premium_for_trade
            return current_premium_for_trade(trade) or trade.entry_price
        except Exception:
            return trade.entry_price
    try:
        tk = client.ticker(trade.symbol) or {}
        last = float(tk.get("lastPrice", 0) or 0)
        if last > 0:
            return Decimal(str(last))
    except Exception:
        pass
    return trade.entry_price


def _pnl(trade, price: Decimal) -> Decimal:
    if trade.side == "BUY":
        pnl = (price - trade.entry_price) * trade.qty
    else:
        pnl = (trade.entry_price - price) * trade.qty
    if trade.asset_class == "options":
        try:
            from bot_program.asset_engine.options_bot import option_pnl_multiplier
            pnl *= option_pnl_multiplier(trade)
        except Exception:
            pass
    elif trade.asset_class == "forex":
        # Same entry-time conversion as every other close path — yen must
        # not land unconverted in the column the USD daily-loss gate sums.
        try:
            from bot_program.asset_engine.forex_bot import forex_usd_multiplier
            pnl *= forex_usd_multiplier(trade)
        except Exception:
            pass
    return pnl


def broker_still_holds(trade, client):
    """Does the broker still report this position? None = cannot tell.

    Resubmitting a market close blindly is how a retry turns into a NEW
    naked position in the opposite direction: if the original close
    actually filled (and only the response was lost), or a protective leg
    fired in between, the account is already flat.
    """
    fn = getattr(client, "get_positions", None)
    if not callable(fn):
        return None
    try:
        positions = list(fn() or [])
    except Exception as e:
        logger.warning("close retry: get_positions() failed for %s: %s",
                       trade.symbol, e)
        return None

    symbols, opt_underlyings, typed = set(), set(), False
    for p in positions:
        sym = (p.get("symbol") if isinstance(p, dict)
               else getattr(p, "symbol", None))
        sec = (p.get("sec_type") if isinstance(p, dict)
               else getattr(p, "sec_type", None))
        if not sym:
            continue
        symbols.add(str(sym).upper())
        if sec is not None:
            typed = True
            if str(sec).upper() == "OPT":
                opt_underlyings.add(str(sym).upper())

    if trade.asset_class == "options":
        occ = str((trade.metadata or {}).get("occ_symbol") or "").upper()
        if occ and occ in symbols:
            return True
        if trade.symbol.upper() in opt_underlyings:
            return True
        # Same rule as reconciliation: without an OCC symbol or a sec-typed
        # feed we cannot see options at all — don't guess.
        return False if (occ or typed) else None
    return trade.symbol.upper() in symbols


def broker_position_qty(trade, client):
    """How much of `trade` the broker still reports, or None when unreadable.

    `broker_still_holds` answers presence; this answers size, and size is
    what a resubmit needs. The retry used to size its replacement order from
    `close_filled_qty` — a number recorded BEFORE the working order was
    cancelled — so anything that printed between the last poll and the
    cancel was sold twice: the residual was computed against a position
    that had already shrunk.

    Asking the broker after the cancel is the only reading that cannot be
    stale, and None (an unreadable or untyped feed) correctly falls back to
    the recorded arithmetic rather than guessing a size.
    """
    fn = getattr(client, "get_positions", None)
    if not callable(fn):
        return None
    try:
        positions = list(fn() or [])
    except Exception as e:  # noqa: BLE001 — an unreadable book is not a crash
        logger.warning("close retry: get_positions() failed for %s: %s",
                       trade.symbol, e)
        return None

    occ = str((trade.metadata or {}).get("occ_symbol") or "").upper()
    want = {trade.symbol.upper()} | ({occ} if occ else set())
    for p in positions:
        sym = (p.get("symbol") if isinstance(p, dict)
               else getattr(p, "symbol", None))
        if not sym or str(sym).upper() not in want:
            continue
        for key in ("qty", "quantity", "position", "size"):
            raw = (p.get(key) if isinstance(p, dict) else getattr(p, key, None))
            amount = _decimal(raw)
            if amount is not None:
                # Absolute: a short is reported negative and the close order
                # is sized in units, not in direction.
                return abs(amount)
        return None

    # The symbol is not in the book the broker just handed us. That is a
    # MEASUREMENT — zero held — not a failure to read, and conflating the two
    # costs an order: a close that finished while we were cancelling its
    # predecessor would report None, the residual would stay at its pre-cancel
    # value, and a full-size market order would go out against a flat account.
    #
    # `broker_still_holds` owns the one case where absence really is unknown:
    # an options row with no OCC symbol and an untyped feed cannot be seen at
    # all, and it answers None there. Deferring to it keeps that judgement in
    # one place instead of two that can drift.
    return Decimal(0) if broker_still_holds(trade, client) is False else None


def _submit_close(trade, client):
    """Resubmit the broker close for whatever is still open.

    Raises on failure. Returns the broker's response so the caller can book
    the exit at the fill it reports instead of at the current mark.
    """
    from bot_program.engine.idempotency import make_client_order_id

    qty = residual_qty(trade)
    if qty <= 0:
        raise RuntimeError(
            f"trade {trade.id} has nothing left to close (already filled "
            f"{(trade.metadata or {}).get(CLOSE_FILLED_QTY_KEY)!r} of "
            f"{trade.qty}) — refusing to send an order that would open a "
            f"reverse position")

    # Stable across retries of the SAME size (unlike a minute bucket), so a
    # broker that dedups on client order id rejects a duplicate close instead
    # of opening a reverse position. The size is part of that identity
    # because a retry of a smaller RESIDUAL after a partial fill is a
    # genuinely different order — deduping it away would leave the remainder
    # live at the broker forever.
    client_order_id = make_client_order_id(
        config_id=trade.config_id, symbol=trade.symbol,
        signal_id=str(trade.id), intent="EXIT",
        bar_ts=f"retry:{qty:.8f}",
    )
    if trade.asset_class == "options":
        if qty != (_decimal(trade.qty) or qty):
            # submit_option_close closes trade.qty contracts — the WHOLE
            # position — because it has no size argument. Calling it for a
            # residual would sell contracts we no longer hold. Fail loudly:
            # the caller's escalation tells the operator to close the
            # remainder at the broker, which is the only safe answer until
            # the option close path can take a size.
            raise RuntimeError(
                f"options trade {trade.id} was only partly closed ({qty} of "
                f"{trade.qty} contracts still open) and the option close path "
                f"cannot submit a residual — close the remainder manually at "
                f"the broker")
        from bot_program.asset_engine.options_bot import submit_option_close
        return submit_option_close(client, trade,
                                   client_order_id=client_order_id)
    close_side = "SELL" if trade.side == "BUY" else "BUY"
    return client.market_order(trade.symbol, close_side, float(qty),
                               client_order_id=client_order_id)


def _cancel_working_close(trade, client) -> bool:
    """Take the previous attempt's still-working close off the book, if any.

    True means it is safe to send another close: either nothing was working,
    or the broker confirmed the cancel. Sending one on top of a live close
    order is how one flatten becomes two — the resting order prints a second
    later and the account is now short the position it just closed.
    """
    meta = trade.metadata or {}
    if not meta.get(CLOSE_ORDER_WORKING_KEY):
        return True
    order_id = str(meta.get(CLOSE_WORKING_ORDER_ID_KEY) or "")
    cancel = getattr(client, "cancel_order", None)
    if not order_id or not callable(cancel):
        return False
    try:
        cancelled = cancel(order_id)
    except Exception as e:
        logger.warning("close retry: cancelling working close %s for #%s "
                       "failed: %s", order_id, trade.id, e)
        return False
    # A client answering False usually means the order is already off the book
    # — filled, or cancelled by someone else. Either way we did not confirm
    # it, and the next beat re-reads the position before doing anything, so
    # waiting costs one cycle and stacking costs a reverse position.
    if cancelled is False:
        return False

    # Clear the flag the moment the order is off the book, not when the
    # replacement is booked. If the resubmit below then fails, this row must
    # come back next beat able to try again — leaving the flag set would make
    # every later attempt try to cancel an order that no longer exists and
    # refuse to send anything until the retry ceiling ran out.
    logger.info("close retry: cancelled working close %s on #%s before "
                "resubmitting", order_id, trade.id)
    trade.metadata = {**(trade.metadata or {}),
                      CLOSE_ORDER_WORKING_KEY: False,
                      CLOSE_WORKING_ORDER_ID_KEY: ""}
    trade.save(update_fields=["metadata"])
    return True


def _reconcile_filled_against_broker(trade, client) -> None:
    """Trust the broker's remaining size over our recorded fill, if we can read it.

    Called immediately after a confirmed cancel. The recorded
    `close_filled_qty` is a snapshot from before the cancel, and a market
    order can print in that gap — so the residual derived from it can be
    larger than what is actually left, and the replacement order would sell
    units the account no longer has. That does not close anything; it opens
    a position the other way, which is the one outcome this whole module
    exists to prevent.

    Silent no-op when the broker cannot be read: an unreadable book is a
    reason to keep the arithmetic we have, never to invent a size.

    THE REVISION IS WRITTEN AS A FILL SLICE, not only as the cached total.
    `close_fills` is the ledger and `close_filled_qty` is a sum of it —
    `resolve_exit_fill` RE-DERIVES the cumulative fill by adding the slices
    up, so a total revised on its own is discarded by the very next booking
    and the phantom residual comes straight back. Correcting the cache
    without correcting the ledger it is a cache of fixes nothing.

    The reconciled units have no price the broker handed us — they printed
    while we were not looking — so the slice is booked at the mark and
    sourced as such, which correctly degrades the blended exit's provenance
    to "mark" rather than letting it claim a broker fill it never saw.
    """
    remaining = broker_position_qty(trade, client)
    if remaining is None:
        return
    qty = _decimal(trade.qty) or Decimal(0)
    implied_filled = max(Decimal(0), qty - remaining)
    meta = dict(trade.metadata or {})
    prior = [f for f in (meta.get(CLOSE_FILLS_KEY) or [])
             if isinstance(f, dict)]
    # Measured against the LEDGER, because the ledger is what the next
    # booking will read. Comparing against the cached total would let a
    # stale cache decide whether to correct the ledger.
    recorded = sum(((_decimal(f.get("qty")) or Decimal(0)) for f in prior),
                   Decimal(0))
    # Only ever revise the filled quantity UPWARD. A broker briefly reporting
    # a larger position than we believe (a settlement lag, a second position
    # in the same symbol opened by hand) must not talk us into re-selling
    # what we already sold.
    if implied_filled <= recorded:
        return

    delta = implied_filled - recorded
    mark = _mark_price(trade, client)
    mark_px = _decimal(mark) or _decimal(trade.entry_price) or Decimal(0)
    logger.info("close retry: broker shows %s of %s left on #%s — booking the "
                "%s that printed in the cancel window at the mark %s",
                remaining, qty, trade.id, delta, mark_px)
    prior.append({"qty": qty_str(delta), "price": str(mark_px),
                  "source": EXIT_SOURCE_MARK, "reconciled": True})
    meta.update({
        CLOSE_FILLS_KEY: prior,
        CLOSE_FILLED_QTY_KEY: qty_str(implied_filled),
        CLOSE_RESIDUAL_QTY_KEY: qty_str(remaining),
        "close_filled_reconciled_at": timezone.now().isoformat(),
    })
    trade.metadata = meta
    trade.save(update_fields=["metadata"])


def _attempts(trade) -> int:
    return int((trade.metadata or {}).get("close_retry_attempts") or 0)


def _record_attempt(trade, *, ok: bool, error: str = "") -> None:
    meta = dict(trade.metadata or {})
    meta["close_retry_attempts"] = 0 if ok else _attempts(trade) + 1
    meta["close_retry_last_at"] = timezone.now().isoformat()
    if error:
        meta["close_retry_last_error"] = error[:300]
    trade.metadata = meta


def _alert_stranded(trade, attempts: int, error: str) -> None:
    try:
        from alerts.links import page_url
        from alerts.models import Notification
        Notification.objects.create(
            user=trade.config.user, notification_type="bot",
            title=f"⊠ Stranded position: {trade.symbol}",
            body=(f"{trade.asset_class} trade #{trade.id} has failed to close "
                  f"{attempts} times and is STILL OPEN at the broker. "
                  f"Last error: {error[:160]}. Close it manually at the broker "
                  f"if this persists."),
            # The body names the trade by number and the alert wants the
            # operator acting on it now — landing them on the full fill
            # history to search for #4127 is the wrong page in an emergency.
            url=page_url("forensics_detail", trade.id) or "/eye/fills/",
        )
    except Exception as e:
        logger.warning("stranded-position alert failed for #%s: %s", trade.id, e)


def _after_failed_attempt(trade, error: str) -> int:
    """Attempt bookkeeping and escalation, shared by a REJECTED close and a
    partly-filled one.

    Both leave a live position behind the row, so both have to be bounded and
    both have to reach a human — the only difference is the wording. Returns
    the new attempt count.
    """
    attempts = _attempts(trade) + 1
    _record_attempt(trade, ok=False, error=error)
    trade.save(update_fields=["metadata"])
    if attempts >= MAX_RETRY_ATTEMPTS:
        logger.error("close retry #%s abandoned after %d attempts",
                     trade.id, attempts)
        _give_up(trade, error)
    elif attempts % ALERT_AFTER_ATTEMPTS == 0:
        _alert_stranded(trade, attempts, error)
    return attempts


def _finalise_closed(trade, *, fill: dict, reason: str) -> None:
    """Mark the row CLOSED at `fill` and run the close hooks.

    `fill` comes from `resolve_exit_fill`, so the exit price is the broker's
    own when the broker reported one — a trade that ends here must not get a
    different KIND of exit price than one that closed on the first attempt.
    """
    price = fill["price"]
    trade.exit_price = price
    trade.pnl = _pnl(trade, price)
    trade.metadata = {**(trade.metadata or {}), **fill["metadata"]}
    trade.status = "CLOSED"
    trade.closed_at = timezone.now()
    trade.reason = ((trade.reason or "") + f" | closed:{reason}").strip()[:1000]
    _record_attempt(trade, ok=True)
    trade.save()

    # Grade + audit + tax lots, same as a first-attempt close. Never fatal.
    try:
        from bot_program.bot_grading import grade_bot_trade
        grade_bot_trade(trade)
    except Exception as e:
        logger.warning("close retry grading failed for #%s: %s", trade.id, e)
    try:
        from bot_program.audit import record_trade_close
        record_trade_close(trade.config.user, trade=trade)
    except Exception as e:
        logger.warning("close retry audit failed for #%s: %s", trade.id, e)
    try:
        from bot_program.tax_lots import close_lots_for
        close_lots_for(trade)
    except Exception as e:
        logger.warning("close retry tax_lots failed for #%s: %s", trade.id, e)


def _record_partial(trade, fill: dict) -> None:
    """The broker filled only PART of the close. The row stays CLOSE_PENDING.

    Marking it CLOSED is the quiet version of the failure this whole module
    exists to prevent: the residual stays live at the broker while
    `reconcile_asset` — which only ever scans OPEN and CLOSE_PENDING — has no
    row left to find it on, so nothing watches it again, ever.

    A partial counts as a failed attempt even though it made progress. A
    residual that keeps not filling has to reach the operator alert and the
    MAX_RETRY_ATTEMPTS ceiling instead of firing a live order every five
    minutes forever; the per-class dust line in `dust_qty` is what keeps a
    rounding artefact out of this branch.
    """
    trade.metadata = {**(trade.metadata or {}), **fill["metadata"]}
    trade.status = "CLOSE_PENDING"
    if "partial-close" not in (trade.reason or ""):
        trade.reason = ((trade.reason or "") + " | partial-close").strip()[:1000]
    trade.save(update_fields=["metadata", "status", "reason"])
    _after_failed_attempt(
        trade,
        f"partial close: {fill['residual_qty']} of {trade.qty} still open")


def _give_up(trade, error: str) -> None:
    """Terminal state after MAX_RETRY_ATTEMPTS — stop firing live orders."""
    trade.status = "ERROR"
    trade.reason = ((trade.reason or "")
                    + " | close-abandoned").strip()[:1000]
    trade.save(update_fields=["status", "reason"])
    try:
        from alerts.links import page_url
        from alerts.models import Notification
        Notification.objects.create(
            user=trade.config.user, notification_type="bot",
            title=f"✕ Close abandoned: {trade.symbol}",
            body=(f"{trade.asset_class} trade #{trade.id} failed to close "
                  f"{MAX_RETRY_ATTEMPTS} times and is no longer being retried. "
                  f"Last error: {error[:160]}. Verify and close it manually "
                  f"at the broker."),
            # This trade's own forensics page, not the list of every fill:
            # the retry history the operator needs is already on it.
            url=page_url("forensics_detail", trade.id) or "/forensics/",
        )
    except Exception as e:
        logger.warning("close-abandoned alert failed for #%s: %s", trade.id, e)


def retry_trade_close(trade) -> bool:
    """Retry one CLOSE_PENDING trade. True when it ended CLOSED."""
    from bot_program.engine.broker_router import client_for_symbol

    client = client_for_symbol(trade.config.user, trade.symbol, trade.config)

    # A LIVE row handed the simulator: the router falls back to PaperTrader
    # when credentials are missing or a broker library is not installed. Its
    # simulated FILLED response would book this live position at an invented
    # price stamped `broker`, while the position it claims to have closed
    # stays open at a broker we cannot reach. Count the attempt so the
    # operator alert still fires, and send nothing. (A paper row is a
    # different thing entirely — PaperTrader IS its venue — and the sweep
    # never sends one here anyway.)
    if not trade.paper and is_paper_client(client):
        msg = ("broker unavailable (PaperTrader fallback) — no close was "
               "sent and the position is still open at the broker")
        logger.error("close retry #%s for %s: %s", trade.id, trade.symbol, msg)
        _after_failed_attempt(trade, msg)
        return False

    # If the broker says the position is already gone, the original close
    # (or a protective leg) did fill — finalise instead of sending another
    # order that would open a naked reverse position.
    if broker_still_holds(trade, client) is False:
        logger.info("close retry: broker no longer holds #%s (%s) — "
                    "finalising without a new order", trade.id, trade.symbol)
        # No order was sent, so there is no fill to read: the remainder is
        # booked at the current mark and flagged as such.
        _finalise_closed(
            trade,
            fill=resolve_exit_fill(trade, None,
                                   mark=_mark_price(trade, client)),
            reason="RETRY_ALREADY_FLAT")
        return True

    # The previous attempt may have left an order alive at the broker (an
    # accepted market close that had not printed when we read it). Clear it
    # before adding another, or wait a beat if we cannot.
    if not _cancel_working_close(trade, client):
        # "Not confirmed" is not the same as "still resting", and the
        # difference decides whether waiting is prudence or paralysis:
        # AlpacaClient.cancel_order returns False for 404/422 — its own
        # comment reads "already gone or not cancelable; treat as done" —
        # so an order that is definitively OFF the book looked identical to
        # one we failed to cancel. The row then refused to resubmit on every
        # beat until the retry ceiling ran out, roughly an hour of a live
        # position sitting open because a cancel succeeded too well.
        #
        # So ask the position instead of reading the cancel's tea leaves. If
        # the broker no longer holds it, the close filled and the next block
        # finalises it. If it does still hold it, re-checking here changes
        # nothing about the risk of stacking, so waiting remains correct.
        if broker_still_holds(trade, client) is False:
            logger.info("close retry: cancel unconfirmed on #%s but the "
                        "broker no longer holds %s — the working close "
                        "filled; finalising", trade.id, trade.symbol)
            _finalise_closed(
                trade,
                fill=resolve_exit_fill(trade, None,
                                       mark=_mark_price(trade, client)),
                reason="RETRY_WORKING_CLOSE_FILLED")
            return True
        msg = ("the previous close is still working at the broker and could "
               "not be cancelled — refusing to stack a second close on it")
        logger.error("close retry #%s for %s: %s", trade.id, trade.symbol, msg)
        _after_failed_attempt(trade, msg)
        return False

    # The cancel landed, so whatever that order had filled is final — and it
    # may have filled MORE between the last poll and the cancel. Re-read the
    # size from the broker and reconcile the recorded fill against it, or the
    # replacement order is sized against a position that no longer exists at
    # that size and oversells the difference.
    _reconcile_filled_against_broker(trade, client)

    try:
        result = _submit_close(trade, client)
    except Exception as e:
        attempts = _attempts(trade) + 1
        logger.error("close retry #%s failed for trade %s (attempt %d): %s",
                     trade.id, trade.symbol, attempts, e)
        _after_failed_attempt(trade, str(e))
        return False

    fill = resolve_exit_fill(trade, result, mark=_mark_price(trade, client))
    if not fill["complete"]:
        logger.error("close retry #%s for %s filled %s of %s — %s is still "
                     "open at the broker; staying CLOSE_PENDING",
                     trade.id, trade.symbol, fill["filled_qty"], trade.qty,
                     fill["residual_qty"])
        _record_partial(trade, fill)
        return False

    _finalise_closed(trade, fill=fill, reason="RETRY")
    logger.info("close retry succeeded for trade #%s (%s)", trade.id, trade.symbol)
    return True


def retry_all_pending_closes() -> dict:
    """Retry every CLOSE_PENDING live trade. Paper rows never reach this
    state (they have no broker order to fail)."""
    from bot_program.models import AssetBotTrade

    qs = (AssetBotTrade.objects
          .filter(status="CLOSE_PENDING", paper=False)
          .select_related("config", "config__user"))
    out = {"pending": 0, "closed": 0, "still_pending": 0}
    for trade in qs:
        out["pending"] += 1
        try:
            if retry_trade_close(trade):
                out["closed"] += 1
            else:
                out["still_pending"] += 1
        except Exception as e:
            logger.exception("close retry crashed for #%s: %s", trade.id, e)
            out["still_pending"] += 1
    return out
