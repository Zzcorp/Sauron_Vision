"""THE ENTRY TIMING (2026-10-06): no new entry in the minutes when the
price is not a market price, and no attack into a scheduled print.

The operator asked for more resilience and smartness in taking positions.
A bot's entry was judged on its signal, its cost, its levels, its size,
its venue's health and its quote (PR43, PR44) — and never on the CLOCK.
The same order sent at 16:58 New York on a forex pair, in the first
minutes after an exchange opens, in the last minutes before it closes,
or ten minutes before a non-farm payroll print, is a worse trade than the
same order an hour away from any of them: the spread is wider, the print
is the previous session's, the fill is somebody's market-on-close, or
the stop is about to be gapped through. This module answers one
question, with the instrument's own clock (core.exchange_status) and the
calendar the open-position care already reads (position_care):

  ROLLOVER      forex, commodities and indices: no new entry from
                ROLLOVER_NY[0] to ROLLOVER_NY[1] New York every weekday —
                the daily swap, when every CFD venue re-prices (eToro
                answers error 749 at 21:01 UTC, measured) and the spread
                is at its widest.
  OPEN SETTLE   a market that opened less than OPEN_SETTLE_MINUTES ago:
                its first quotes are the previous session's (the paper
                venue's REOPEN_SETTLE_SECONDS rule, for every venue).
                Forex: the first quarter hour of the week.
  CLOSE GUARD   a stock or ETF in the last CLOSE_GUARD_MINUTES before its
                exchange closes (early closes kept); and every class
                that shuts, in Friday's last hour before the weekend
                (position_care.is_weekend_window): a position opened
                into the gap cannot be managed through it.
  THE PRINT     a high-impact macro print on the instrument's currency
                (either leg of a pair, the home currency for every other
                class) from EVENT_BEFORE_MINUTES before to
                EVENT_AFTER_MINUTES after — position_care.event_for, the
                care's own matching — and a held stock's own earnings
                within EARNINGS_BEFORE_HOURS.
  THE ATTACK    no refusal, but a print within EVENT_ATTACK_HOURS: the
                attack tier is capped at STANDARD (base.py _attack_tier)
                — the risk is sized, never raised, into a print.

A verdict is a dict: {"ok", "code" (ROLLOVER/SHUT/OPEN_SETTLE/
CLOSE_GUARD/WEEKEND/EVENT or ""), "why" (one sentence, no money), "until"
(an aware UTC datetime when the clock knows it, else None), "attack"
({"cap": "STANDARD", "why"} or None)}. The bot lane refuses on it
(skips.BAD_TIMING, or skips.MARKET_SHUT for SHUT — skip_code; at
propose_entry and again before the order); the TAKE TRADE ticket warns
and stays pressable (the operator keeps the last word).

THE SHUT EXCHANGE (2026-10-07). On 2026-10-06 research_stock_5 (config
26) shorted PG at 13:08 UTC, 22 minutes before the NYSE open; eToro
filled it at once, and Morgul G1 braked the config at 13:12. Until then a
shut market was left to the venue, or to the paper gate, and a real
venue that fills a CFD out of session said nothing. The bot lane now
refuses a live entry while the instrument's exchange is shut (SHUT), on
Morgul's own clock (market_clock, the one morgul._shut reads), for the
classes G1 judges at a broker (SHUT_CLASSES). The options lane refuses on
the same clock on its live branch, keyed on the underlying
(OPTIONS_SHUT_CLASSES). The words give the opening hour and the hour new
entries resume; the skip is recorded as skips.MARKET_SHUT (skip_code), the
same code the paper venue gives a shut market, so one word means "the
market is shut" in every lane. The TAKE TRADE ticket warns, as it does for
every other window.

A clock or a calendar that cannot be read refuses nothing. GATE is read at
call time: tests/__init__.py turns it off for a suite whose entries run at
whatever hour the wall clock says, and tests/test_entry_timing.py turns it
back on at a fixed clock.
"""
import logging
from datetime import datetime, time as dtime, timedelta
from datetime import timezone as dt_timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from django.utils import timezone

logger = logging.getLogger(__name__)

#: Read at call time (see the module docstring).
GATE = True

