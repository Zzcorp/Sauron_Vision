"""THE POWER OF THREE (2026-10-03): accumulation, manipulation, distribution —
the day read by its sessions.

The operator: "include the consolidation, manipulation and distribution
often linked to the market sessions; very important". ICT's Power of
Three: a trading day has three parts. ASIA consolidates — a small range
where the orders and the stops build up on both sides (accumulation).
LONDON manipulates — the first move runs ONE side of that range to take
the stops resting there, the Judas swing, and turns. NEW YORK distributes
— the real move, the other way, toward the pools on the far side. Reading
which part the day is in says what the next move most likely is: inside
the range, wait for the run; a run through one side that came back
inside, the manipulation is done and the distribution points the other
way; a run that holds past the range, either the manipulation still
running or a true break — the tell is a close back inside.

What is read, on the 1h bars (POWER_TIMEFRAME) when there are enough,
else the 4h:
  THE SESSION   the ICT session the clock is in now
                (signals/smc/sessions.in_ny_session: asia, london, ny_am,
                ny_lunch, ny_pm), New-York-anchored, or "off" between the
                New York close and the Asian open.
  THE RANGE     today's Asian range (ICT_SESSIONS_NY "asia", 20:00 to
                midnight New York): the accumulation.
  THE RUN       since the range closed: did the price run through its high,
                its low, both, neither; where the run reached; where the
                price stands now.
  THE JUDAS     London's Judas swing when the detector sees one today
                (signals/smc/session_setups.detect_judas_swings): the
                manipulation named by its own numbers.
  THE PHASE     accumulation / manipulation / distribution / unclear, and
                the direction the distribution points when it is known.

Judged by the proving ground like every claim here: the `po3` family
(backtester/proving/families.py) fires on the first bar back inside the
Asian range after a run through one side only — the moment this module
calls "distribution" — in the direction away from the run.

Information, never a gate: the positioning map carries it, the chart
draws the Asian range, the ticket and the review read the words. Nothing
raises; a day that cannot be read says so.

THE STAGES (2026-10-08): `stages` carries what the chart draws: the London
and New York windows of the trading day by the sessions table, each run of
an Asian edge with its bar and its return, and the trading day's Judas
swing with its bar times. Display only: the positioning map keeps it out
of `compact()`, which the ticket and the position reviewer read.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from django.utils import timezone

logger = logging.getLogger(__name__)

POWER_TIMEFRAME = "1h"
#: Fewer 1h bars than this and the 4h bars are read instead.
MIN_BARS_1H = 48
#: Fewer bars than this at all: unread.
MIN_BARS = 12
#: A range older than this is yesterday's day, not today's.
RANGE_MAX_AGE_H = 30
#: The sessions, in the day's order, with the part they play.
SESSION_PART = {"asia": "accumulation", "london": "manipulation",
                "ny_am": "distribution", "ny_lunch": "distribution",
                "ny_pm": "distribution"}

ACCUMULATION, MANIPULATION, DISTRIBUTION, UNCLEAR, UNREAD = (
    "accumulation", "manipulation", "distribution", "unclear", "unread")


def session_now(now=None) -> str:
    """The ICT session the clock is in: asia, london, ny_am, ny_lunch,
    ny_pm, or "off" (between sessions), "unknown" without a tz database."""
    from signals.smc.sessions import ICT_SESSIONS_NY, in_ny_session
    now = now or timezone.now()
    for name in ("asia", "london", "ny_am", "ny_lunch", "ny_pm"):
        if name not in ICT_SESSIONS_NY:
            continue
        hit = in_ny_session(now, name)
        if hit is None:
            return "unknown"
        if hit:
            return name
    return "off"


def _frame(symbol, bars=None):
    """(df, swings, timeframe): the 1h bars when there are enough, else the
    4h; `bars` = (df, swings, timeframe) to read instead of loading."""
    if bars is not None:
        return bars
    from bot_program import smart_money as sm
    df, swings = sm._bars(symbol, POWER_TIMEFRAME)
    if df is not None and len(df) >= MIN_BARS_1H:
        return df, swings, POWER_TIMEFRAME
    df4, swings4 = sm._bars(symbol, "4h")
    if df4 is not None and len(df4) >= MIN_BARS:
        return df4, swings4, "4h"
    return df, swings, POWER_TIMEFRAME


def asian_range(df, *, now=None):
    """{high, low, date, start, end, last_pos} of the newest Asian range in
    the frame, or None when there is none inside RANGE_MAX_AGE_H."""
    from signals.smc.sessions import session_windows
    if df is None or len(df) == 0:
        return None
    windows = session_windows(df, "asia")
    if not windows:
        return None
    w = windows[-1]
    end = pd.Timestamp(w["end_ts"])
    if end.tzinfo is None:
        end = end.tz_localize("UTC")
    now = pd.Timestamp(now or timezone.now())
    if now.tzinfo is None:
        now = now.tz_localize("UTC")
    if (now - end).total_seconds() > RANGE_MAX_AGE_H * 3600:
        return None
    sub = df.iloc[w["positions"]]
    return {"high": float(sub["high"].max()), "low": float(sub["low"].min()),
            "date": str(w["date"]), "start": str(w["start_ts"]),
            "end": str(w["end_ts"]), "last_pos": int(w["positions"][-1])}


def _span(df, rng):
    """{opened, closed}: the Asian session's first bar open and last bar
    close in epoch seconds, or {} when the stamps cannot be read."""
    try:
        def ep(v):
            t = pd.Timestamp(v)
            return int((t.tz_localize("UTC") if t.tzinfo is None else t).timestamp())
        step = pd.Series(df.index).diff().median()
        bar = int(step.total_seconds()) if pd.notna(step) else 0
        return {"opened": ep(rng["start"]), "closed": ep(rng["end"]) + bar}
    except Exception:  # noqa: BLE001 - a box is a bonus to the two prices
        return {}


#: The windows the chart marks after the Asian range, by the sessions table
#: (signals/smc/sessions.ICT_SESSIONS_NY): London is the manipulation's,
#: New York AM's open to New York PM's close the distribution's.
STAGE_WINDOWS = {"london": ("london", "london"), "new_york": ("ny_am", "ny_pm")}


def _epoch(ts) -> int:
    t = pd.Timestamp(ts)
    return int((t.tz_localize("UTC") if t.tzinfo is None else t).timestamp())


def _ny_clock(ts):
    """'HH:MM' on the New York wall clock of a UTC stamp; None without a tz
    database."""
    from signals.smc.sessions import new_york_timezone
    tz = new_york_timezone()
    if tz is None:
        return None
    t = pd.Timestamp(ts)
    t = t.tz_localize("UTC") if t.tzinfo is None else t
    return t.tz_convert(tz).strftime("%H:%M")


def _window(day, first, last, now):
    """{opened, closed, state, ny}: the sessions table's `first` start to
    `last` end on the New York date `day`, as UTC epoch seconds; state
    'upcoming' | 'open' | 'closed' at `now`; ny '02:00–05:00'. None without
    a tz database or an unknown name.

    datetime.combine(..., tzinfo=ZoneInfo) takes fold 0: on the
    spring-forward Sunday 02:00 does not exist and maps to 07:00 UTC (03:00
    EDT), so London is two hours long that night — as in_ny_session's bar
    membership has it."""
    from datetime import datetime
    from signals.smc.sessions import ICT_SESSIONS_NY, new_york_timezone
    tz = new_york_timezone()
    if tz is None or first not in ICT_SESSIONS_NY or last not in ICT_SESSIONS_NY:
        return None
    start, end = ICT_SESSIONS_NY[first][0], ICT_SESSIONS_NY[last][1]
    o = int(datetime.combine(day, start, tzinfo=tz).timestamp())
    c = int(datetime.combine(day, end, tzinfo=tz).timestamp())
    n = _epoch(now)
    return {"opened": o, "closed": c,
            "state": "upcoming" if n < o else ("open" if n < c else "closed"),
            "ny": f"{start:%H:%M}–{end:%H:%M}"}


def _ny_span(ts, bar):
    """'HH:MM–HH:MM' on the New York wall clock, a bar's open to its close;
    None without a tz database."""
    a = _ny_clock(ts)
    b = _ny_clock(pd.Timestamp(ts) + pd.Timedelta(seconds=bar))
    return None if a is None or b is None else f"{a}–{b}"


def _bar_session(ts, bar):
    """The first ICT session a bar [ts, ts + bar) overlaps — a 4h bar
    straddles the sessions, and the clock at its open said 'off' for a
    London run (2026-10-15) — else 'off'; 'unknown' without a tz database."""
    from datetime import datetime, timedelta
    from signals.smc.sessions import ICT_SESSIONS_NY, new_york_timezone
    tz = new_york_timezone()
    if tz is None:
        return "unknown"
    t0 = pd.Timestamp(ts)
    t0 = t0.tz_localize("UTC") if t0.tzinfo is None else t0
    t1 = t0 + pd.Timedelta(seconds=bar)
    lo, hi = t0.tz_convert(tz), t1.tz_convert(tz)
    days = {lo.date() - timedelta(days=1), lo.date(), hi.date()}
    best = None
    for name in ("asia", "london", "ny_am", "ny_lunch", "ny_pm"):
        if name not in ICT_SESSIONS_NY:
            continue
        start, end = ICT_SESSIONS_NY[name]
        for day in days:
            s = pd.Timestamp(datetime.combine(day, start, tzinfo=tz))
            e = pd.Timestamp(datetime.combine(day + timedelta(days=1 if end <= start else 0),
                                              end, tzinfo=tz))
            if s < t1 and e > t0 and (best is None or s < best[0]):
                best = (s, name)
    return best[1] if best else "off"


def _sweeps(rest, rng, bar=3600):
    """The run of each Asian edge since the range closed, in time order
    (a low before a high on one bar): {side, edge, price, at, ny, session,
    back_at, back_close_at, back_price, back_ny}. `at` is the FIRST bar
    holding the run's extreme; `back_at` the first bar at or after it whose
    close is back inside (the same strictness as read_day's back_inside),
    `back_close_at` that bar's close, else None. On a read wider than an
    hour (the 4h, when the 1h tape is short) one bar spans the sessions:
    `ny` is then the bar's span ('00:00–04:00'), `session` the first
    session the bar overlaps and `back_ny` the return bar's close."""
    out = []
    closes = rest["close"].to_numpy(dtype=float)
    wide = bar > 3600
    for side in ("low", "high"):
        col = rest[side].to_numpy(dtype=float)
        ext = float(col.min() if side == "low" else col.max())
        if not (ext < rng["low"] if side == "low" else ext > rng["high"]):
            continue
        pos = int(np.flatnonzero(col == ext)[0])
        back = next((i for i in range(pos, len(rest))
                     if (closes[i] > rng["low"] if side == "low"
                         else closes[i] < rng["high"])), None)
        at = rest.index[pos]
        bk = None if back is None else rest.index[back]
        bk_close = None if bk is None else pd.Timestamp(bk) + pd.Timedelta(seconds=bar)
        out.append({"side": side, "edge": float(rng[side]), "price": ext,
                    "at": _epoch(at),
                    "ny": _ny_span(at, bar) if wide else _ny_clock(at),
                    "session": _bar_session(at, bar) if wide else session_now(at),
                    "back_at": None if bk is None else _epoch(bk),
                    "back_close_at": None if bk is None else _epoch(bk_close),
                    "back_price": None if back is None else float(closes[back]),
                    "back_ny": None if bk is None else _ny_clock(bk_close if wide else bk)})
    out.sort(key=lambda s: (s["at"], 0 if s["side"] == "low" else 1))
    return out


def _judas_today(df, found, day):
    """London's Judas swing on the TRADING day (the date London opens on,
    the Asian date + 1), with the bar times the chart draws it at; None
    when the detector names none that day."""
    from signals.smc.sessions import session_windows
    today = [s for s in found if str(s.get("session_date")) == str(day)]
    win = [w for w in session_windows(df, "london") if str(w["date"]) == str(day)]
    if not today or not win:
        return None
    s, first = today[-1], df.index[win[0]["positions"][0]]
    return {"direction": s["direction"], "open": float(s["session_open"]),
            "open_at": _epoch(first), "open_ny": _ny_clock(first),
            "extreme": float(s["judas_price"]),
            "extreme_at": _epoch(s["judas_ts"]), "extreme_ny": _ny_clock(s["judas_ts"]),
            "words": s.get("why_now", "")}


def _stages(df, rng, rest, found, now):
    from datetime import date, timedelta
    day = date.fromisoformat(rng["date"]) + timedelta(days=1)
    step = pd.Series(df.index).diff().median()
    bar = int(step.total_seconds()) if pd.notna(step) else 0
    return {"date": day.isoformat(),
            "bar": bar,
            "london": _window(day, *STAGE_WINDOWS["london"], now),
            "new_york": _window(day, *STAGE_WINDOWS["new_york"], now),
            "sweeps": _sweeps(rest, rng, bar or 3600) if len(rest) else [],
            "judas": _judas_today(df, found, day)}


def _stages_or_none(df, rng, rest, found, now):
    try:
        return _stages(df, rng, rest, found, now)
    except Exception as e:  # noqa: BLE001 - a drawing is a bonus to the read
        logger.debug("[po3] stages unread: %s", e)
        return None


def read_day(df, swings=None, *, now=None) -> dict:
    """The three parts of the day on one frame — pure, no I/O:
    {ok, phase, direction, session, asia, run: {below, above, low, high},
    mark, judas, why, stages}.

    `stages` (2026-10-08) is what the chart draws of the three parts, None
    on every unread path: {date, bar, london: {opened, closed, state, ny}
    | None, new_york: same, sweeps: [{side, edge, price, at, ny, session,
    back_at, back_close_at, back_price, back_ny}], judas: {direction, open,
    open_at, open_ny, extreme, extreme_at, extreme_ny, words} | None}.
    `date` is the trading day (the Asian date + 1), `bar` the frame's bar
    in seconds; every time is UTC epoch seconds, every `ny` the New York
    wall clock (a 4h bar's span, as _sweeps says)."""
    now = now or timezone.now()
    out = {"ok": False, "phase": UNREAD, "direction": None,
           "session": session_now(now), "asia": None, "run": None,
           "mark": None, "judas": None, "why": "", "stages": None}
    if df is None or len(df) < MIN_BARS:
        out["why"] = "too few bars to read the day"
        return out
    rng = asian_range(df, now=now)
    if rng is None:
        out["why"] = "no Asian range in the frame for today"
        return out
    out["asia"] = {k: rng[k] for k in ("high", "low", "date")}
    # The session's span as epoch seconds (2026-10-07), so the chart draws
    # the accumulation as the box it is rather than two endless lines:
    # the first bar's open and the last bar's close.
    out["asia"].update(_span(df, rng))
    rest = df.iloc[rng["last_pos"] + 1:]
    mark = float(df["close"].values[-1])
    out["mark"] = mark
    # The Judas detector's list, kept for the stages (the chart's London is
    # the trading day's): empty until it runs below.
    found = []

    def _done():
        # What the chart draws (2026-10-08), read last: no key above moves.
        out["stages"] = _stages_or_none(df, rng, rest, found, now)
        return out

    if rest.empty:
        out.update(ok=True, phase=ACCUMULATION,
                   run={"below": False, "above": False, "low": None,
                        "high": None},
                   why="inside the Asian range, nothing has run either side")
        return _done()
    lo, hi = float(rest["low"].min()), float(rest["high"].max())
    below, above = lo < rng["low"], hi > rng["high"]
    out["run"] = {"below": bool(below), "above": bool(above),
                  "low": lo if below else None, "high": hi if above else None}
    # London's Judas swing today, when the detector names one.
    try:
        from signals.smc.session_setups import detect_judas_swings
        if swings:
            found = detect_judas_swings(df, swings, session="london")
            today = [s for s in found if str(s.get("session_date")) == rng["date"]]
            if today:
                s = today[-1]
                out["judas"] = {"direction": s["direction"],
                                "open": float(s["session_open"]),
                                "extreme": float(s["judas_price"]),
                                "words": s.get("why_now", "")}
    except Exception as e:  # noqa: BLE001 — the judas is a bonus read
        logger.debug("[po3] judas unread: %s", e)

    if below and above:
        out.update(ok=True, phase=UNCLEAR,
                   why="both sides of the Asian range were run: no clean "
                       "three-part day")
        return _done()
    if not below and not above:
        out.update(ok=True, phase=ACCUMULATION,
                   why="inside the Asian range, nothing has run either side")
        return _done()
    side = "low" if below else "high"
    back_inside = (mark > rng["low"]) if below else (mark < rng["high"])
    if back_inside:
        out.update(ok=True, phase=DISTRIBUTION,
                   direction="up" if below else "down",
                   why=(f"the {side}s of the Asian range were run "
                        f"({(lo if below else hi):g}) and the price came back "
                        f"inside: the manipulation is done, the distribution "
                        f"points {'up' if below else 'down'}"))
    else:
        out.update(ok=True, phase=MANIPULATION,
                   why=(f"the {side}s of the Asian range were run "
                        f"({(lo if below else hi):g}) and the price holds "
                        f"{'under' if below else 'over'} it: the manipulation "
                        f"still running, or a true break — a close back "
                        f"inside tells"))
    return _done()


def words_for(day: dict) -> str:
    """One sentence for the ticket, the caption and the review."""
    if not day.get("ok"):
        return f"Power of Three unread: {day.get('why') or 'no read'}."
    a = day["asia"]
    sess = day.get("session") or "off"
    part = SESSION_PART.get(sess)
    where = (f"the {sess.replace('_', ' ')} session"
             + (f", the day's {part}" if part else "")) if sess not in (
        "off", "unknown") else "between sessions"
    s = (f"Power of Three ({where}): Asia consolidated {a['low']:g}–"
         f"{a['high']:g}; {day['why']}.")
    if day.get("judas"):
        j = day["judas"]
        s += (f" London's Judas swing: opened {j['open']:g}, faked to "
              f"{j['extreme']:g}, reversed ({j['direction'].lower()}).")
    return s


def power_of_three(symbol, *, now=None, bars=None) -> dict:
    """The day's three parts for `symbol`: read_day on the 1h bars (else
    the 4h), with `timeframe` and `words`. Never raises."""
    now = now or timezone.now()
    try:
        df, swings, timeframe = _frame(symbol, bars)
        day = read_day(df, swings, now=now)
    except Exception as e:  # noqa: BLE001 — an unread day, said
        logger.info("[po3] %s unread: %s", symbol, e)
        day = {"ok": False, "phase": UNREAD, "direction": None,
               "session": session_now(now), "asia": None, "run": None,
               "mark": None, "judas": None, "why": f"unread: {e}"[:160],
               "stages": None}
        timeframe = POWER_TIMEFRAME
    day["timeframe"] = timeframe
    day["symbol"] = symbol
    day["words"] = words_for(day)
    return day
