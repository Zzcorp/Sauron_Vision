"""eToro's ALL-WEEK INSTRUMENTS ON THE SCREENS (2026-11-19). Display only.

The operator, 2026-11-19: yes, the screens say "open 24/7 at eToro" at the
weekend for eToro's all-week instruments, and the bots keep no new entry
at the weekend, for now. eToro trades GOLD, OIL, SILVER, NATGAS, SPX500
and NSDQ100 all week with short breaks (market_data/shut_bars.py
ALL_WEEK_ETORO_IDS, keyed by eToro's id; the published breaks beside it,
ALL_WEEK_BREAKS_UTC). Every screen said their market was shut from Friday
night to Sunday night, because every screen read Sauron's own clock (CME
Globex for the four commodities, the cash index and CME's week for the
two indices), the clock the guards read.

THE GUARDS KEEP THEIR CLOCK. Nothing here changes what the bots, the
paper venue, the care, Morgul, the Orcs' metronome, the bar writer or a
booking read: core.exchange_status.market_clock, market_status_for,
get_exchange_status, signals.market_hold.market_state and bot_program.
entry_timing answer exactly as before, and no money module imports this
one outside the display functions tests/test_all_week_money_pins.py
names. This module only says, for the screens, what to say instead.

ONE ANSWER, week(instrument, now): None when the screens keep Sauron's
own words (any other instrument, or an all-week one while Sauron's clock
is open, or inside one of its own short shuts that is not one of eToro's
published breaks). Otherwise:

  open    eToro trades it and Sauron's own clock is inside a shut of a
          day or more (the weekend): "open · eToro 24/7"
  pause   inside one of eToro's published breaks: "pause · eToro reopens
          23:00 UTC" (the Friday break reopens at 22:30, OIL's and
          NATGAS's Saturday break at 22:15)

and, at the weekend, what still holds on Sauron's clock:

  bots    "bots: no weekend entries, by your choice", only while the bots'
          own entry clock refuses it (entry_timing.shut_verdict: the four
          commodities; an index is no SHUT class, so SPX500 and NSDQ100
          never read it)
  paper   "paper: waits for CME's open, Sun 23:00 UTC": the paper venue
          keeps its clock (paper_trader.paper_market_shut)

Breaks eToro does not publish (SPX500, NSDQ100) are not invented: those
two read open at the weekend, and keep Sauron's words in its short shuts
(the CME daily break, in which eToro refused US index orders on
2026-10-01, entry_timing.INDEX_BREAK_NY).

GATE is read at call time: tests/__init__.py turns it off for a suite
whose pages render at whatever hour the wall clock says (a page rendered
at 22:30 UTC would read "pause"), and the tests of this change turn it
back on at a fixed clock. Clock arithmetic only: no database, no network;
never raises (None, Sauron's own words).
"""
from __future__ import annotations

import logging
from datetime import datetime
from datetime import timezone as dt_tz

logger = logging.getLogger(__name__)

#: Read at call time (see the module docstring).
GATE = True

OPEN, PAUSE = "open", "pause"
#: The words of an open all-week market.
OPEN_LABEL = "open · eToro 24/7"
#: The bots' weekend rule, said only while their entry clock refuses it.
BOTS_WORDS = "bots: no weekend entries, by your choice"
#: The hover of an id whose breaks eToro does not publish.
NO_BREAKS_WORDS = "short breaks; times not published"
#: The market badge of an all-week instrument: its own session code (the
#: badge poller, static/js/sv-market-status.js, repaints a badge by its
#: code, and CME's row would turn it back to CLOSED within a minute), its
#: name and its words.
BADGE_CODE = "ETORO247_{}"
BADGE_NAME = "eToro 24/7"
BADGE_OPEN, BADGE_PAUSE = "24/7", "PAUSE"

_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _utc(now):
    if now is None:
        return datetime.now(dt_tz.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=dt_tz.utc)
    return now.astimezone(dt_tz.utc)