NY = ZoneInfo("America/New_York")
#: The daily rollover window, New York time (DST follows).
ROLLOVER_NY = (dtime(16, 50), dtime(17, 10))
#: The classes that roll over at 17:00 New York.
ROLLOVER_CLASSES = frozenset({"forex", "commodity", "index"})
#: The classes whose modelled session is the venue's own, so a rollover
#: that ends inside the venue's break clears at its reopening (+ settle).
VENUE_BREAK_CLASSES = frozenset({"commodity"})
#: Minutes after an open before a new entry.
OPEN_SETTLE_MINUTES = 15
#: Minutes before an exchange close with no new entry, and the classes
#: whose venue closes daily.
CLOSE_GUARD_MINUTES = 10
CLOSE_GUARD_CLASSES = frozenset({"stock", "etf"})
#: Hours before a print in which the attack tier is capped.
EVENT_ATTACK_HOURS = 3
EVENT_ATTACK_CAP = "STANDARD"
#: Classes with no clock to judge (never shut, no rollover).
NEVER_SHUTS = frozenset({"crypto"})
# THE SHUT EXCHANGE (2026-10-07). The classes refused while their
# exchange is shut are Morgul G1's own classes for a booking at a broker:
# morgul.CLOCK_CLASSES less "index", because G1 does not judge an index
# booked at a broker (the clock keeps the cash session, SPX500 on New
# York, while a broker's index CFD trades nearly round the clock), so a
# live index CFD still enters at night, as it may. The bot lane never sees
# "options" (the options lane replaces scan_symbol and never calls
# propose_entry), so SHUT_CLASSES leaves it out too. The options lane asks
# with OPTIONS_SHUT_CLASSES on the UNDERLYING's Instrument key, which is
# the key G1 reads for an options row (the row's symbol is the
# underlying), "options" included for an underlying with no Instrument
# row. Crypto stays NEVER_SHUTS; an unmodelled class (cfd, an unknown one)
# reads open with modelled False on both sides, so neither refuses it.
# These are written here and not imported from morgul, which imports
# telegram_eye at module level; tests/test_entry_timing.py pins the
# equality instead, so the gate and G1 cannot drift apart unnoticed.
SHUT_CLASSES = frozenset({"forex", "stock", "etf", "commodity"})
OPTIONS_SHUT_CLASSES = SHUT_CLASSES | {"options"}

ROLLOVER, OPEN_SETTLE, CLOSE_GUARD, WEEKEND, EVENT, SHUT = (
    "ROLLOVER", "OPEN_SETTLE", "CLOSE_GUARD", "WEEKEND", "EVENT", "SHUT")

_CLASS_WORDS = {"etf": "ETF"}


def _open() -> dict:
    return {"ok": True, "code": "", "why": "", "until": None, "attack": None}


def _class_words(asset_class) -> str:
    cls = str(asset_class or "").strip().lower()
    return _CLASS_WORDS.get(cls, cls or "instrument")


def instrument_key(symbol, asset_class="") -> tuple:
    """(class, exchange) of `symbol`'s INSTRUMENT row — the router's own
    key (paper_trader._instrument_key); the given class when no row."""
    from bot_program.engine.paper_trader import _instrument_key
    return _instrument_key(symbol, asset_class)


def _utc_words(moment) -> str:
    try:
        from core.exchange_status import utc_words
        return utc_words(moment)
    except Exception:  # noqa: BLE001
        return "?"


