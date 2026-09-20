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

#: Statuses that mean the venue DOES NOT KNOW whether the order exists.
#: Deliberately NOT part of TERMINAL_ORDER_STATUSES above: an order nobody
#: has resolved is not finished, and calling it finished would let this loop
#: read it as dead and send a second close beside it. Saxo answers 202
#: TradeNotCompleted when its broker leg has not confirmed within sixty
#: seconds, and its adapter reports that as UNKNOWN with the note "this order
#: may exist — it is not retried".
IN_DOUBT_ORDER_STATUSES = frozenset({"UNKNOWN"})

#: The row's own note that a close MAY already be live at the broker. The
#: SAME key AssetBot._close_trade writes when the close request does not come
#: back, so the bot path and this loop read one flag rather than two that can
#: disagree.
CLOSE_IN_DOUBT_KEY = "close_in_doubt"


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


def order_in_doubt(result) -> bool:
    """Did the venue refuse to say whether this order exists at all?

    A DIFFERENT question from `order_still_working`, and the difference
    decides whether this module may cancel and resend. A working order can be
    taken off the book and replaced, and the cancel is the proof. An in-doubt
    order cannot be: the venue answered 202 for the PLACEMENT, so "cancelled"
    and "no such order" are the same sentence about a broker leg that may
    still print — and sending another close beside it is the second live
    close for one intent that this module exists to prevent.

    Two spellings, because one 202 reaches us two ways: an explicit inDoubt
    flag (SaxoTrader.close_position) and the UNKNOWN status
    (SaxoTrader.market_order, which is what this loop calls).
    """
    if not isinstance(result, dict):
        return False
    if result.get("inDoubt"):
        return True
    status = str(result.get("status") or "").strip().upper()
    return status in IN_DOUBT_ORDER_STATUSES


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
    if order_in_doubt(result):
        # THE VENUE WOULD NOT SAY WHETHER THIS CLOSE EXISTS. Written here,
        # where the answer arrives, because the pass that learns of the doubt
        # is never the pass that would resend.
        meta[CLOSE_IN_DOUBT_KEY] = {
            "at": timezone.now().isoformat(),
            "order_id": str(result.get("orderId") or ""),
            "reference": str(result.get("reference") or ""),
            "status": str(result.get("status") or ""),
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

def _mark_price(trade, client) -> Optional[Decimal]:
    """Current price on the trade's own scale, or None when there isn't one.

    None, never the entry price. Two of this module's callers book the mark
    AS the exit price — the paths where the broker is already flat and there
    is no fill to read — so an entry price handed back here does not degrade
    gracefully, it invents a scratch: exit == entry, pnl 0.00, realized_r
    0.0. A stop-out that actually cost 450 dollars then reads as flat, which
    the 24h daily-loss gate sums as nothing and the promotion track record
    counts as a break-even trade. `AssetBot._mark_price` has always answered
    None for the same question, and manage_positions skips the trade rather
    than mark it against a price nobody quoted; this now agrees with it.
    """
    if trade.asset_class == "options":
        try:
            from bot_program.asset_engine.options_bot import current_premium_for_trade
            return current_premium_for_trade(trade) or None
        except Exception:
            return None
    try:
        tk = client.ticker(trade.symbol) or {}
        last = float(tk.get("lastPrice", 0) or 0)
        if last > 0:
            return Decimal(str(last))
    except Exception:
        pass
    return None


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


# ── what the broker holds, in three states ──────────────────────────────
#
# HELD / FLAT / UNKNOWN, never two of them collapsed. A live market order is
# sized off this reading, so each state carries its own consequence: HELD
# sizes the resubmit, FLAT lets the row be booked without sending anything,
# and UNKNOWN sends nothing AND books nothing.
POS_HELD = "held"
POS_FLAT = "flat"
POS_UNKNOWN = "unknown"

#: A position row's side, in the two dialects the wired venues speak:
#: BUY/SELL (IBKR, OANDA, eToro, Saxo, PaperTrader) and LONG/SHORT (Alpaca
#: answers side "long"). A reader that knew only the first would read every
#: Alpaca short as "not this row's side" — that is, as FLAT — and book a
#: live position CLOSED.
_LONG_SIDES = frozenset({"BUY", "LONG"})
_SHORT_SIDES = frozenset({"SELL", "SHORT"})

#: Below this, a netted size is the residue of decimal arithmetic rather
#: than a position. Fractional venues trade to eight places, so the floor
#: sits under the smallest real size any of them will accept.
_POSITION_DUST = Decimal("0.00000001")


def _row_field(p, *names):
    """One field off a position row, dict or object, or None."""
    for name in names:
        value = (p.get(name) if isinstance(p, dict)
                 else getattr(p, name, None))
        if value is not None:
            return value
    return None


def _position_size_and_side(p):
    """(size, direction) for one position row; either may be None.

    `size` is ABSOLUTE, and None means the row named a symbol and no usable
    quantity — presence without a number, which has to stay unmeasured: a 0
    there reads as "nothing held" and a guess sizes a live order.
    `direction` is +1 long, -1 short, None when the feed names no side.

    A NEGATIVE quantity is the venue signing the direction itself (Alpaca
    hands back "-10" for a short) and it wins over the side word, which may
    be absent or spelled in the other dialect.
    """
    amount = _decimal(_row_field(p, "qty", "quantity", "position", "size",
                                 "positionAmt"))
    word = str(_row_field(p, "side") or "").strip().upper()
    direction = (Decimal(1) if word in _LONG_SIDES
                 else Decimal(-1) if word in _SHORT_SIDES else None)
    if amount is not None and amount < 0:
        direction = Decimal(-1)
    return (None if amount is None else abs(amount)), direction


def _unknown_exposure(why: str) -> dict:
    return {"state": POS_UNKNOWN, "qty": None, "ambiguous": True, "why": why}


def _siblings_claim(trade) -> bool:
    """Does another live row of this user claim the same symbol and side?

    The gate AssetBot._broker_still_holds applies, for the same reason: the
    account total cannot say whose units are whose, so a resubmit sized off
    it would sell units belonging to another row. WORKING rows are excluded —
    their quantity sits on the row while the order is still queued, and the
    broker holds nothing for them.
    """
    try:
        from bot_program.models import AssetBotTrade
        others = (AssetBotTrade.objects
                  .filter(config__user=trade.config.user, symbol=trade.symbol,
                          side=trade.side, paper=False,
                          asset_class=trade.asset_class,
                          status__in=("OPEN", "CLOSE_PENDING"))
                  .exclude(pk=trade.pk))
        return any(not (t.metadata or {}).get("entry_working") for t in others)
    except Exception as e:  # noqa: BLE001 — unreadable siblings are a doubt
        logger.warning("close retry: could not check sibling rows for %s: %s",
                       trade.symbol, e)
        return True


def _options_exposure(trade, positions) -> dict:
    """The options reading — the presence test, unchanged in substance.

    An option CANNOT be netted off a position list: IBKR reports every option
    under its UNDERLYING symbol with no strike, expiry or right, so two rows
    that look identical here can be different instruments and their sizes
    must never be added up. Presence answers HELD with no size, which makes
    the caller fall back to its own recorded arithmetic.
    """
    symbols, opt_underlyings, typed = set(), set(), False
    for p in positions:
        sym = _row_field(p, "symbol")
        sec = _row_field(p, "sec_type")
        if not sym:
            continue
        symbols.add(str(sym).upper())
        if sec is not None:
            typed = True
            if str(sec).upper() == "OPT":
                opt_underlyings.add(str(sym).upper())
    occ = str((trade.metadata or {}).get("occ_symbol") or "").upper()
    if (occ and occ in symbols) or trade.symbol.upper() in opt_underlyings:
        return {"state": POS_HELD, "qty": None, "ambiguous": False, "why": ""}
    # Same rule as reconciliation: without an OCC symbol or a sec-typed feed
    # we cannot see options at all — don't guess.
    if occ or typed:
        return {"state": POS_FLAT, "qty": Decimal(0), "ambiguous": False,
                "why": ""}
    return _unknown_exposure("this feed names no option contracts, so an "
                             "options position cannot be seen at all")


def broker_exposure(trade, client) -> dict:
    """{"state", "qty", "ambiguous", "why"} — what the broker holds for THIS row.

    The reading the whole retry loop turns on, and it is deliberately timid.
    Its predecessor asked "is this symbol in the book", with no side and no
    size: under Saxo's FifoEndOfDay the CLOSING lot sits Open beside the lot
    it closed until the evening netting, so that answer was "still held" all
    day and the size came off whichever lot Saxo listed first — which can be
    the closing one. remaining then equalled the whole position, nothing was
    counted as filled, and a third full-size market order went out.

    So: netted per side, and ANY of these is UNKNOWN rather than a number —
    an offsetting lot, a row that names the symbol without a usable quantity
    or side, a sibling row of this user claiming the same symbol, or a feed
    that cannot be read at all. UNKNOWN means this module sends nothing and
    books nothing.
    """
    fn = getattr(client, "get_positions", None)
    if not callable(fn):
        return _unknown_exposure("this broker client cannot list positions")
    try:
        positions = list(fn() or [])
    except Exception as e:  # noqa: BLE001 — an unreadable book is not a crash
        logger.warning("close retry: get_positions() failed for %s: %s",
                       trade.symbol, e)
        return _unknown_exposure(f"the position list could not be read ({e})")

    if trade.asset_class == "options":
        return _options_exposure(trade, positions)

    mine = Decimal(1) if str(trade.side).upper() == "BUY" else Decimal(-1)
    want = trade.symbol.upper()
    lots = []
    for p in positions:
        sym = _row_field(p, "symbol")
        if not sym or str(sym).upper() != want:
            continue
        sec = _row_field(p, "sec_type")
        if sec is not None and str(sec).upper() == "OPT":
            # An option under the same underlying symbol is a different
            # instrument, and its size must never join this sum.
            continue
        lots.append(_position_size_and_side(p))

    ours, against = Decimal(0), Decimal(0)
    unmeasured = False          # named, and nothing here could size it
    unsized_against = False     # named, no number, on the OTHER side

    if len(lots) == 1:
        # ONE LOT NEEDS NO SIDE. A direction decides something only when
        # there is another lot to net against, and most feeds sign the
        # quantity rather than naming a side — so demanding one here would
        # read a perfectly ordinary book as unmeasured and stop the
        # reconciliation that removes a phantom residual. A negative quantity
        # is still honoured: _position_size_and_side reads the sign as the
        # direction, and a lone SHORT lot against a long row is the
        # offsetting case below.
        size, direction = lots[0]
        if size is None:
            unmeasured = True
        elif direction is None or direction == mine:
            ours = size
        else:
            against = size
    else:
        for size, direction in lots:
            if size is None:
                # PRESENCE WITHOUT A NUMBER, beside at least one other lot.
                # Unmeasured — and on the OTHER side it is evidence, because
                # read as nothing it leaves `against` at 0 while a real
                # offsetting position is open.
                unmeasured = True
                if direction is not None and direction != mine:
                    unsized_against = True
                continue
            if direction is None:
                # A size with no side, beside other lots: it cannot be
                # attributed to a direction, so this book cannot be netted.
                unmeasured = True
                continue
            if direction == mine:
                ours += size
            else:
                against += size

    if unsized_against:
        return _unknown_exposure(
            "the book holds this symbol on the OTHER side with no usable "
            "quantity — an unmeasured offsetting lot read as nothing is how a "
            "second live close gets sent")
    if against > _POSITION_DUST:
        return _unknown_exposure(
            f"the broker holds {against} of {trade.symbol} on the OTHER side "
            f"as well as {ours} on ours — under end-of-day netting the "
            f"closing lot sits beside the lot it closed until the evening, so "
            f"the book cannot say what is still this row's")
    if ours > _POSITION_DUST and _siblings_claim(trade):
        return _unknown_exposure(
            f"another live row of this user claims {trade.symbol} on the same "
            f"side, so the {ours} in the book cannot be attributed to this row")
    if ours > _POSITION_DUST:
        return {"state": POS_HELD, "qty": ours, "ambiguous": False, "why": ""}
    if unmeasured:
        # The symbol IS in the book and nothing here could size it. Not flat
        # — that would book the row as fully filled — and not ambiguous
        # either: the caller sizes from its own recorded arithmetic, which is
        # what this function answered before it could net at all.
        return {"state": POS_UNKNOWN, "qty": None, "ambiguous": False,
                "why": "the book names this symbol with no usable quantity"}
    return {"state": POS_FLAT, "qty": Decimal(0), "ambiguous": False, "why": ""}


def broker_still_holds(trade, client):
    """Does the broker still report this position? None = cannot tell.

    Resubmitting a market close blindly is how a retry turns into a NEW naked
    position in the opposite direction: if the original close actually filled
    (and only the response was lost), or a protective leg fired in between,
    the account is already flat. The three states of `broker_exposure`, in
    this function's older two-and-a-half shape, for the callers that only
    need presence.
    """
    state = broker_exposure(trade, client)["state"]
    return (True if state == POS_HELD
            else False if state == POS_FLAT else None)


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

    exposure = broker_exposure(trade, client)
    if exposure["state"] == POS_FLAT:
        # The symbol is not in the book the broker just handed us. That is a
        # MEASUREMENT — zero held — not a failure to read, and conflating the
        # two costs an order: a close that finished while we were cancelling
        # its predecessor would report None, the residual would stay at its
        # pre-cancel value, and a full-size market order would go out against
        # a flat account.
        return Decimal(0)
    # HELD carries the size — itself None for a feed that names the symbol and
    # no quantity, and for every options row — and UNKNOWN has no size by
    # definition. Neither may become a 0 here: an unmeasured size read as zero
    # remaining would book the whole position as filled.
    return exposure["qty"] if exposure["state"] == POS_HELD else None


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
    # THROUGH venue_close, never straight to market_order. On eToro an
    # "opposite market order" is an OPENING order — its API separates opening
    # from closing — and on Saxo under FifoEndOfDay it leaves both lots live,
    # so this resubmit used to add a second position while the row booked
    # CLOSED over double exposure. venue_close raises rather than send one,
    # and _after_failed_attempt already knows what to do with a raise.
    from bot_program.engine.venue_close import close_or_refuse
    close_side = "SELL" if trade.side == "BUY" else "BUY"
    return close_or_refuse(trade, client, float(qty), close_side=close_side,
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
    # The QUANTITY is the point here — leaving it wrong oversells the
    # difference on the next attempt — so a missing mark must not abandon the
    # correction. With no price at all the entry price is the only real number
    # on the row; the slice is already stamped `mark`, so the blended exit
    # correctly stops claiming a broker fill.
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


#: How long a close may keep losing the trading session before the operator
#: is told. Not an attempt counter — a stall detector: the drain is supposed
#: to win the session within a tick or two, and if it never does, something
#: is holding it that should not be.
SESSION_BUSY_ALERT_AFTER_MINUTES = 45


def _note_session_busy(trade) -> None:
    """Record a pass that could not even ask, and escalate a long stall.

    Deliberately NOT `_after_failed_attempt`: nothing was sent, so this
    must not move the row toward `_give_up`. It still has to be visible —
    a drain that can never take the session is as stuck as one the broker
    refuses, and silence there is the failure mode this whole module
    exists to prevent.
    """
    from django.utils import timezone as _tz

    meta = dict(trade.metadata or {})
    first = meta.get("close_session_busy_since")
    now = _tz.now()
    if not first:
        meta["close_session_busy_since"] = now.isoformat()
    meta["close_session_busy_at"] = now.isoformat()
    meta["close_session_busy_passes"] = int(
        meta.get("close_session_busy_passes") or 0) + 1
    trade.metadata = meta
    trade.save(update_fields=["metadata"])

    try:
        from datetime import datetime as _dt
        stalled_min = ((now - _dt.fromisoformat(first)).total_seconds() / 60.0
                       if first else 0.0)
    except (TypeError, ValueError):
        stalled_min = 0.0
    if stalled_min < SESSION_BUSY_ALERT_AFTER_MINUTES:
        return
    if meta.get("close_session_busy_alerted"):
        return
    try:
        from bot_program.notifications import notify_staff
        notify_staff(
            title=f"⚠ {trade.symbol}: close blocked by a busy IBKR session",
            body=(f"Trade #{trade.id} has been CLOSE_PENDING for "
                  f"{int(stalled_min)} minutes without a single close being "
                  f"ATTEMPTED: every pass lost the exclusive IBKR trading "
                  f"session to another process. The position is still open "
                  f"at the broker. Check that no process is holding the "
                  f"session (a stuck tick, a stale lease)."),
            url="/positions/")
        meta["close_session_busy_alerted"] = True
        trade.metadata = meta
        trade.save(update_fields=["metadata"])
    except Exception as e:  # noqa: BLE001
        logger.warning("session-busy alert failed for #%s: %s", trade.id, e)


#: How long a row may go on refusing to send a close before the operator is
#: told, and how often the log repeats while it does. A drain that never even
#: ATTEMPTS is as stuck as one the broker refuses, and silence there is the
#: failure this module exists to prevent.
CLOSE_BLOCKED_ALERT_AFTER_MINUTES = 45
CLOSE_BLOCKED_RELOG_MINUTES = 60


def _note_close_blocked(trade, why: str) -> None:
    """Record a pass that deliberately sent NOTHING, and escalate a stall.

    Deliberately NOT `_after_failed_attempt`: nothing was sent and nothing
    was refused, so this must not spend the MAX_RETRY_ATTEMPTS budget. That
    matters, because both things that block here resolve themselves later in
    the day — an offsetting lot nets at the evening netting, an in-doubt
    order gets an answer — and a row driven to ERROR first would be left
    permanently unbooked: no exit price, no pnl, no grade, and "stranded,
    STILL OPEN at the broker" printed about a position that is already flat.

    The log repeats hourly rather than once: a single line at 03:00 about a
    row that is still blocked at noon is a line nobody sees.
    """
    from datetime import datetime as _dt

    meta = dict(trade.metadata or {})
    now = timezone.now()
    first = meta.get("close_blocked_since")
    if not first:
        meta["close_blocked_since"] = now.isoformat()
        first = meta["close_blocked_since"]
    meta["close_blocked_at"] = now.isoformat()
    meta["close_blocked_why"] = str(why)[:300]
    meta["close_blocked_passes"] = int(meta.get("close_blocked_passes") or 0) + 1

    def _minutes_since(stamp):
        try:
            return (now - _dt.fromisoformat(str(stamp))).total_seconds() / 60.0
        except (TypeError, ValueError):
            return None

    said = meta.get("close_blocked_logged_at")
    since_log = _minutes_since(said) if said else None
    if since_log is None or since_log >= CLOSE_BLOCKED_RELOG_MINUTES:
        logger.error("close retry #%s for %s: sending NOTHING — %s",
                     trade.id, trade.symbol, why)
        meta["close_blocked_logged_at"] = now.isoformat()

    stalled = _minutes_since(first)
    if (stalled is not None and stalled >= CLOSE_BLOCKED_ALERT_AFTER_MINUTES
            and not meta.get("close_blocked_alerted")):
        try:
            from bot_program.notifications import notify_staff
            notify_staff(
                title=f"⚠ {trade.symbol}: the close is being held back",
                body=(f"Trade #{trade.id} has been CLOSE_PENDING for "
                      f"{int(stalled)} minutes and every pass has refused to "
                      f"send a close: {why}. NOTHING has been sent — a second "
                      f"order here would reverse the position rather than "
                      f"close it. Read the broker's own position list and "
                      f"order list before acting."),
                url="/positions/")
            meta["close_blocked_alerted"] = True
        except Exception as e:  # noqa: BLE001 — an alert must not block a drain
            logger.warning("close-blocked alert failed for #%s: %s",
                           trade.id, e)
    trade.metadata = meta
    trade.save(update_fields=["metadata"])


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
    # The dashboards hear about a close from push_eye_event and nothing
    # else — and this finaliser never called it. The user's exact story:
    # a live close fails once (the page correctly shows CLOSE_PENDING),
    # the retry — button or the five-minute beat — succeeds, and the
    # position sits on every open page until a manual refresh.
    try:
        from dashboard.consumers import push_eye_event
        push_eye_event(trade.config.user, "fill_close", {
            "trade_id": trade.id, "asset_class": trade.asset_class,
            "symbol": trade.symbol, "side": trade.side,
            "outcome": trade.outcome or "",
            "pnl": str(trade.pnl) if trade.pnl is not None else "0",
        })
    except Exception as e:
        logger.warning("close retry eye push failed for #%s: %s",
                       trade.id, e)
    # Same hole, second channel: a first-attempt close rings
    # notify_bot_fill_close; a retried one never did.
    try:
        from bot_program.notifications import notify_bot_fill_close
        notify_bot_fill_close(
            trade.config.user, asset_class=trade.asset_class,
            symbol=trade.symbol, side=trade.side, qty=trade.qty,
            exit_price=trade.exit_price, pnl=trade.pnl,
            outcome=trade.outcome or "", trade_id=trade.id,
        )
    except Exception as e:
        logger.warning("close retry notify failed for #%s: %s",
                       trade.id, e)


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
    # ERROR leaves every OPEN/CLOSE_PENDING read at once — the pages
    # must re-render the row out now, not at the next slow sweep.
    try:
        from dashboard.consumers import push_eye_event
        push_eye_event(trade.config.user, "close_pending", {
            "trade_id": trade.id, "asset_class": trade.asset_class,
            "symbol": trade.symbol, "abandoned": True,
        })
    except Exception as e:
        logger.warning("close-abandoned eye push failed for #%s: %s",
                       trade.id, e)
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


# How long a flat-at-broker row may wait for a price before the operator is
# told. It is not an error state and it is not stranded — the position is
# gone — but a row that sits CLOSE_PENDING unexplained is its own problem.
MARK_WAIT_ALERT_SECONDS = 3600


def _alert_unpriced(trade) -> None:
    """Tell the operator once an hour that a closed position has no price."""
    meta = dict(trade.metadata or {})
    last = meta.get("unpriced_alert_at")
    now = timezone.now()
    if last:
        try:
            from django.utils.dateparse import parse_datetime
            when = parse_datetime(str(last))
            if when and (now - when).total_seconds() < MARK_WAIT_ALERT_SECONDS:
                return
        except Exception:  # noqa: BLE001
            pass
    meta["unpriced_alert_at"] = now.isoformat()
    trade.metadata = meta
    trade.save(update_fields=["metadata"])
    try:
        from alerts.links import page_url
        from alerts.models import Notification
        Notification.objects.create(
            user=trade.config.user, notification_type="bot",
            title=f"⊙ Closed but unpriced: {trade.symbol}",
            body=(f"{trade.asset_class} trade #{trade.id} is FLAT at the "
                  f"broker — nothing is live — but no price could be read to "
                  f"book the exit, so the row stays CLOSE_PENDING rather than "
                  f"record the trade as a scratch. It will close itself as "
                  f"soon as a quote returns."),
            url=page_url("forensics_detail", trade.id) or "/eye/fills/",
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("unpriced-close alert failed for #%s: %s", trade.id, e)


def _finalise_flat(trade, client, *, reason: str) -> bool:
    """Book a position the broker no longer holds. False when we cannot.

    Nothing was sent on this path, so there is no fill to read: the mark IS
    the exit price. With no mark there is nothing to book, and the old
    fallback — the entry price — recorded a stop-out that cost real money as
    a scratch: exit == entry, pnl 0.00, realized_r 0.0. That zero is
    invisible to the 24h daily-loss gate, which is the number the operator
    trusts to stop the day, and it enters the promotion track record as a
    break-even trade that never happened.

    So the row waits. Deliberately NOT through `_after_failed_attempt`: that
    counts toward MAX_RETRY_ATTEMPTS and ends at `_give_up`, whose entire
    vocabulary — "stranded", "STILL OPEN at the broker", "close it manually"
    — is the opposite of what is true here. The broker is FLAT. Nothing is
    live, nothing is at risk, and nothing needs a human at the venue; the
    only missing thing is a number to write down. Abandoning the row for the
    lack of it would tell the operator to go chase a position that does not
    exist, and would leave the trade permanently unbooked into the bargain.

    It waits with a voice, not in silence — hourly, and with the truth.
    """
    mark = _decimal(_mark_price(trade, client))
    if mark is None or mark <= 0:
        logger.error(
            "close retry #%s: the broker is flat but no price could be read "
            "for %s — refusing to book the exit at the entry price, which "
            "would record this trade as a scratch. Waiting for a quote.",
            trade.id, trade.symbol)
        _alert_unpriced(trade)
        return False
    _finalise_closed(trade,
                     fill=resolve_exit_fill(trade, None, mark=mark),
                     reason=reason)
    return True


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
        from bot_program.engine.broker_router import session_busy
        if session_busy(client):
            # The IBKR trading session is EXCLUSIVE (one clientId, because
            # an order is visible only to the session that placed it), and
            # another process — usually the bot tick — is holding it. The
            # broker is fine and nothing was asked of it, so this is not an
            # attempt: counting it would spend the abandon budget on a local
            # lock and eventually flip a perfectly closable position to
            # ERROR with "close it by hand", which would be false. The row
            # stays CLOSE_PENDING and the next pass tries again.
            logger.warning(
                "close retry #%s for %s: the IBKR trading session is held by "
                "another process — nothing sent, NOT counted as an attempt",
                trade.id, trade.symbol)
            _note_session_busy(trade)
            return False
        msg = ("broker unavailable (PaperTrader fallback) — no close was "
               "sent and the position is still open at the broker")
        logger.error("close retry #%s for %s: %s", trade.id, trade.symbol, msg)
        _after_failed_attempt(trade, msg)
        return False

    # If the broker says the position is already gone, the original close
    # (or a protective leg) did fill — finalise instead of sending another
    # order that would open a naked reverse position.
    #
    # THIS RUNS FIRST ON EVERY PASS, before the two blocks below, because a
    # book with the position gone is the best possible resolution of both:
    # under end-of-day netting it is exactly what the evening produces.
    exposure = broker_exposure(trade, client)
    if exposure["state"] == POS_FLAT:
        logger.info("close retry: broker no longer holds #%s (%s) — "
                    "finalising without a new order", trade.id, trade.symbol)
        # No order was sent, so there is no fill to read: the remainder is
        # booked at the current mark and flagged as such.
        return _finalise_flat(trade, client, reason="RETRY_ALREADY_FLAT")

    # A CLOSE THE VENUE NEVER CONFIRMED OUTRANKS EVERY MOVE BELOW. The venue
    # answered 202 for the placement — "this order may exist" — and the
    # cancel-and-resend path below cannot help, because a cancel proves
    # nothing about an order the venue never admitted holding: the resend
    # would be a second live close for one intent. Nothing here can retire
    # the doubt either; the only thing that does is the book going flat,
    # which the escape above reads on every pass.
    doubt = (trade.metadata or {}).get(CLOSE_IN_DOUBT_KEY)
    if isinstance(doubt, dict) and doubt:
        _note_close_blocked(
            trade, f"a close for this row may already be live at the broker "
                   f"(order {doubt.get('order_id') or '(none)'}, reference "
                   f"{doubt.get('reference') or '(none)'}) and the venue has "
                   f"not resolved it")
        return False

    # THE BOOK WAS READ AND IT CANNOT SAY WHAT IS STILL THIS ROW'S — both
    # sides of the symbol are open, or a lot names no size, or a sibling row
    # claims the same units. Sending here is precisely what turned a flatten
    # into a THIRD full-size order. Nothing is sent and nothing is booked; a
    # later pass reads `flat` once the netting has run.
    if exposure["state"] == POS_UNKNOWN and exposure["ambiguous"]:
        _note_close_blocked(trade, exposure["why"])
        return False

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
            return _finalise_flat(trade, client,
                                  reason="RETRY_WORKING_CLOSE_FILLED")
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


def _claim_for_retry(trade_pk):
    """Take the in-flight claim on one CLOSE_PENDING row, or None.

    The sweep used to iterate a plain queryset and start closing: no row
    lock, and no look at the claim the CLOSE button takes. Every ingredient
    for two live closes on one position was present — `retry_pending_closes`
    is deliberately ungated, beat fires it every 300s onto the `default`
    queue, that worker runs two slots, and one pass over a timing-out broker
    takes longer than a beat. The module's only anti-stacking device,
    `_cancel_working_close`, reads a metadata key written AFTER a submit
    returns, so while the first close is in flight there is nothing in the
    row for the second caller to see: both read CLOSE_PENDING, both hear
    "the broker still holds it", both send a market order, and the flatten
    becomes a naked reverse position.

    Deliberately the SAME claim `manual_close` takes, not a second private
    one, so the beat and the CLOSE button exclude each other instead of each
    excluding only its own kind. `_stale` bounds it, so a worker that dies
    mid-close does not make the row unclosable forever.
    """
    from django.db import transaction
    from bot_program.manual_close import CLAIM_KEY, _stale
    from bot_program.models import AssetBotTrade

    with transaction.atomic():
        try:
            trade = (AssetBotTrade.objects
                     .select_for_update()
                     .select_related("config", "config__user")
                     .get(pk=trade_pk))
        except AssetBotTrade.DoesNotExist:
            return None
        # Everything that decides whether a retry may start is re-read INSIDE
        # the lock: the row may have been closed, abandoned or claimed
        # between the sweep's queryset and this moment.
        if trade.status != "CLOSE_PENDING" or trade.paper:
            return None
        held = (trade.metadata or {}).get(CLAIM_KEY)
        if held and not _stale(str(held)):
            logger.info("close retry: #%s is already being closed elsewhere "
                        "— leaving it to that attempt", trade_pk)
            return None
        meta = dict(trade.metadata or {})
        meta[CLAIM_KEY] = timezone.now().isoformat()
        trade.metadata = meta
        trade.save(update_fields=["metadata"])
    return trade


def retry_all_pending_closes() -> dict:
    """Retry every CLOSE_PENDING live trade. Paper rows never reach this
    state (they have no broker order to fail).

    One row at a time, each claimed first — see `_claim_for_retry`. A row
    somebody else is already closing counts as STILL PENDING rather than as
    a separate outcome: nothing closed it on this pass, and the next beat
    picks it up if that attempt failed.
    """
    from bot_program.manual_close import _release
    from bot_program.models import AssetBotTrade

    # Primary keys, not row snapshots: the claim re-reads each row under a
    # lock, so carrying stale copies out of the queryset would only invite
    # writing one back.
    pks = list(AssetBotTrade.objects
               .filter(status="CLOSE_PENDING", paper=False)
               .values_list("pk", flat=True))
    out = {"pending": 0, "closed": 0, "still_pending": 0}
    for pk in pks:
        out["pending"] += 1
        trade = _claim_for_retry(pk)
        if trade is None:
            out["still_pending"] += 1
            continue
        try:
            if retry_trade_close(trade):
                out["closed"] += 1
            else:
                out["still_pending"] += 1
        except Exception as e:
            logger.exception("close retry crashed for #%s: %s", trade.id, e)
            out["still_pending"] += 1
        finally:
            _release(pk)
    return out