def hhmm(moment) -> str:
    """"23:00" (UTC) for an aware datetime."""
    return moment.astimezone(dt_tz.utc).strftime("%H:%M")


def day_hhmm(moment) -> str:
    """"Sun 23:00 UTC" for an aware datetime, from a fixed table."""
    m = moment.astimezone(dt_tz.utc)
    return f"{_DAYS[m.weekday()]} {m:%H:%M} UTC"


def reopens_words(reopens) -> str:
    """"eToro reopens 23:00 UTC": a pause's second half."""
    return f"eToro reopens {hhmm(reopens)} UTC"


def pause_label(reopens) -> str:
    """"pause · eToro reopens 23:00 UTC"."""
    return f"{PAUSE} · {reopens_words(reopens)}"


def _span(window) -> str:
    return f"{window[0]:%H:%M}-{window[1]:%H:%M}"


def hint(etoro_id) -> str:
    """The breaks in words, from the published table (shut_bars.
    ALL_WEEK_BREAKS_UTC): "breaks 22:00-23:00 UTC daily, Fri 22:00-22:30"
    (", Sat 22:00-22:15" for OIL and NATGAS); NO_BREAKS_WORDS for an id
    whose breaks eToro does not publish."""
    from market_data.shut_bars import ALL_WEEK_BREAKS_UTC
    week = ALL_WEEK_BREAKS_UTC.get(etoro_id)
    if not week:
        return NO_BREAKS_WORDS
    parts = []
    daily = week[0]
    if daily:
        parts.append(f"{_span(daily)} UTC daily")
    for day in (4, 5):
        if week[day] and week[day] != daily:
            parts.append(f"{_DAYS[day]} {_span(week[day])}")
    return "breaks " + ", ".join(parts)


def _clock(cls, exchange, symbol, now):
    from core.exchange_status import market_clock
    return market_clock(cls, exchange or "", symbol=symbol or "",
                        now_utc=now)


def own_shut(instrument, now):
    """(closed, reopens, session) of the shut Sauron's own screens say
    holds `now` for `instrument`, or None while they say it is open.
    signals.market_hold.market_state's rule: an index while its cash
    session AND CME's futures week are both shut, any other class while
    its market clock reads shut. Raises on an unreadable clock (week()
    catches it)."""
    cls = str(getattr(instrument, "asset_class", "") or "").strip().lower()
    exchange = getattr(instrument, "exchange", "") or ""
    symbol = getattr(instrument, "symbol", "") or ""
    clock = _clock(cls, exchange, symbol, now)
    if not clock.get("modelled") or clock.get("is_open", True):
        return None
    closed, reopens = clock.get("closed"), clock.get("reopens")
    if cls == "index":
        fut = _clock("commodity", "CME", "", now)
        if fut.get("is_open", True):
            return None
        if fut.get("closed") is not None and (
                closed is None or fut["closed"] > closed):
            closed = fut["closed"]
        if fut.get("reopens") is not None and (
                reopens is None or fut["reopens"] < reopens):
            reopens = fut["reopens"]
    return closed, reopens, clock.get("session") or ""


def _long(shut) -> bool:
    """A shut of a day or more (the weekend), never a nightly or a daily
    break (shut_bars.SHUT_MIN_S, the bar rule's own bound)."""
    from market_data.shut_bars import SHUT_MIN_S
    if shut is None:
        return False
    closed, reopens = shut[0], shut[1]
    if closed is None or reopens is None:
        return False
    return (reopens - closed).total_seconds() >= SHUT_MIN_S


def _bots_hold(instrument, now) -> bool:
    """Whether the bots' own entry clock refuses `instrument` now on its
    shut exchange (entry_timing.shut_verdict, the SHUT refusal the bot
    lane records): read, never changed."""
    from bot_program import entry_timing
    v = entry_timing.shut_verdict(
        getattr(instrument, "symbol", "") or "",
        getattr(instrument, "asset_class", "") or "",
        exchange=getattr(instrument, "exchange", "") or "", now=now)
    return bool(v) and v.get("code") == entry_timing.SHUT