def rollover(now, asset_class, *, exchange="", symbol="") -> dict | None:
    """The rollover verdict for `now`, or None outside the window.

    Monday to Thursday only: Friday's 16:50-17:00 is the weekend window's
    (clock_verdict), and from 17:00 every venue has shut for the week. The
    hour it clears is the window's end — unless the instrument's own venue
    is still shut then (CME's daily break, a grain's or a soft's midday
    gap), when it is that venue's reopening plus its settling quarter
    hour. The hour comes first in the words: why_no_trade prints 88
    characters of a skip's detail."""
    cls = str(asset_class or "").lower()
    if cls not in ROLLOVER_CLASSES:
        return None
    ny = now.astimezone(NY)
    start, end = ROLLOVER_NY
    if ny.weekday() >= 4 or not (start <= ny.time() < end):
        return None
    until = ny.replace(hour=end.hour, minute=end.minute, second=0,
                       microsecond=0).astimezone(dt_timezone.utc)
    reopens_note = ""
    # Commodities only: their modelled session IS the venue's (CME Globex
    # with its 16:00-17:00 CT break, the grains' and softs' gaps). An
    # index is modelled on its cash exchange's hours, which an index CFD
    # outlives by most of the night, so its window's end stands.
    if cls in VENUE_BREAK_CLASSES:
        try:
            from core.exchange_status import market_clock
            later = market_clock(cls, exchange or "", symbol=symbol or "",
                                 now_utc=until)
            if not later.get("is_open", True) and later.get("reopens"):
                until = later["reopens"] + timedelta(
                    minutes=OPEN_SETTLE_MINUTES)
                reopens_note = ", once the venue reopens and settles"
        except Exception as e:  # noqa: BLE001 — the window's end stands
            logger.warning("[timing] venue clock unread for %s: %s",
                           symbol, e)
    return {"ok": False, "code": ROLLOVER,
            "why": (f"the {_class_words(cls)} market rolls over at 17:00 New "
                    f"York — new entries resume {_utc_words(until)}"
                    f"{reopens_note} (the daily swap: every venue re-prices "
                    f"and the spread is at its widest)"),
            "until": until, "attack": None}


def _session_close(code, now):
    """The running session's close as an aware UTC datetime, for an
    EXCHANGES row with a daily close (early closes kept for the US
    equity sessions); None for FOREX, CME and anything unmodelled."""
    import pytz

    from core import exchange_status as es
    if code in ("FOREX", "CME", "CRYPTO", ""):
        return None
    ex = next((e for e in es.EXCHANGES if e["code"] == code), None)
    if ex is None:
        return None
    tz = pytz.timezone(ex["tz"])
    local = now.astimezone(tz)
    close = ex["close"]
    if code in es._US_EQUITY_SESSIONS:
        close = es.US_EQUITY_EARLY_CLOSES.get(local.date(), close)
    return tz.localize(datetime.combine(local.date(), close)).astimezone(
        pytz.UTC)


def _utc_hour_words(moment) -> str:
    """"22:15 UTC" for an aware datetime: the hour alone, for a resume
    instant on the reopening's own UTC date (_shut_verdict)."""
    try:
        return f"{moment.astimezone(dt_timezone.utc):%H:%M} UTC"
    except Exception:  # noqa: BLE001
        return _utc_words(moment)


def _shut_verdict(cls: str, clock: dict, flagged: bool = False) -> dict:
    """THE SHUT EXCHANGE (2026-10-07): the refusal for a market whose
    clock reads shut, with the hour it opens and the hour new entries
    resume first in the words (why_no_trade prints 88 characters of a
    skip's detail). New entries resume OPEN_SETTLE_MINUTES after the
    reopening — the same 15 minutes as the paper venue's
    REOPEN_SETTLE_SECONDS — so "resume" names the very instant the
    OPEN_SETTLE window below clears, never the opening minute that window
    would then refuse. The session's name loses its underscores
    (CBOT_GRAINS reads "CBOT GRAINS"), so no snake_case reaches the
    operator.

    Review 2026-10-07: the words say only what is always true. The tail is
    "(<SESSION> hours: out of session)"; it adds ", a fill Morgul G1 would
    flag" only when `flagged` — shut_verdict found the clock shut at now
    AND CLOSE_GRACE_S before it, G1's own condition (morgul.
    check_market_shut) — so the first minutes after a close, which G1
    lets pass, promise no flag. "Would": G1 runs only while the
    morgul_guards component is ON, and it brakes only while morgul_brake
    is ON, both OFF on arrival, so neither "flags" nor "brakes" is said as
    a fact. The resume instant is "HH:MM UTC" alone when it falls on the
    reopening's own UTC date, so the resume hour stays inside the 88
    characters for every class and weekday; on another date it keeps its
    day."""
    reopens = clock.get("reopens")
    settled = (reopens + timedelta(minutes=OPEN_SETTLE_MINUTES)
               if reopens else None)
    sess = str(clock.get("session") or "").replace("_", " ")
    state = ("out of session, a fill Morgul G1 would flag" if flagged
             else "out of session")
    tail = f"({sess} hours: {state})" if sess else f"({state})"
    if reopens:
        try:
            same_day = (settled.astimezone(dt_timezone.utc).date()
                        == reopens.astimezone(dt_timezone.utc).date())
        except Exception:  # noqa: BLE001 — the full words stand
            same_day = False
        resume = (_utc_hour_words(settled) if same_day
                  else _utc_words(settled))
        why = (f"the {_class_words(cls)} market is shut until "
               f"{_utc_words(reopens)} — new entries resume {resume} "
               f"{tail}")
    else:
        why = (f"the {_class_words(cls)} market is shut — new entries "
               f"resume once it opens and settles {tail}")
    return {"ok": False, "code": SHUT, "why": why, "until": settled,
            "attack": None}


