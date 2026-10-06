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

A verdict is a dict: {"ok", "code" (ROLLOVER/OPEN_SETTLE/CLOSE_GUARD/
WEEKEND/EVENT or ""), "why" (one sentence, no money), "until" (an aware
UTC datetime when the clock knows it, else None), "attack" ({"cap":
"STANDARD", "why"} or None)}. The bot lane refuses on it
(skips.BAD_TIMING, propose_entry and again before the order); the TAKE
TRADE ticket warns and stays pressable (the operator keeps the last
word). A shut market is nobody's business here (the venue, or the paper
gate, says so); a clock or a calendar that cannot be read refuses
nothing. GATE is read at call time: tests/__init__.py turns it off for a
suite whose entries run at whatever hour the wall clock says, and
tests/test_entry_timing.py turns it back on at a fixed clock.
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

ROLLOVER, OPEN_SETTLE, CLOSE_GUARD, WEEKEND, EVENT = (
    "ROLLOVER", "OPEN_SETTLE", "CLOSE_GUARD", "WEEKEND", "EVENT")

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


def clock_verdict(symbol, asset_class, *, exchange="", now=None) -> dict | None:
    """The clock's refusal — rollover, open settle, close guard, the
    weekend window — or None. A shut market answers None: the venue (or
    the paper gate) says so, not this. Never raises past its own log."""
    now = now or timezone.now()
    cls = str(asset_class or "").strip().lower()
    if cls in NEVER_SHUTS or cls == "options":
        return None
    got = rollover(now, cls, exchange=exchange, symbol=symbol)
    if got is not None:
        return got
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
    try:
        from core.exchange_status import market_clock
        clock = market_clock(cls, exchange or "", symbol=symbol or "",
                             now_utc=now)
    except Exception as e:  # noqa: BLE001 — an unreadable clock refuses nothing
        logger.warning("[timing] market clock unreadable for %s: %s",
                       symbol, e)
        return None
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


def advisory(symbol, asset_class, *, exchange="", now=None) -> dict:
    """{"ok", "reason", "attack"} for the TAKE TRADE preview — a warning,
    never a refusal: the operator keeps the last word on their own lane."""
    try:
        v = verdict(symbol, asset_class, exchange=exchange, now=now)
    except Exception as e:  # noqa: BLE001 — an unread clock warns of nothing
        logger.warning("[timing] advisory unread for %s: %s", symbol, e)
        return {"ok": True, "reason": "", "attack": ""}
    return {"ok": bool(v["ok"]), "reason": v["why"],
            "attack": (v["attack"] or {}).get("why", "")}