def paper_words(instrument, now) -> str:
    """"paper: waits for CME's open, Sun 23:00 UTC" while the paper
    venue's clock (market_clock, paper_trader.paper_market_shut's) is
    shut; "" while it is open or cannot say when it opens."""
    clock = _clock(
        str(getattr(instrument, "asset_class", "") or "").strip().lower(),
        getattr(instrument, "exchange", "") or "",
        getattr(instrument, "symbol", "") or "", now)
    if not clock.get("modelled") or clock.get("is_open", True):
        return ""
    reopens = clock.get("reopens")
    if reopens is None:
        return ""
    session = str(clock.get("session") or "its market").replace("_", " ")
    return f"paper: waits for {session}'s open, {day_hhmm(reopens)}"


def week(instrument, now=None):
    """What the screens say of `instrument`'s market at `now` (the module
    docstring), or None when they keep Sauron's own words.

      {"state": "open" | "pause", "etoro_id", "name" (eToro's),
       "label": "open · eToro 24/7" | "pause · eToro reopens 23:00 UTC",
       "opens": "" | "eToro reopens 23:00 UTC",
       "since", "reopens": a pause's start and end (aware UTC),
       "after": a pause: the words once it ends ("open · eToro 24/7"
                while Sauron's own clock is still shut then, else ""),
       "until": when the open words end (Sauron's own clock reopens),
       "next_pause": (start, end) of eToro's next published break before
                "until" (open only), else None,
       "weekend": Sauron's own clock is inside a shut of a day or more,
       "bots": BOTS_WORDS while the bots' entry clock refuses it at the
               weekend, else "",
       "paper": paper_words(...) at the weekend or in a pause, else "",
       "hint": hint(etoro_id)}"""
    if not GATE:
        return None
    try:
        from market_data.shut_bars import all_week_state
        now = _utc(now)
        aw = all_week_state(instrument, now)
        if aw is None:
            return None
        shut = own_shut(instrument, now)
        weekend = _long(shut)
        out = {"state": aw["state"], "etoro_id": aw["etoro_id"],
               "name": aw["name"], "label": OPEN_LABEL, "opens": "",
               "since": None, "reopens": None, "after": "", "until": None,
               "next_pause": None, "weekend": weekend, "bots": "",
               "paper": "", "hint": hint(aw["etoro_id"])}
        if aw["state"] == PAUSE:
            reopens = aw["reopens"]
            out.update(label=pause_label(reopens),
                       opens=reopens_words(reopens), since=aw["since"],
                       reopens=reopens)
            later = own_shut(instrument, reopens)
            if later is not None:
                out.update(after=OPEN_LABEL, until=later[1])
            out["paper"] = paper_words(instrument, now)
        elif not weekend:
            return None
        else:
            out["until"] = shut[1]
            nxt = aw.get("next_pause")
            if nxt is not None and (shut[1] is None or nxt[0] < shut[1]):
                out["next_pause"] = nxt
            out["paper"] = paper_words(instrument, now)
        if weekend and _bots_hold(instrument, now):
            out["bots"] = BOTS_WORDS
        return out
    except Exception as e:  # noqa: BLE001 — Sauron's own words stand
        logger.info("[all week] %s unread at %s: %s",
                    getattr(instrument, "symbol", instrument), now, e)
        return None


def label(instrument, now=None) -> str:
    """What a signal announced now says of its market, where
    signals.market_hold.shut_label said it (the new-signal banner, the
    Telegram message and its email and WhatsApp copies, the bell): for an
    all-week instrument the screens show open or paused, "open · eToro
    24/7 · bots: no weekend entries, by your choice" (the bots' words only
    while their clock refuses it), "pause · eToro reopens 23:00 UTC";
    otherwise shut_label's own words ("" on an open market, so its
    announcement keeps its bytes). Never raises."""
    wk = week(instrument, now)
    if wk is None:
        from signals.market_hold import shut_label
        return shut_label(instrument, now=now)
    return " · ".join(x for x in (wk["label"], wk["bots"]) if x)