def shut_verdict(symbol, asset_class, *, exchange="", now=None,
                 classes=SHUT_CLASSES, clock=None) -> dict | None:
    """THE SHUT EXCHANGE (2026-10-07): SHUT's refusal when `symbol`'s
    exchange is shut now, on Morgul G1's own clock (market_clock, the one
    morgul._shut reads), for a class in `classes`; None otherwise.

    ONE function for both lanes, so the bot lane (through clock_verdict,
    with SHUT_CLASSES) and the options lane (on its live branch, with
    OPTIONS_SHUT_CLASSES on the underlying's key) can never read two
    different clocks. GATE is read at call time, so the suite's switch
    (tests/__init__.py) turns SHUT off in every lane at once. `clock`, when
    the caller has already read it, is used as is (clock_verdict reads the
    clock once). An unmodelled class (modelled False) and an open market
    answer None. No grace: G1 needs a booking shut at the booking AND a
    grace before it, so the gate is stricter than G1 by up to that grace
    after a close, and nothing G1 can flag passes it at the instant it
    sends. Never raises past its own log: a clock that cannot be read
    refuses nothing.

    Review 2026-10-07: G1 flags a booking only when the market is shut at
    it AND morgul.CLOSE_GRACE_S before it, so a refusal names G1 only
    then: on a shut clock the clock is read a second time at
    now - CLOSE_GRACE_S (also when `clock` was handed in), and the words
    say "a fill Morgul G1 would flag" only when that read is shut too
    (_shut_verdict). A second read that fails says nothing of G1; the
    refusal itself stands."""
    if not GATE:
        return None
    cls = str(asset_class or "").strip().lower()
    if cls not in classes:
        return None
    now = now or timezone.now()
    if clock is None:
        try:
            from core.exchange_status import market_clock
            clock = market_clock(cls, exchange or "", symbol=symbol or "",
                                 now_utc=now)
        except Exception as e:  # noqa: BLE001 — an unreadable clock refuses nothing
            logger.warning("[timing] market clock unreadable for %s: %s",
                           symbol, e)
            return None
    try:
        if clock.get("modelled", True) and not clock.get("is_open", True):
            return _shut_verdict(
                cls, clock,
                flagged=_g1_would_flag(cls, exchange, symbol, now))
    except Exception as e:  # noqa: BLE001 — never raises past its own log
        logger.warning("[timing] market clock unreadable for %s: %s",
                       symbol, e)
    return None


def _g1_would_flag(cls, exchange, symbol, now) -> bool:
    """Review 2026-10-07: whether Morgul G1 (morgul.check_market_shut)
    would flag a booking made at `now` on a clock that reads shut — G1's
    own condition, the clock shut at the booking AND CLOSE_GRACE_S before
    it. Only the second read is made here: the caller has the first. The
    constant is imported at call time (morgul imports telegram_eye at
    module level). False when the import or the read fails: the words
    then promise no flag."""
    try:
        from bot_program.morgul import CLOSE_GRACE_S
        from core.exchange_status import market_clock
        before = market_clock(cls, exchange or "", symbol=symbol or "",
                              now_utc=now - timedelta(seconds=CLOSE_GRACE_S))
        return bool(before.get("modelled", True)
                    and not before.get("is_open", True))
    except Exception as e:  # noqa: BLE001 — unread: no flag is promised
        logger.warning("[timing] the clock a grace before %s unread for "
                       "%s: %s", now, symbol, e)
        return False


