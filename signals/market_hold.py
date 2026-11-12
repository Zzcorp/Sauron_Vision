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

OPTIONAL, BEHIND A SWITCH: THE HOLD. For an operator who would rather
hear of a signal when he can act on it, the switch signal_market_hold
(OFF on arrival, read with is_component_enabled, so a missing row is OFF)
makes the announcement wait for the market:

  at birth      hold_at_birth: a signal whose market cannot trade now
                (shut, or in its first quarter hour) is written exactly
                as today, nothing is announced, and one SignalHold row
                says why and when the market opens. A hold that cannot be
                written announces as before: a signal is never swallowed.
  every 5 min   release_due, called by the signal lifecycle task after its
                grading loop. For each held row, first match wins:
                  1  the engine closed the signal          drop  closed
                  2  it is 24 hours old or more            drop  aged_shut
                  3  its market is shut or settling        wait
                  4  a price of the new session exists     judge it
                     (a quote written after the open plus the settle and
                     no older than the grader's own bound, else the close
                     of a 1h or 4h bar opened since the open): drop
                     (stop_crossed, target_reached, chased) or release
                  5  no such price 30 minutes after the    release, saying
                     settle                                its levels were
                                                           not re-checked
  a release     announces once, through the same three steps as a birth,
                with one more sentence ("fired Sunday 09:00 UTC, while its
                market was shut"), best score first, so the 20 Telegram
                messages an hour go to the best ones.

The switch gates the hold at birth only: turned off while rows are held,
the pass still settles them. The 24 hours are the vote's and the ticket's
(manual_trade.SIGNAL_BACKING_HOURS); the three price reasons are the
judgment the operator's own signal list already makes of a card
(levels_reason; a test compares the two on a grid).

GATE is read at call time: tests/__init__.py turns it off for a suite
whose signals are announced at whatever hour the wall clock says, and
tests/test_signal_market_hold.py turns it back on at a fixed clock.

WORDS AND TIMING OF AN ANNOUNCEMENT ONLY. Nothing here writes a field of
a Signal, moves an order, a size, a stop or a gate, or changes a bot's
vote or a grade: decide() reads the same rows with the same filter.
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

#: The optional hold's switch (core.platform_control): OFF on arrival.
SWITCH = "signal_market_hold"
#: Past the settling window, how long the release pass waits for a first
#: price before it announces a signal unchecked: many instruments have no
#: quote poller, and a feed that cannot be read must not swallow a signal.
NO_PRICE_GRACE = timedelta(minutes=30)

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


# ── the optional hold (the switch signal_market_hold) ────────────────────

def enabled() -> bool:
    """The switch. OFF on arrival, and a row that is not seeded yet reads
    OFF (is_component_enabled): then every signal is announced at birth."""
    try:
        from core.platform_control import is_component_enabled
        return bool(is_component_enabled(SWITCH))
    except Exception:  # noqa: BLE001 — an unread switch is off
        return False


def life() -> timedelta:
    """How long a signal counts: the hours of the bots' vote and of the
    hand ticket's backing (manual_trade.SIGNAL_BACKING_HOURS)."""
    from bot_program.manual_trade import SIGNAL_BACKING_HOURS
    return timedelta(hours=SIGNAL_BACKING_HOURS)


def quote_max_age() -> timedelta:
    """Past this a stored quote is not a price any more: the grader's own
    bound (signals.performance.MAX_QUOTE_AGE_SECONDS)."""
    from signals.performance import MAX_QUOTE_AGE_SECONDS
    return timedelta(seconds=MAX_QUOTE_AGE_SECONDS)


def levels_reason(direction, entry, stop, target, mark) -> str:
    """"" while a plan is still valid at `mark`, else why it is past:
    stop_crossed (the mark at or through the stop), target_reached (at or
    through the target) or chased (the reward to risk from the mark under
    the ticket's line, manual_trade.REWARD_RISK_WARN, when the plan
    cleared it at its entry). Floats, or None for a level the signal does
    not carry; a direction that is neither bullish nor bearish has no
    plan to judge."""
    from bot_program.manual_trade import (REWARD_RISK_WARN,
                                          reward_risk_advisory)
    order = {"bullish": "BUY", "bearish": "SELL"}.get(direction or "")
    if order is None or mark is None:
        return ""
    if stop is not None and ((order == "BUY" and mark <= stop)
                             or (order == "SELL" and mark >= stop)):
        return "stop_crossed"
    if target is not None and ((order == "BUY" and mark >= target)
                               or (order == "SELL" and mark <= target)):
        return "target_reached"
    if None in (entry, stop, target):
        return ""
    now_rr = reward_risk_advisory(order, mark, stop, target).get("ratio")
    born_rr = reward_risk_advisory(order, entry, stop, target).get("ratio")
    if (now_rr is not None and born_rr is not None
            and now_rr < REWARD_RISK_WARN <= born_rr):
        return "chased"
    return ""


def hold_at_birth(signal, now=None) -> str:
    """Hold the announcement of a freshly created signal when its market
    cannot trade now.

    Returns the hold's words when the announcement must wait (one
    SignalHold row, state held, was written or was already there), else
    "": announce now, as before. "" as well while GATE or the switch is
    off, and when the row cannot be written. Never raises."""
    if not GATE or not enabled():
        return ""
    pk = getattr(signal, "pk", None)
    try:
        st = market_state(signal.instrument, now=now)
        if st["tradeable"]:
            return ""
        from django.db import transaction

        from signals.models_hold import SignalHold
        reason = (SignalHold.MARKET_SHUT if st["state"] == "shut"
                  else SignalHold.MARKET_SETTLING)
        # Its own savepoint: a database refusal here must not poison the
        # transaction of the creator that has just written the signal.
        with transaction.atomic():
            hold, created = SignalHold.objects.get_or_create(
                signal=signal,
                defaults={"state": SignalHold.HELD, "reason": reason,
                          "words": st["words"][:300],
                          "reopens_at": st["reopens"],
                          "held_at": now or timezone.now()})
    except Exception as e:  # noqa: BLE001 — a signal is never swallowed
        logger.warning("[market hold] signal #%s: the hold could not be "
                       "written (%s): announced now, as before", pk, e)
        return ""
    if hold.state != SignalHold.HELD:
        return ""               # already settled: nothing waits any more
    if created:
        logger.info("[market hold] signal #%s (%s) is not announced yet: %s",
                    pk, getattr(signal.instrument, "symbol", "?"), hold.words)
    return hold.words or st["words"]


def _price(value, instrument) -> str:
    from core.price_format import format_price
    return format_price(value, getattr(instrument, "asset_class", "") or "",
                        getattr(instrument, "symbol", "") or "")


def _first_price(instrument, since, now):
    """The first usable price of the session that opened at `since`, or
    None: the stored quote when it was written after the open plus the
    settle and is no older than the grader's bound, else the close of the
    newest 1h or 4h bar opened since the open (bars are stamped with
    their open)."""
    try:
        quote = instrument.live_quote
    except Exception:  # noqa: BLE001 — no quote row is no quote
        quote = None
    if quote is not None:
        last, at = quote.last, quote.updated_at
        if (last is not None and last > 0 and at is not None
                and at >= since + SETTLE and now - at <= quote_max_age()):
            return last
    try:
        from market_data.models import PriceData
        return (PriceData.objects
                .filter(instrument=instrument, timeframe__in=("1h", "4h"),
                        timestamp__gte=since, timestamp__lte=now)
                .order_by("-timestamp")
                .values_list("close", flat=True).first())
    except Exception as e:  # noqa: BLE001 — unread bars are no price
        logger.debug("[market hold] bars unread for %s: %s",
                     getattr(instrument, "symbol", "?"), e)
        return None


def _release_note(signal, hold, mark) -> dict:
    """What a release says: {"clause" (the banner and the bell), "line"
    (the Telegram message and the copies), "words" (kept on the row)}."""
    from signals.models_hold import SignalHold
    fired = utc_words(signal.created_at)
    if hold.reason == SignalHold.MARKET_SETTLING:
        its, the = ("in its market's first quarter hour",
                    "in the market's first quarter hour")
    else:
        its, the = "while its market was shut", "while the market was shut"
    clause = f"fired {fired}, {its}"
    if mark is None:
        tail = "no price since the open: its levels were not re-checked"
        return {"clause": f"{clause}; {tail}",
                "line": f"Fired {fired}, {the}. No price since the open: "
                        f"its levels were not re-checked.",
                "words": f"Announced at the open: {clause}; {tail}."}
    px = _price(mark, signal.instrument)
    return {"clause": clause,
            "line": f"Fired {fired}, {the}. First price since the open: "
                    f"{px}.",
            "words": f"Announced at the open: {clause}; first price since "
                     f"the open {px}."}


def _drop_words(why, signal, mark) -> str:
    inst = signal.instrument
    px = _price(mark, inst)
    if why == "stop_crossed":
        return (f"At the open the first price, {px}, was at or through its "
                f"stop, {_price(signal.suggested_stop, inst)}: it was never "
                f"announced.")
    if why == "target_reached":
        return (f"At the open the first price, {px}, had already reached "
                f"its target, {_price(signal.suggested_target, inst)}: it "
                f"was never announced.")
    return (f"At the open the first price, {px}, left a reward to risk "
            f"under the ticket's 1.00 line, when its plan cleared it at the "
            f"entry: it was never announced.")


def _judge(hold, now) -> tuple:
    """The release pass's verdict on one held row, first match wins:
    ("wait",) | ("drop", reason, words, mark) | ("release", reason,
    words, mark, note)."""
    from bot_program.manual_trade import SIGNAL_BACKING_HOURS
    from signals.models_hold import SignalHold
    signal = hold.signal
    inst = signal.instrument
    if not signal.is_active:
        return ("drop", SignalHold.CLOSED,
                "The engine closed it before its market opened: it was "
                "never announced.", None)
    ends = signal.created_at + life()
    if now >= ends:
        return ("drop", SignalHold.AGED_SHUT,
                f"Its {SIGNAL_BACKING_HOURS} hours ended {utc_words(ends)}, "
                f"before its market had opened and settled: it was never "
                f"announced.", None)
    st = market_state(inst, now=now)
    if not st["tradeable"]:
        return ("wait",)
    since = st["opened"] or hold.reopens_at or hold.held_at
    mark = _first_price(inst, since, now)
    if mark is None:
        if now < since + SETTLE + NO_PRICE_GRACE:
            return ("wait",)
        note = _release_note(signal, hold, None)
        return ("release", SignalHold.UNCHECKED, note["words"], None, note)

    def f(value):
        return None if value is None else float(value)

    entry = (signal.suggested_entry if signal.suggested_entry is not None
             else signal.price_at_signal)
    why = levels_reason(signal.direction, f(entry), f(signal.suggested_stop),
                        f(signal.suggested_target), float(mark))
    if why:
        return ("drop", why, _drop_words(why, signal, mark), mark)
    note = _release_note(signal, hold, mark)
    return ("release", SignalHold.VALID, note["words"], mark, note)


def _settle(hold, state, reason, words, mark, now) -> bool:
    """Write the decision on a row that is still held; False when another
    pass got there first (so a release is announced once)."""
    from signals.models_hold import SignalHold
    return bool(SignalHold.objects
                .filter(pk=hold.pk, state=SignalHold.HELD)
                .update(state=state, reason=reason, words=(words or "")[:300],
                        mark=mark, decided_at=now))


def _record(counts) -> None:
    """What the pass did, on the switch's own row: /ops/ and the system
    map show a switch's last run, and this switch gates no task of its
    own, so without this an enabled switch would read "has never run".
    Written while the switch is on or something is still held; with the
    switch off and nothing held the pass writes nothing."""
    try:
        from core.platform_control import get_component
        row = get_component(SWITCH)
        if row is None:
            return
        said = (f"{counts['waiting']} waiting for their market · "
                f"{counts['released']} announced at the open · "
                f"{counts['dropped']} dropped")
        if counts["errors"]:
            said += f" · {counts['errors']} could not be judged"
        row.mark_run(success=not counts["errors"], message=said)
    except Exception as e:  # noqa: BLE001 — a note, never the pass
        logger.debug("[market hold] the pass could not be recorded: %s", e)


def release_due(now=None) -> dict:
    """Settle the held announcements: release (announce once), drop, or
    wait. Called by the signal lifecycle task every five minutes, after
    its grading loop. Not gated by the switch: rows held before it was
    turned off are still settled. Returns {"held", "waiting", "released",
    "dropped", "errors"}."""
    counts = {"held": 0, "waiting": 0, "released": 0, "dropped": 0,
              "errors": 0}
    if not GATE:
        return counts
    from signals.models_hold import SignalHold
    now = now or timezone.now()
    holds = list(SignalHold.objects.filter(state=SignalHold.HELD)
                 .select_related("signal", "signal__instrument",
                                 "signal__instrument__live_quote"))
    counts["held"] = len(holds)
    if not holds:
        if enabled():
            _record(counts)
        return counts
    releases = []
    for hold in holds:
        # One bad row must not starve the rest of the pass.
        try:
            verdict = _judge(hold, now)
        except Exception:  # noqa: BLE001
            logger.exception("[market hold] signal #%s could not be judged",
                             hold.signal_id)
            counts["errors"] += 1
            continue
        if verdict[0] == "wait":
            counts["waiting"] += 1
        elif verdict[0] == "drop":
            _kind, reason, words, mark = verdict
            if _settle(hold, SignalHold.DROPPED, reason, words, mark, now):
                counts["dropped"] += 1
                logger.info("[market hold] signal #%s dropped (%s): %s",
                            hold.signal_id, reason, words)
        else:
            releases.append((hold, verdict))
    # Best score first: when many are released at one open, the 20
    # Telegram messages an hour (alerts/dispatch) are the best ones, and
    # its guard counts the rest.
    releases.sort(key=lambda r: (-float(r[0].signal.score or 0),
                                 r[0].signal_id))
    for hold, (_kind, reason, words, mark, note) in releases:
        if not _settle(hold, SignalHold.RELEASED, reason, words, mark, now):
            continue
        counts["released"] += 1
        try:
            from signals.announce import announce_released
            announce_released(hold.signal, note)
        except Exception:  # noqa: BLE001 — the next one still goes out
            logger.exception("[market hold] signal #%s was released and "
                             "its announcement failed", hold.signal_id)
    _record(counts)
    return counts