def card_words(wk):
    """A signal's words for an all-week instrument the screens show open
    or paused (the rail's card, its popup, the headband's dropdown row and
    /signals/), from week()'s answer; None for None:

      {"tag": "OPEN 24/7" | "PAUSE", "note": "at eToro" | "eToro reopens
       23:00 UTC", "title" (the hover: eToro's breaks, the bots' choice
       while their clock refuses it, the paper venue's wait, the live
       ticket), "pop" (the popup's market line: "open · eToro 24/7 · bots:
       no weekend entries, by your choice · paper: waits for CME's open,
       Sun 23:00 UTC; a live ticket fills at eToro"), "pause"}"""
    if not wk:
        return None
    pause = wk["state"] == PAUSE
    live = ("a live order waits for eToro's reopening" if pause
            else "a live ticket fills at eToro")
    tail = "; ".join(x for x in (wk["paper"], live) if x)
    pop = " · ".join(x for x in (wk["label"], wk["bots"], tail) if x)
    name = wk.get("name") or "it"
    if pause:
        title = (f"eToro pauses {name} until "
                 f"{hhmm(wk['reopens'])} UTC ({wk['hint']}).")
    else:
        title = f"Open at eToro, which trades {name} all week ({wk['hint']})."
    if wk["bots"]:
        title += f" {wk['bots'][:1].upper()}{wk['bots'][1:]}."
    title += f" {tail[:1].upper()}{tail[1:]}."
    return {"tag": BADGE_PAUSE if pause else "OPEN 24/7",
            "note": wk["opens"] if pause else "at eToro",
            "title": title, "pop": pop, "pause": pause}


def market_line(instrument, now=None, venue="eToro") -> str:
    """The Horde dossier's Market line for a row held at eToro of an
    all-week instrument, all week (as the badge): "eToro: trades GOLD 24/7
    (breaks 22:00-23:00 UTC daily, Fri 22:00-22:30). Open." with "Bots: no
    weekend entries, by your choice." while the bots' clock refuses it at
    the weekend, "... Pause · eToro reopens 23:00 UTC." in a break; "" for
    any other instrument, or with GATE off. Never raises."""
    if not GATE:
        return ""
    try:
        from market_data.shut_bars import all_week_state
        at = _utc(now)
        aw = all_week_state(instrument, at)
        if aw is None:
            return ""
        state = ("Open" if aw["state"] == OPEN
                 else f"Pause · {reopens_words(aw['reopens'])}")
        out = (f"{venue or 'eToro'}: trades {aw['name']} 24/7 "
               f"({hint(aw['etoro_id'])}). {state}.")
        wk = week(instrument, at)
        if wk is not None and wk["bots"]:
            out += f" {wk['bots'][:1].upper()}{wk['bots'][1:]}."
        return out
    except Exception as e:  # noqa: BLE001 — Sauron's own line stands
        logger.info("[all week] market line unread for %s: %s",
                    getattr(instrument, "symbol", instrument), e)
        return ""


#: eToro's own note on its 24/7 assets at the weekend (its help centre,
#: "Trading 24/7 on eToro", read 2026-11-15 and 2026-11-19: market orders
#: only, prices that follow other markets, wider spreads), in its words'
#: substance.
ETORO_WEEKEND_NOTE = ("eToro trades {name} all week; at the weekend only "
                      "market orders, and spreads may be wider (eToro's "
                      "note)")
#: In one of eToro's breaks, "orders can be set to be executed when markets
#: reopen" (its market-hours page, read 2026-11-19).
ETORO_PAUSE_NOTE = "an order now waits for eToro's reopening (eToro's note)"