def clock_verdict(symbol, asset_class, *, exchange="", now=None) -> dict | None:
    """The clock's refusal — the rollover, a shut exchange (SHUT:
    SHUT_CLASSES on Morgul G1's own clock), Friday's last hour before the
    weekend, a market's first quarter hour, an exchange's last minutes — in
    that order, or None. A shut market of another class (an index CFD at
    night) answers None. Never raises past its own log."""
    now = now or timezone.now()
    cls = str(asset_class or "").strip().lower()
    if cls in NEVER_SHUTS or cls == "options":
        return None
    got = rollover(now, cls, exchange=exchange, symbol=symbol)
    if got is not None:
        return got
    # THE SHUT EXCHANGE (2026-10-07): the clock is read once, before the
    # weekend window, so a market already shut on a Friday afternoon (the
    # grains after 13:20 Chicago, a stock after an early close) is given
    # the hour it opens again, not the weekend window's words, which name
    # no hour. The rollover stays first: CME's daily break at 17:05 New
    # York keeps PR47's words and its settle hour. A clock that cannot be
    # read refuses nothing, and the weekend window below never reads it,
    # so that window still stands when the clock is unreadable.
    clock = None
    try:
        from core.exchange_status import market_clock
        clock = market_clock(cls, exchange or "", symbol=symbol or "",
                             now_utc=now)
    except Exception as e:  # noqa: BLE001 — an unreadable clock refuses nothing
        logger.warning("[timing] market clock unreadable for %s: %s",
                       symbol, e)
    if clock is not None:
        shut = shut_verdict(symbol, cls, exchange=exchange, now=now,
                            classes=SHUT_CLASSES, clock=clock)
        if shut:
            return shut
    try:
        from bot_program.position_care import is_weekend_window
        if is_weekend_window(now, cls):
            return {"ok": False, "code": WEEKEND,
                    "why": (f"Friday's last hour before the weekend for the "
                            f"{_class_words(cls)} market — a position "
                            f"opened now cannot be managed through the gap; "
                            f"new entries resume on the week's open"),
                    "until": None, "attack": None}
    except Exception as e:  # noqa: BLE001
        logger.warning("[timing] weekend window unread for %s: %s", symbol, e)
    if clock is None:
        return None
    # A market of another class that is shut (an index CFD at night), or
    # a class the clock does not model: nothing more is judged here, as
    # before 2026-10-07.
    if not clock.get("is_open", True) or not clock.get("modelled", True):
        return None
    opened = clock.get("opened")
    if opened is not None:
        settled = opened + timedelta(minutes=OPEN_SETTLE_MINUTES)
        if now < settled:
            return {"ok": False, "code": OPEN_SETTLE,
                    "why": (f"the {_class_words(cls)} market opened at "
                            f"{_utc_words(opened)} — new entries resume "
                            f"{_utc_words(settled)} (its first quarter hour "
                            f"is not a market price yet)"),
                    "until": settled, "attack": None}
    if cls in CLOSE_GUARD_CLASSES:
        try:
            close = _session_close(clock.get("session") or "", now)
        except Exception as e:  # noqa: BLE001
            logger.warning("[timing] session close unread for %s: %s",
                           symbol, e)
            close = None
        if close is not None and timedelta(0) <= close - now < timedelta(
                minutes=CLOSE_GUARD_MINUTES):
            return {"ok": False, "code": CLOSE_GUARD,
                    "why": (f"the {_class_words(cls)} market closes at "
                            f"{_utc_words(close)} — no new entry in its "
                            f"last {CLOSE_GUARD_MINUTES} minutes (the "
                            f"closing auction is not a price to size on)"),
                    "until": close, "attack": None}
    return None


