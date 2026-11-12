"""Can this instrument trade now? The market clock behind a signal's
announcement and its card (2026-11-12).

The operator, 2026-11-11: signals were announced while their market was
shut, with nothing to tell them from the ones he could act on ("please
fix it"). Nothing that wrote, announced or showed a signal asked the
market clock; the bots, the paper venue, Morgul and the ticket did. A
signal is born on a shut market at fixed moments: the 09:00 UTC
opportunity scan (always before the US bell, and on Saturday and Sunday
too), the 23:45 UTC full-universe scan, and a closed-bar rule reading a
session's last bar, which it can only do once the session has ended.

THE CLOCK IS NOT NEW. market_state asks core.exchange_status.market_clock
(the clock Morgul, the entry gate, the paper venue and the ticket read),
with the classes on which the bots already refuse a shut market
(entry_timing.SHUT_CLASSES) and the bots' own settling quarter hour
(entry_timing.OPEN_SETTLE_MINUTES); tests/test_signal_market_hold.py pins
both equalities, so a signal's words and the bots can never read two
clocks.

    crypto, an unmodelled class     never shut
    forex, stock, ETF, commodity    shut while market_clock reads shut;
                                    settling for 15 minutes after an open
    index                           shut only while its cash session AND
                                    the CME futures week are both shut: a
                                    broker's index CFD trades nearly round
                                    the clock (entry_timing says why). The
                                    futures week is CME's, an approximation
                                    for an index that is not American, and
                                    the words say so
    a clock that cannot be read     never shut, with a WARNING (the house
                                    rule of the entry gate: a clock that
                                    cannot be read refuses nothing)

Only "shut" and "opened less than 15 minutes ago" are read. The bots'
whole timing verdict is not: the rollover, the hour around a print and
Friday's last hour are moments of an OPEN market.

ALWAYS ON, NO SWITCH: THE LABEL. The operator, 2026-11-12, told the
announcements would wait for the open: "non, faites que l'on reçoive
quand même les signaux live, c'est plus intéressant". So every signal is
announced the moment it fires, as before, and one whose market is shut at
that moment says so on every channel that announces it, with the hour the
market opens when the clock knows it (shut_label):

    market shut · opens Sun 22:00 UTC

"market shut" alone when the clock does not know the hour; nothing at all
while the market is open, its first quarter hour included, so an open
market's announcement keeps main's bytes.

GATE is read at call time: tests/__init__.py turns it off for a suite
whose signals are announced at whatever hour the wall clock says, and
tests/test_signal_market_hold.py turns it back on at a fixed clock.

DISPLAY AND WORDS ONLY. Nothing here writes a Signal, moves an order, a
size, a stop or a gate, or changes a bot's vote or a grade.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from datetime import timezone as dt_timezone

from django.utils import timezone

from bot_program import entry_timing
from core.exchange_status import market_clock, utc_words

logger = logging.getLogger(__name__)

#: Read at call time (see the module docstring).
GATE = True

#: The classes that read shut on their market clock: the bots' own
#: (entry_timing.SHUT_CLASSES). An index has its own rule below.
HOLD_CLASSES = entry_timing.SHUT_CLASSES
#: The quarter hour after an open in which a quote may still carry the
#: price from before the shut: the bots' own.
SETTLE_MINUTES = entry_timing.OPEN_SETTLE_MINUTES
SETTLE = timedelta(minutes=SETTLE_MINUTES)

#: The label's weekday, from a fixed table: no locale can change the words.
_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_CLASS_WORDS = {"etf": "ETF"}


def opens_words(moment) -> str:
    """"Sun 22:00 UTC" for an aware datetime."""
    m = moment.astimezone(dt_timezone.utc)
    return f"{_DAYS[m.weekday()]} {m.strftime('%H:%M')} UTC"


def _state(state, tradeable, **more) -> dict:
    out = {"state": state, "tradeable": tradeable, "session": "",
           "reopens": None, "opened": None, "tradeable_at": None,
           "words": "", "label": "", "opens": ""}
    out.update(more)
    return out


def _index_clock(exchange, symbol, now) -> dict:
    """An index CFD outlives its cash session: shut only while the cash
    session and the futures week (the CME row) are both shut."""
    cash = market_clock("index", exchange, symbol=symbol, now_utc=now)
    if cash["is_open"]:
        return cash
    futures = market_clock("commodity", "CME", symbol="", now_utc=now)
    session = f"{cash.get('session') or ''}+CME"
    if futures["is_open"]:
        return {**futures, "session": session}
    both = [c["reopens"] for c in (cash, futures) if c.get("reopens")]
    first = min(both) if both else None
    return {**cash, "session": session, "reopens": first,
            "reopens_words": utc_words(first) if first else ""}


def market_state(instrument, now=None) -> dict:
    """Can `instrument` trade now?

    {"state": "always" (crypto) | "open" | "settling" (opened less than
    SETTLE_MINUTES ago) | "shut" | "unmodelled" (no modelled hours, or a
    clock that could not be read) | "off" (GATE), "tradeable": True unless
    shut or settling, "session", "reopens" (an aware UTC datetime while
    shut, None when the clock does not know it), "opened" (while open),
    "tradeable_at" (the open plus the settle), "words" (one sentence for
    a market that cannot trade now, else ""), "label" (what a signal
    announced now says: "market shut · opens Sun 22:00 UTC", "market shut"
    when the hour is unknown, "" unless shut) and "opens" (the label's
    second half, or "")}. Never raises.
    """
    if not GATE:
        return _state("off", True)
    cls = str(getattr(instrument, "asset_class", "") or "").strip().lower()
    exchange = getattr(instrument, "exchange", "") or ""
    symbol = getattr(instrument, "symbol", "") or ""
    if cls == "crypto":
        return _state("always", True, session="CRYPTO")
    if cls not in HOLD_CLASSES and cls != "index":
        return _state("unmodelled", True)
    if now is None:
        now = timezone.now()
    try:
        if cls == "index":
            clock = _index_clock(exchange, symbol, now)
        else:
            clock = market_clock(cls, exchange, symbol=symbol, now_utc=now)
    except Exception as e:  # noqa: BLE001 — an unread clock holds nothing
        logger.warning("[market hold] the market clock could not be read "
                       "for %s (%s): read as open", symbol or "?", e)
        return _state("unmodelled", True)
    if not clock.get("modelled", True):
        return _state("unmodelled", True)
    session = clock.get("session") or ""
    name = _CLASS_WORDS.get(cls, cls)
    if not clock.get("is_open", True):
        reopens = clock.get("reopens")
        if cls == "index":
            what = ("its cash session and the futures week are both shut"
                    if symbol in entry_timing.US_INDEX_FUTURES else
                    "its cash session and the CME futures week are both "
                    "shut (CME's week is an approximation for an index "
                    "that is not American)")
        else:
            what = f"the {name} market is shut"
        if reopens is None:
            return _state("shut", False, session=session,
                          words=f"{what}: the clock does not know when it "
                                f"opens",
                          label="market shut")
        opens = f"opens {opens_words(reopens)}"
        return _state("shut", False, session=session, reopens=reopens,
                      tradeable_at=reopens + SETTLE,
                      words=f"{what}: it opens {utc_words(reopens)}",
                      label=f"market shut · {opens}", opens=opens)
    opened = clock.get("opened")
    if opened is not None and now < opened + SETTLE:
        return _state("settling", False, session=session, opened=opened,
                      tradeable_at=opened + SETTLE,
                      words=(f"the {name} market opened at "
                             f"{utc_words(opened)}: its first quarter hour "
                             f"is not a market price yet"))
    return _state("open", True, session=session, opened=opened)


def shut_label(instrument, now=None) -> str:
    """What a signal announced now says of its market: "market shut ·
    opens Sun 22:00 UTC", "market shut" when the clock does not know the
    hour, "" while the market can trade or is in its first quarter hour.
    Never raises: a label is never worth an announcement."""
    try:
        return market_state(instrument, now=now)["label"]
    except Exception as e:  # noqa: BLE001
        logger.warning("[market hold] the market label could not be read "
                       "for %s (%s): nothing is said",
                       getattr(instrument, "symbol", "?"), e)
        return ""