def ticket_words(instrument, advisory=None, now=None, *, live=True):
    """The TAKE TRADE popup's words for an all-week instrument where its
    entry clock says the market is shut (the advisory's code SHUT): a
    display key beside the preview, never in it (manual_trade's
    timing_advisory, and the booking's record of it, are untouched).
    None for any other instrument or advisory, or with GATE off.

      {"state": "open" | "pause", "head": "OPEN · eToro 24/7" | "PAUSE ·
       eToro reopens 23:00 UTC", "lines": [eToro's note; the bots' choice
       while their clock refuses it; "Sauron's clock (CME) is shut: a
       booking now is one Morgul G1 would flag" when the advisory says G1
       would flag it], "paper": the paper venue's clock (a paper ticket)}"""
    adv = advisory or {}
    if adv.get("code") != "SHUT":
        return None
    wk = week(instrument, now)
    if wk is None:
        return None
    pause = wk["state"] == PAUSE
    name = wk.get("name") or "it"
    lines = [ETORO_PAUSE_NOTE if pause
             else ETORO_WEEKEND_NOTE.format(name=name)]
    if wk["bots"]:
        lines.append(wk["bots"])
    if "Morgul G1 would flag" in str(adv.get("reason") or ""):
        session = ""
        try:
            shut = own_shut(instrument, _utc(now))
            session = shut[2] if shut else ""
        except Exception:  # noqa: BLE001 — the clause without the name
            session = ""
        clock = f"Sauron's clock ({session})" if session else "Sauron's clock"
        lines.append(f"{clock} is shut: a booking now is one Morgul G1 "
                     f"would flag")
    out = {"state": wk["state"],
           "head": (f"PAUSE · {wk['opens']}" if pause
                    else "OPEN · eToro 24/7"),
           "lines": lines, "hint": wk["hint"]}
    if not live:
        out["paper"] = (f"{wk['paper'] or 'paper: waits for its market'}; "
                        f"eToro itself trades {name} 24/7")
    return out


#: An overdue metronome while Sauron's own clock is shut is the metronome
#: resting there (the Orcs' W11 runs no tick on a shut market), not a
#: fault, and eToro trades the instrument meanwhile.
NEXT_WAKE_RESTS = ("Next wake: the metronome rests on Sauron's {session} "
                   "clock until {when} UTC; eToro trades {name} 24/7.")


def wake_words(trade, due, now=None, minds=None, *, clock=None) -> str:
    """The Orc's next wake in words (bot_program.orcs.notes.slot) for one
    of eToro's all-week instruments while the metronome rests on Sauron's
    own clock (NEXT_WAKE_RESTS), or "" for the usual words (notes.
    next_wake_t): the wake must be overdue, the instrument one the screens
    show open or paused at eToro (week), and W11's own clock shut now.
    `clock` is that clock (orcs.sessions.next_shut), handed in by the slot
    so this reader never imports the Orcs. The metronome, its clock and
    its wakes are untouched. Never raises."""
    try:
        if trade is None or not due or clock is None:
            return ""
        at = _utc(now)
        moment = due if isinstance(due, datetime) else \
            datetime.fromisoformat(str(due))
        moment = _utc(moment)
        if moment >= at:
            return ""
        from types import SimpleNamespace
        cls = str(getattr(trade, "asset_class", "") or "")
        sym = str(getattr(trade, "symbol", "") or "")
        wk = week(SimpleNamespace(symbol=sym, asset_class=cls, exchange=""),
                  at)
        if wk is None:
            return ""
        shut = clock(cls, sym, at)
        if not shut or not shut.get("now_shut") or not shut.get("reopens"):
            return ""
        reopens = _utc(shut["reopens"])
        when = (f"{reopens:%H:%M}" if reopens.date() == at.date()
                else f"{reopens:%a %d %b %H:%M}")
        words = NEXT_WAKE_RESTS.format(
            session=str(shut.get("session") or "").replace("_", " ")
            or "own", when=when, name=wk.get("name") or sym)
        if minds is False:
            words += " Detected and recorded only, no model."
        return words
    except Exception as e:  # noqa: BLE001 — the usual words stand
        logger.info("[all week] wake words unread: %s", e)
        return ""