def event_verdict(symbol, asset_class, *, now=None, events=None,
                  cache=None) -> dict:
    """{"refusal": dict|None, "attack": dict|None} — the print inside the
    care's window (a refusal), else the print within EVENT_ATTACK_HOURS
    (the attack cap). Uses position_care's matching, so the entry and the
    care agree on which currency's prints touch which instrument."""
    from bot_program import position_care as pc
    now = now or timezone.now()
    cls = str(asset_class or "").strip().lower()
    if cls == "options":
        return {"refusal": None, "attack": None}
    if events is None:
        events = pc.upcoming_events(now, cache=cache,
                                    horizon_minutes=EVENT_ATTACK_HOURS * 60)
    row = SimpleNamespace(symbol=symbol, asset_class=cls)
    near = pc.event_for(row, now, events)
    if near is not None:
        m = float(near.get("minutes") or 0.0)
        if near.get("earnings"):
            why = (f"{near['title']} {_when(m)} — the instrument's own "
                   f"earnings within {pc.EARNINGS_BEFORE_HOURS} h; no new "
                   f"entry into them")
        else:
            why = (f"high-impact print {near['title']} {_when(m)} — no new "
                   f"entry from {pc.EVENT_BEFORE_MINUTES} min before to "
                   f"{pc.EVENT_AFTER_MINUTES} min after")
        until = None
        try:
            at = datetime.fromisoformat(str(near.get("at")))
            until = at + timedelta(minutes=pc.EVENT_AFTER_MINUTES)
        except (TypeError, ValueError):
            pass
        return {"refusal": {"ok": False, "code": EVENT, "why": why,
                            "until": until, "attack": None},
                "attack": None}
    soon = pc.event_for(row, now, events,
                        before_minutes=EVENT_ATTACK_HOURS * 60)
    if soon is None:
        return {"refusal": None, "attack": None}
    m = float(soon.get("minutes") or 0.0)
    return {"refusal": None,
            "attack": {"cap": EVENT_ATTACK_CAP,
                       "why": (f"attack capped at {EVENT_ATTACK_CAP}: "
                               f"{soon['title']} {_when(m)}, inside "
                               f"{EVENT_ATTACK_HOURS} h of a print")}}


def _when(minutes: float) -> str:
    if minutes < 0:
        return f"{-minutes:.0f} min ago"
    if minutes > 120:
        return f"in {round(minutes / 60, 1):g} h"
    return f"in {minutes:.0f} min"


def verdict(symbol, asset_class, *, exchange="", now=None, events=None,
            cache=None) -> dict:
    """The entry timing verdict for `symbol` now (see the module
    docstring). Never raises: a clock or a calendar that cannot be read
    refuses nothing, and says so in the log."""
    if not GATE:
        return _open()
    now = now or timezone.now()
    try:
        got = clock_verdict(symbol, asset_class, exchange=exchange, now=now)
        if got is not None:
            return got
    except Exception as e:  # noqa: BLE001
        logger.warning("[timing] clock verdict failed for %s: %s", symbol, e)
    try:
        ev = event_verdict(symbol, asset_class, now=now, events=events,
                           cache=cache)
    except Exception as e:  # noqa: BLE001
        logger.warning("[timing] event verdict failed for %s: %s", symbol, e)
        return _open()
    if ev["refusal"] is not None:
        return ev["refusal"]
    out = _open()
    out["attack"] = ev["attack"]
    return out


def skip_code(verdict: dict) -> str:
    """THE SHUT EXCHANGE (2026-10-07): the skip code a refusal is recorded
    under. SHUT is skips.MARKET_SHUT, the code the paper venue already
    gives a shut market, so one word means "the market is shut" in every
    lane and a night of refusals does not swamp bad_timing's count and its
    advice; every other window stays skips.BAD_TIMING."""
    from bot_program.asset_engine import skips
    if (verdict or {}).get("code") == SHUT:
        return skips.MARKET_SHUT
    return skips.BAD_TIMING


def advisory(symbol, asset_class, *, exchange="", now=None) -> dict:
    """{"ok", "reason", "attack", "code"} for the TAKE TRADE preview — a
    warning, never a refusal: the operator keeps the last word on their own
    lane. "code" (2026-10-07) is the verdict's code ("SHUT", "ROLLOVER",
    ... or ""), so the ticket can say THE MARKET IS SHUT rather than a bad
    hour, and the booking records which window was overridden."""
    try:
        v = verdict(symbol, asset_class, exchange=exchange, now=now)
    except Exception as e:  # noqa: BLE001 — an unread clock warns of nothing
        logger.warning("[timing] advisory unread for %s: %s", symbol, e)
        return {"ok": True, "reason": "", "attack": "", "code": ""}
    return {"ok": bool(v["ok"]), "reason": v["why"],
            "attack": (v["attack"] or {}).get("why", ""),
            "code": str(v.get("code") or "")}