def _badge_words(aw) -> dict:
    open_ = aw["state"] == OPEN
    return {
        "name": BADGE_NAME, "is_open": open_, "pause": not open_,
        "word": BADGE_OPEN if open_ else BADGE_PAUSE,
        "title": (f"{OPEN_LABEL} ({hint(aw['etoro_id'])})" if open_
                  else pause_label(aw["reopens"])),
        "next_state": "" if open_ else "opens",
        "time_until_change": ""}


def badge(instrument, market, now=None):
    """The market badge for `instrument` (market_status_for's shape, the
    instrument page's and the instruments list's): for an all-week
    instrument, eToro's own, all week: "24/7" (title "open · eToro 24/7
    (breaks ...)"), "PAUSE" in a published break (title "pause · eToro
    reopens 23:00 UTC"), under its own session code (BADGE_CODE) so the
    poller repaints it from its own row (badge_rows); `market` itself for
    any other instrument, or with GATE off."""
    if not GATE or market is None:
        return market
    try:
        from market_data.shut_bars import all_week_state
        aw = all_week_state(instrument, _utc(now))
        if aw is None:
            return market
        out = dict(market)
        out.update(_badge_words(aw), session=BADGE_CODE.format(
            aw["etoro_id"]), code=BADGE_CODE.format(aw["etoro_id"]))
        return out
    except Exception as e:  # noqa: BLE001 — Sauron's own badge stands
        logger.info("[all week] badge unread for %s: %s",
                    getattr(instrument, "symbol", instrument), e)
        return market


def badge_rows(now=None) -> list:
    """One row per eToro all-week id for /api/exchange-status/ (beside the
    exchanges and the product sessions, never in their count): {"code",
    "name", "is_open", "pause", "word", "title", "next_state",
    "time_until_change"}. [] with GATE off. Never raises."""
    if not GATE:
        return []
    try:
        from market_data.shut_bars import ALL_WEEK_ETORO_IDS, all_week_state
        at = _utc(now)
        out = []
        for iid in ALL_WEEK_ETORO_IDS:
            aw = all_week_state(etoro_id=iid, now=at)
            if aw is not None:
                out.append({"code": BADGE_CODE.format(iid),
                            **_badge_words(aw)})
        return out
    except Exception as e:  # noqa: BLE001
        logger.info("[all week] badge rows unread: %s", e)
        return []


def payload(wk) -> dict | None:
    """The one price's "wk" (market_data/one_quote.py, mirrored in
    static/js/sv-venue.js) from week()'s answer, times as datetimes (the
    payload writes them in ms): {"open": the words before an open price
    ("" in a pause that Sauron's own clock does not outlast), "until":
    when they end, "np": eToro's next break while open ({"since",
    "reopens", "label", "opens", "word"}), "hint"}; None for None."""
    if not wk:
        return None
    np = None
    if wk["state"] == OPEN and wk.get("next_pause"):
        start, end = wk["next_pause"]
        np = {"since": start, "reopens": end, "label": pause_label(end),
              "opens": reopens_words(end), "word": PAUSE}
    return {"open": wk["label"] if wk["state"] == OPEN else wk["after"],
            "until": wk["until"], "np": np,
            "hint": f"eToro 24/7: {wk['hint']}"}


def shut(wk) -> dict | None:
    """The one price's shut for a pause (one_quote's own shape, its word
    "pause": the browser flips it open at its end by itself); None
    otherwise."""
    if not wk or wk["state"] != PAUSE:
        return None
    return {"since": wk["since"], "label": wk["label"], "opens": wk["opens"],
            "reopens": wk["reopens"], "word": PAUSE}
