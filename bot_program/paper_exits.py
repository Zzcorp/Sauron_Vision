"""A paper stop books like a resting stop (2026-10-08).

WHY. A paper GBPUSD BUY opened 2026-09-03 with its stop about 30 pips
under the entry, was booked on 2026-09-28 at -8.12R. A paper stop was only a
per-tick comparison (base.manage_positions: the one mark of the tick against
the level), and nothing had managed the row for weeks (its config was off,
or the platform paused), so the first tick that acted booked it at the far
price it saw, at the time it saw it. A stop resting at a broker would have
filled at the stop, or at the open of the bar that gapped through it, when
that bar traded. The reverse was just as wrong: a crossing that came back
before the next tick was never booked, and a gap the mark had recovered
from booked better than any resting stop could have. The promotion ladder
promotes rules to real money on their paper record, so the first bars a good
rule and the second flatters a bad one.

WHAT. On every managed tick of a PAPER row (base.manage_positions, right
after the shut-market wait and before the mark is read), the bars the row
has not yet been tested against are walked oldest first:
  - a stop crossed (a BUY's low at or under it) books at the stop, or at the
    bar's open when the bar opened through it (a gap) and the gap is
    confirmed (2026-10-15): the bar's own close, or the next bar's open, is
    through the stop too, or sits within the class's one-print jump bar
    (mark_sanity.JUMP_PCT) of that open, the proving ground's return-bar
    rule at the scale of one print. An open through the stop that neither
    confirms is one print (a bad tick, not a market) and books at the stop.
    With no next bar yet, the crossing waits up to GAP_CONFIRM_WAIT past
    the bar's end for it;
  - a target crossed books at the target, never better, even when the bar
    gapped through it;
  - both in one bar: the stop (nothing in a bar says which came first, and
    the record that sizes real money must not be flattered);
  - the booking is stamped at the crossing bar's time (closed_at), not at
    the tick that noticed it.
A SELL is the mirror. The price level is always one the bar traded; the
modelled half cost is then charged on top of it, as on every paper exit
(base._close_trade): a stop touched at the bar's low pays the cost like a
stop crossed deep (2026-10-15: the old clamp to the bar's worst price
waived it).

THE BARS. market_data.PriceData, 1h first (its timestamp is the bar's
OPEN, bot_bars), a 4h bar for any stretch the 1h bars leave uncovered while
the market was in session (a hole in the 1h series is tested on the 4h bar
that holds it, 2026-10-15). A bar is tested while it is not yet COMPLETE
behind the row's cursor (`bars_through`: the end of the newest complete bar
already tested), so the forming bar is tested again on the next tick. An
in-session hole in the 1h bars younger than the reopen grace holds the
cursor at its start, so an hourly bar written late is still read. The bar
that contains the fill is never tested (part of its range predates the
position).

THE BAR SANITY (2026-10-15). A stored bar is not trusted because it is
stored: the proving ground documents near-zero prints and spikes in these
very series (backtester/proving/data.py). Each bar's open, high, low and
close must sit within that module's max_jump (by class) of the last
accepted close (the row's entry for the first bar); a bar past it is
dropped, unless LEVEL_SHIFT_BARS of them in a row agree on one new level
(a market that moved and held, kept as it traded). A bar still waiting on
that verdict holds the cursor. And the bars must be the row's own
instrument: a paper row priced off one feed (Yahoo's gold FUTURES, through
PaperTrader's LiveQuote) and barred off another (eToro's spot CFD) is a
basis, not a crossing. When the bars around the opening do not hold the
row's own entry (within the modelled round trip plus BASIS_TOL), the row is
not replayed (history "basis") and is managed on the mark as before.

THE CLOCK. A bar the paper market clock calls shut for its whole span is
skipped (a poller's re-stamp, not a trade). One that STARTS shut and opens
inside (the hour-stamped 13:00 bar holding the 13:30 US open, the 4h bar
holding the Sunday 21:00 FX reopen) books at the end of the settling
quarter hour after that open, the first moment the paper venue may exit;
so does one that starts inside the settling window.

THE LEVELS (2026-10-15). The stop in force is the tighter of the row's stop
and, while the position care runs (the aragorn switch), its soft stop. They
move on a managed tick (trailing, break-even, the care, a scale-out), after
that tick's replay, or by hand (adjust_levels, level_edits) between ticks.
Each stamp keeps the HISTORY of the levels (`moves`: [at, stop, target],
each in force from `at` until the next), and each bar is tested against the
LOOSEST stop and target in force at any moment of its span. The stamp of
the last tick alone was not enough: a 1h bar sees about twelve ticks, and
two ticks after a break-even move the bar's low from before the move was
tested against the moved stop and booked a stop-out that never happened.
A row with no stamp (opened before this module, or never managed since) is
replayed from its opening only when its stop is still the one it opened
with, and from its last hand edit when its levels were edited (the target
too); one whose stop moved starts its history now, and no bar that began
before it is tested, because which levels were in force then is not known.

THE TIME STOP (2026-10-15). A bar at or past the time-stop ceiling is the
clock exit's, not the stop's: the walk stops there. When no managed tick
saw the ceiling (the row sat unmanaged across it) and the first bar at or
past it is complete, the time stop books from that bar: at its open, at its
time (reason TIME), never at the far mark of the first tick after weeks.

AN UNMANAGED STRETCH (2026-10-15). A row nothing managed for
UNMANAGED_AFTER (no managed tick, no shut-market tick, or a stopped config's
paper row the paper-only pass touches for the first time) whose bars cannot
cover that stretch (stop history unknown, no bars, bars of another
instrument, bars that stop short of now) has no honest exit price: an exit
booked from its mark this tick closes the row but carries
metadata["unmanaged_exit"], and grading leaves its realized_r unset, so the
record the ladder promotes from never reads it.

NO BARS. A row with no bars to test (no feed for the symbol, options whose
bars are the underlying's, a feed that failed) is managed on the mark: its
tick is stamped and its cursor is not moved, so bars that arrive later are
still replayed against the level history.

THE STAMP. metadata["paper_replay"] = {"tick_at": the last managed tick,
"seen_at": the last tick that saw the row (a shut-market tick too),
"bars_through": the cursor (None until a bar was tested), "stop",
"target": the levels tested, "moves": the level history, "ref": the last
accepted bar's close, "basis": "ok" | "off" | None}. It is written under
the row's lock onto the row as it stands in the database (2026-10-15: the
copy loaded when the tick began could erase a thesis ADJUST written since).
A booked exit carries metadata["paper_exit"] = {model: "bar_replay",
reason, tf, bar_ts, open, high, low, close, level, gapped, worst, source,
at, booked_at}, so the ladder and the pages can tell a replayed booking
from a mark booking.

REAL ROWS are never replayed: a real stop rests at the broker, and nothing
here touches an order path.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone as dt_tz
from typing import Optional

from django.utils import timezone

logger = logging.getLogger(__name__)

MODEL_BAR_REPLAY = "bar_replay"
STAMP_KEY = "paper_replay"
EXIT_KEY = "paper_exit"
UNMANAGED_KEY = "unmanaged_exit"
#: How long each bar the replay reads runs, from its timestamp (its open).
SPANS = {"1h": timedelta(hours=1), "4h": timedelta(hours=4)}
#: A ceiling on one replay's reach: about 90 days of 1h bars.
MAX_BARS = 2200
#: How far behind the cursor the level history must still reach: the
#: longest bar the walk reads (a 4h bar still forming at the cursor).
HISTORY_REACH = timedelta(hours=4)
#: The most level moves one stamp keeps (a row with no bars never prunes
#: by its cursor; past this the oldest go, and bars older than what is
#: left are never tested — a missed crossing, never an invented one).
MAX_MOVES = 120
#: The grain the 1h coverage of a stretch is measured in.
SLOT = timedelta(minutes=15)
#: A stretch with no 1h bar this long after it ended is missing, not a
#: poller a few minutes behind (a forming hour's bar not yet written never
#: pulls its 4h bar into the walk).
MISSING_AFTER = timedelta(hours=1)
#: A gapped stop with no next bar yet waits this long past its bar's end
#: for the next bar's open to confirm the gap.
GAP_CONFIRM_WAIT = timedelta(hours=1)
#: How far, beyond the modelled round trip, the row's own entry may sit
#: outside the bars around its opening before those bars are another
#: instrument's (a futures quote against spot bars): a fraction of price.
BASIS_TOL = {"forex": 0.001, "crypto": 0.003, "stock": 0.002, "etf": 0.002,
             "index": 0.002, "commodity": 0.002}
DEFAULT_BASIS_TOL = 0.002
#: Nothing managed the row for this long: its exit, if the bars cannot
#: cover the stretch, is not graded (module docstring).
UNMANAGED_AFTER = timedelta(hours=24)
#: The bars cover a stretch only when the newest one walked ends within
#: this of now (a poller a few hours behind, a 4h-only series).
COVER_SLACK = timedelta(hours=6)
#: How often a shut-market tick refreshes the row's seen_at.
SEEN_EVERY = timedelta(hours=1)


def _f(value) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None  # NaN is not a level


def _parse(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    from django.utils.dateparse import parse_datetime
    try:
        return parse_datetime(str(value))
    except (TypeError, ValueError):
        return None


def _iso(value):
    return value.isoformat() if isinstance(value, datetime) else value


def _direction(trade) -> int:
    side = str(getattr(trade, "side", "") or "").upper()
    return 1 if side == "BUY" else -1 if side == "SELL" else 0


def _meta(trade) -> dict:
    meta = getattr(trade, "metadata", None)
    return meta if isinstance(meta, dict) else {}


def _stamp_of(trade) -> dict:
    stamp = _meta(trade).get(STAMP_KEY)
    return stamp if isinstance(stamp, dict) else {}


def applies(trade) -> bool:
    """A PAPER row with a side, an opening time and an entry; never an
    option (its bars are the underlying's, its stop is on the premium)."""
    return (bool(getattr(trade, "paper", False))
            and str(getattr(trade, "asset_class", "")) != "options"
            and _direction(trade) != 0
            and getattr(trade, "opened_at", None) is not None
            and _f(getattr(trade, "entry_price", None)))


def levels(trade, *, care_on: bool = False) -> tuple:
    """(stop, target) in force: the tighter of the row's stop and, while
    the position care runs, its soft stop; the row's target."""
    d = _direction(trade)
    stop = _f(trade.stop_loss)
    if care_on:
        soft = _f((_meta(trade).get("care") or {}).get("soft_stop"))
        if soft is not None and (stop is None or
                                 (soft > stop if d > 0 else soft < stop)):
            stop = soft
    return stop, _f(trade.take_profit)


def _looser(d, a, b, *, stop: bool):
    """The farther of two levels from the price (a long's lower stop, its
    higher target). None is NO level, the loosest of all: a bar that spans
    a moment with no stop in force is tested against no stop."""
    if a is None or b is None:
        return None
    if stop:
        return min(a, b) if d > 0 else max(a, b)
    return max(a, b) if d > 0 else min(a, b)


def _same(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= max(1e-8, abs(a) * 1e-9)


def _through(d, price, level) -> bool:
    """`price` at or beyond the stop `level` for a position of direction d."""
    if price is None or level is None:
        return False
    return price <= level if d > 0 else price >= level


def _confirms(d, price, gap_open, stop, jump) -> bool:
    """Does `price` (a gapped bar's close, or the next bar's open) confirm
    the gap's open: through the stop too, or within the class's one-print
    jump bar of that open (the market was there, not one bad tick)."""
    if price is None:
        return False
    if _through(d, price, stop):
        return True
    return bool(jump) and gap_open > 0 and abs(price / gap_open - 1.0) <= jump


def _history_known(trade, stop, *, care_on=False) -> bool:
    """An unstamped row may be replayed from its opening only when the stop
    in force now is the one it opened with."""
    init = _f(_meta(trade).get("initial_stop_loss"))
    return init is not None and stop is not None and _same(init, stop)


def _last_edit_at(trade) -> Optional[datetime]:
    """When the levels were last moved by hand (adjust_levels'
    metadata["level_edits"]), or None."""
    edits = _meta(trade).get("level_edits") or []
    times = [_parse(e.get("at")) for e in edits if isinstance(e, dict)]
    times = [t for t in times if t is not None]
    return max(times) if times else None


def _moves_of(stamp_was) -> list:
    """The stamp's level history: [(at or None, stop, target)], oldest
    first. A stamp from before the history (2026-10-08) is one entry in
    force since an unknown time (None: never a reason to skip a bar)."""
    out = []
    for m in stamp_was.get("moves") or []:
        if isinstance(m, (list, tuple)) and len(m) == 3:
            out.append((_parse(m[0]) if m[0] else None, _f(m[1]), _f(m[2])))
    if not out and stamp_was.get("tick_at"):
        out = [(None, _f(stamp_was.get("stop")), _f(stamp_was.get("target")))]
    return out


def _levels_for(d, moves, ts, end) -> tuple:
    """(stop, target, known) for a bar spanning [ts, end): the loosest stop
    and target in force at any moment of it. known is False when the bar
    began before the oldest level on record (which levels held then is not
    known: the bar is not tested)."""
    if not moves:
        return None, None, False
    first = moves[0][0]
    if first is not None and ts < first:
        return None, None, False
    found = []
    for i, (at, s, t) in enumerate(moves):
        nxt = moves[i + 1][0] if i + 1 < len(moves) else None
        if (at is None or at < end) and (nxt is None or nxt > ts):
            found.append((s, t))
    if not found:
        return None, None, False
    stop, target = found[0]
    for s, t in found[1:]:
        stop = _looser(d, stop, s, stop=True)
        target = _looser(d, target, t, stop=False)
    return stop, target, True


def _prune(moves, cursor) -> list:
    """The history a later walk can still need: an entry replaced before
    `cursor` - HISTORY_REACH never touches a bar the walk will read again.
    The last entry always stays; MAX_MOVES at most."""
    if cursor is not None:
        floor = cursor - HISTORY_REACH
        keep = []
        for i, m in enumerate(moves):
            nxt = moves[i + 1][0] if i + 1 < len(moves) else None
            if nxt is not None and nxt <= floor:
                continue
            keep.append(m)
        moves = keep
    return moves[-MAX_MOVES:]


class _Session:
    """Is the row's market in session at a given moment (paper market
    clock's venue; always with the gate off). Memoised by the shut
    stretches the clock names, so a weekend costs one read."""

    def __init__(self, trade):
        from bot_program.engine import paper_trader
        self.gate = bool(paper_trader.MARKET_HOURS_GATE)
        self.trade = trade
        self.key = None
        self.shut = []

    def open_at(self, at) -> bool:
        if not self.gate:
            return True
        for start, until in self.shut:
            if start <= at < until:
                return False
        from bot_program.engine import paper_trader
        if self.key is None:
            self.key = paper_trader._instrument_key(self.trade.symbol,
                                                    self.trade.asset_class)
        try:
            from core.exchange_status import market_clock
            clock = market_clock(self.key[0] or "", self.key[1] or "",
                                 symbol=self.trade.symbol or "", now_utc=at)
        except Exception:  # noqa: BLE001 — an unreadable clock reads open
            return True
        if clock.get("is_open", True):
            return True
        until = clock.get("reopens")
        until = until if isinstance(until, datetime) and until > at \
            else at + SLOT
        self.shut.append((at, until))
        return False


def _slot(t: datetime) -> datetime:
    t = t.astimezone(dt_tz.utc)
    return t.replace(minute=t.minute - t.minute % 15, second=0,
                     microsecond=0)


def _bars(trade, since: datetime, cursor: Optional[datetime], now,
          session: Optional[_Session] = None,
          holes_from: Optional[datetime] = None) -> tuple:
    """(bars, holes). The bars to test, oldest first, each one a dict: the
    1h bars, and a 4h bar wherever the 1h bars leave an in-session stretch
    of it uncovered. holes: the starts of the in-session SLOTs from the
    first 1h bar (and from `holes_from`) that no 1h bar covers."""
    from instruments.models import Instrument
    from market_data.models import PriceData
    inst = (Instrument.objects.filter(symbol=trade.symbol)
            .values_list("pk", flat=True).first())
    if inst is None:
        return [], []
    session = session or _Session(trade)
    raw = {"1h": [], "4h": []}
    for tf in ("1h", "4h"):
        span = SPANS[tf]
        qs = PriceData.objects.filter(instrument_id=inst, timeframe=tf,
                                      timestamp__gte=since,
                                      timestamp__lte=now)
        if cursor is not None:
            qs = qs.filter(timestamp__gt=cursor - span)
        for row in (qs.order_by("timestamp")
                    .values("timestamp", "open", "high", "low", "close",
                            "source")[:MAX_BARS]):
            o, h, low, c = (_f(row["open"]), _f(row["high"]),
                            _f(row["low"]), _f(row["close"]))
            if not o or not h or not low or not c or h < low or low <= 0:
                continue
            # an open or close a feed rounded past its own high or low
            # traded: the range is widened to hold it, never the bar lost
            h, low = max(h, o, c), min(low, o, c)
            ts = row["timestamp"]
            raw[tf].append({"tf": tf, "ts": ts, "end": ts + span, "open": o,
                            "high": h, "low": low, "close": c,
                            "source": row["source"] or ""})
    covered = set()
    for b in raw["1h"]:
        s = _slot(b["ts"])
        while s < b["end"]:
            covered.add(s)
            s += SLOT

    def uncovered(start, end):
        s = _slot(start)
        while s < end:
            if (s >= since and s + SLOT <= now - MISSING_AFTER
                    and s not in covered and session.open_at(s)):
                yield s
            s += SLOT

    out = list(raw["1h"])
    for b in raw["4h"]:
        if next(uncovered(b["ts"], b["end"]), None) is not None:
            out.append(b)
    holes = []
    if raw["1h"]:
        first = raw["1h"][0]["ts"]
        holes = list(uncovered(max(first, holes_from) if holes_from
                               else first, now))
    out.sort(key=lambda b: (b["ts"], b["tf"]))
    return out, holes


def _within(bar, ref, bound) -> bool:
    if not ref or ref <= 0:
        return True
    return all(abs(v / ref - 1.0) <= bound
               for v in (bar["open"], bar["high"], bar["low"], bar["close"]))


def _sane(bars, ref, bound, shift_bars) -> tuple:
    """(accepted, pending): the bars that pass THE BAR SANITY in order, and
    the first bar of a run past the jump that has not yet held for
    `shift_bars` bars (None when there is none)."""
    accepted, run = [], []
    for bar in bars:
        if _within(bar, ref, bound):
            run = []           # a spike the series came back from: dropped
            accepted.append(bar)
            ref = bar["close"]
            continue
        run.append(bar)
        if len(run) >= shift_bars and all(
                _within(b, run[0]["close"], bound) for b in run[1:]):
            accepted.extend(run)   # one level, held: a market that moved
            ref = run[-1]["close"]
            run = []
    return accepted, (run[0] if run else None)


def _basis(trade) -> Optional[str]:
    """"ok" when the bars around the row's opening hold its own entry,
    "off" when they do not (another instrument's price), None when no bar
    near the opening says."""
    from instruments.models import Instrument
    from market_data.models import PriceData
    inst = (Instrument.objects.filter(symbol=trade.symbol)
            .values_list("pk", flat=True).first())
    entry, opened = _f(trade.entry_price), trade.opened_at
    if inst is None or not entry or opened is None:
        return None
    try:
        from bot_program.asset_engine.risk_levels import (
            round_trip_cost_fraction)
        cost = float(round_trip_cost_fraction(trade.config, trade.symbol))
    except Exception:  # noqa: BLE001 — no cost model: the tolerance alone
        cost = 0.0
    tol = cost + BASIS_TOL.get(str(trade.asset_class or "").lower(),
                               DEFAULT_BASIS_TOL)
    for tf, before, after in (("1h", timedelta(hours=2), timedelta(hours=1)),
                              ("4h", timedelta(hours=8), timedelta(hours=4))):
        rows = [(_f(r["high"]), _f(r["low"])) for r in
                PriceData.objects.filter(
                    instrument_id=inst, timeframe=tf,
                    timestamp__gte=opened - before,
                    timestamp__lt=opened + after).values("high", "low")]
        rows = [(h, low) for h, low in rows if h and low and h >= low > 0]
        if rows:
            hi = max(h for h, _ in rows)
            lo = min(low for _, low in rows)
            return "ok" if lo * (1 - tol) <= entry <= hi * (1 + tol) else "off"
    return None


def _booking_time(trade, bar) -> Optional[datetime]:
    """When a crossing in `bar` books: the bar's open; the end of the
    settling window when the bar began in it, or began shut and the market
    opened inside it; None when the paper market clock calls the whole bar
    shut (a re-stamp, not a trade) or the bar ends inside the settling
    window."""
    from bot_program.engine import paper_trader
    if not paper_trader.MARKET_HOURS_GATE:
        return bar["ts"]
    cls, exchange = paper_trader._instrument_key(trade.symbol,
                                                 trade.asset_class)
    words, opened = paper_trader._paper_clock(cls, exchange, trade.symbol,
                                              now=bar["ts"])
    if not words:
        return bar["ts"]
    if opened is None:
        # Shut at the bar's start. A bar that holds the open (the 13:00
        # bar of a 13:30 open, the 4h bar of the Sunday reopen) is read
        # again at its last second: it traded from that open on.
        _, opened = paper_trader._paper_clock(
            cls, exchange, trade.symbol,
            now=bar["end"] - timedelta(seconds=1))
        if opened is None or not (bar["ts"] < opened < bar["end"]):
            return None
    settled = opened + timedelta(seconds=paper_trader.REOPEN_SETTLE_SECONDS)
    return max(settled, bar["ts"]) if settled < bar["end"] else None


def _cross(d, bar, stop, target) -> Optional[dict]:
    """The exit `bar` books for a position of direction `d`, or None. The
    level is always a price the bar traded (the cost goes on top)."""
    o, h, low = bar["open"], bar["high"], bar["low"]
    if d > 0:
        if stop is not None and low <= stop:
            return {"reason": "SL", "level": max(min(stop, o), low),
                    "gapped": o < stop, "worst": low}
        if target is not None and h >= target:
            return {"reason": "TP", "level": target, "gapped": o > target,
                    "worst": low}
        return None
    if stop is not None and h >= stop:
        return {"reason": "SL", "level": min(max(stop, o), h),
                "gapped": o > stop, "worst": h}
    if target is not None and low <= target:
        return {"reason": "TP", "level": target, "gapped": o < target,
                "worst": h}
    return None


def _start(trade, stamp_was, stop, target, now) -> tuple:
    """(history, moves): how much of the row's level history is known, and
    that history with the levels in force now at its end."""
    tick_at = _parse(stamp_was.get("tick_at"))
    if tick_at is None:
        if not _history_known(trade, stop):
            # Which bars traded under which stop is not known: the history
            # starts now, and no bar that began before it is tested.
            return "unknown", [(now, stop, target)]
        edit_at = _last_edit_at(trade)
        since = trade.opened_at
        if edit_at is not None and edit_at > since:
            # moved by hand (the target too): known from the last edit on
            since = min(edit_at, now)
        return "known", [(since, stop, target)]
    moves = _moves_of(stamp_was)
    if not moves:
        moves = [(None, stop, target)]
    _, s_last, t_last = moves[-1]
    if not (_same(s_last, stop) and _same(t_last, target)):
        # moved after the last tick's replay (trailing, the care, a
        # scale-out), or by hand since: in force from that tick, or from
        # the hand edit when one falls after it
        edit_at = _last_edit_at(trade)
        at = edit_at if (edit_at is not None
                         and tick_at < edit_at <= now) else tick_at
        moves.append((at, stop, target))
    return "stamped", moves


def replay(trade, *, now=None, care_on: bool = False,
           ceiling: Optional[datetime] = None) -> Optional[dict]:
    """The bars since the row's last managed tick, against its levels.

    None when the replay does not apply (a real row, an option, no side,
    no entry, no opening time). Otherwise:
        {"hit": the exit to book or None,
         "stop", "target": the levels in force now,
         "bars_through": the cursor after this walk (None until a bar was
                         tested),
         "tested": bars walked, "history": "stamped" | "known" |
                   "unknown" | "basis",
         "moves": the level history to stamp, "ref": the last accepted
         complete bar's close, "basis": "ok" | "off" | None,
         "covered_to": the end of the newest bar walked (None: none)}
    A hit: {reason "SL"|"TP"|"TIME", level, gapped, worst, at, tf, bar_ts,
    open, high, low, close, source}. Reads only; `stamp` writes."""
    if not applies(trade):
        return None
    from backtester.proving.data import LEVEL_SHIFT_BARS, max_jump
    now = now or timezone.now()
    d = _direction(trade)
    stop, target = levels(trade, care_on=care_on)
    stamp_was = _stamp_of(trade)
    tick_at = _parse(stamp_was.get("tick_at"))
    cursor = _parse(stamp_was.get("bars_through"))
    history, moves = _start(trade, stamp_was, stop, target, now)
    ref0 = _f(stamp_was.get("ref")) or _f(trade.entry_price)
    out = {"hit": None, "stop": stop, "target": target,
           "bars_through": cursor.isoformat() if cursor else None,
           "tested": 0, "history": history, "moves": moves,
           "ref": ref0, "basis": stamp_was.get("basis"), "covered_to": None}

    if out["basis"] not in ("ok", "off"):
        out["basis"] = _basis(trade)
    if out["basis"] == "off":
        # the bars are another instrument's price: the mark, as before
        out["history"] = "basis"
        return out

    from bot_program.engine import paper_trader
    grace = timedelta(seconds=paper_trader.REOPEN_PRICE_GRACE_SECONDS)
    session = _Session(trade)
    raw, holes = _bars(trade, trade.opened_at, cursor, now, session,
                       holes_from=now - grace)
    bars, pending = _sane(raw, ref0, max_jump(trade.asset_class),
                          LEVEL_SHIFT_BARS)
    from bot_program.mark_sanity import bar_for
    jump = bar_for(trade.asset_class)
    # THE CLOCK EXIT FROM THE BARS: only when no managed tick saw the
    # ceiling, and never on a history that is not known
    time_due = (ceiling is not None and ceiling <= now
                and (tick_at is None or tick_at < ceiling)
                and history != "unknown")
    hold = pending["ts"] if pending is not None else None
    newest_complete = cursor
    for i, bar in enumerate(bars):
        if ceiling is not None and bar["ts"] >= ceiling:
            if not time_due or bar["end"] > now:
                break
            at = _booking_time(trade, bar)
            if at is None:
                continue          # a shut bar: the next one books it
            out["hit"] = {"reason": "TIME", "level": bar["open"],
                          "gapped": False, "worst": None,
                          "at": min(at, now), "tf": bar["tf"],
                          "bar_ts": bar["ts"], "open": bar["open"],
                          "high": bar["high"], "low": bar["low"],
                          "close": bar["close"], "source": bar["source"]}
            return out
        out["tested"] += 1
        complete = bar["end"] <= now
        if complete and (newest_complete is None
                         or bar["end"] > newest_complete):
            newest_complete = bar["end"]
        edge = min(bar["end"], now)
        if out["covered_to"] is None or edge > out["covered_to"]:
            out["covered_to"] = edge
        s, t, known = _levels_for(d, moves, bar["ts"], bar["end"])
        if not known:
            continue
        hit = _cross(d, bar, s, t)
        if hit is None:
            continue
        if hit["reason"] == "SL" and hit["gapped"]:
            nxt = bars[i + 1] if i + 1 < len(bars) else None
            if not (_confirms(d, bar["close"], bar["open"], s, jump)
                    or (nxt is not None
                        and _confirms(d, nxt["open"], bar["open"], s,
                                      jump))):
                if nxt is None and now < bar["end"] + GAP_CONFIRM_WAIT:
                    # the next bar's open decides: this bar waits for it
                    hold = bar["ts"] if hold is None else min(hold, bar["ts"])
                    break
                # one print through the stop, not a market: at the stop
                hit.update(level=s, gapped=False, unconfirmed_gap=True)
        at = _booking_time(trade, bar)
        if at is None:
            continue
        hit.update(at=min(at, now), tf=bar["tf"], bar_ts=bar["ts"],
                   open=bar["open"], high=bar["high"], low=bar["low"],
                   close=bar["close"], source=bar["source"])
        out["hit"] = hit
        return out

    # A hole in the 1h bars younger than the reopen grace holds the cursor
    # at its start: an hourly bar written late is still read.
    young = [h for h in holes if h > now - grace
             and (newest_complete is None or h < newest_complete)]
    if young:
        hold = min(young) if hold is None else min(hold, min(young))
    if hold is not None and newest_complete is not None \
            and newest_complete > hold:
        newest_complete = max(hold, cursor) if cursor else hold
    if newest_complete is not None:
        done = [b for b in bars if b["end"] <= newest_complete
                and (cursor is None or b["end"] > cursor)]
        if done:
            out["ref"] = max(done, key=lambda b: b["end"])["close"]
    out["bars_through"] = (newest_complete.isoformat()
                           if newest_complete else None)
    return out


def covered(result: Optional[dict], *, now) -> bool:
    """Did this tick's replay walk the row's bars up to (about) now, on a
    level history it knows? False: an exit booked from the mark this tick
    rests on a price the bars could not check."""
    if not result or result.get("history") not in ("stamped", "known"):
        return False
    to = _parse(result.get("covered_to"))
    return to is not None and to >= now - COVER_SLACK


def uncovered_why(result: Optional[dict]) -> str:
    """Why the bars could not cover the stretch, in words."""
    if not result:
        return "the bar replay did not run"
    if result.get("history") == "basis":
        return "its bars are another instrument's price"
    if result.get("history") == "unknown":
        return "its stop moved before any tick recorded its history"
    if not result.get("tested"):
        return "no bars"
    return "its bars stop short of now"


def unmanaged_since(trade, *, now, first_touch: Optional[datetime] = None
                    ) -> Optional[datetime]:
    """Since when nothing managed this row, when that is longer than
    UNMANAGED_AFTER; else None. Read BEFORE this tick's stamp.

    The last managed or shut-market tick (tick_at, seen_at) says it for a
    stamped row. An unstamped row was managed by the tick before this
    module (no stamp says otherwise) unless `first_touch` is given: the
    paper-only pass of a config a stop switched off, which never ran it
    before; the stretch then began at `first_touch` (when the config was
    stopped, if recorded) or the row's opening, the later of the two."""
    st = _stamp_of(trade)
    times = [t for t in (_parse(st.get("tick_at")), _parse(st.get("seen_at")))
             if t is not None]
    if times:
        since = max(times)
    elif first_touch is not None:
        opened = getattr(trade, "opened_at", None)
        since = max(t for t in (first_touch, opened) if t is not None) \
            if (first_touch or opened) else None
    else:
        return None
    if since is None or now - since < UNMANAGED_AFTER:
        return None
    return since


def _write_stamp(trade, update: dict) -> None:
    """Merge `update` into the row's stamp under its lock, onto the row as
    it stands in the database, and hand the fresh metadata to `trade`."""
    from django.db import transaction
    from bot_program.models import AssetBotTrade
    with transaction.atomic():
        row = (AssetBotTrade.objects.select_for_update()
               .filter(pk=trade.pk).first())
        if row is None:
            return
        meta = dict(row.metadata or {}) if isinstance(row.metadata, dict) \
            else {}
        st = meta.get(STAMP_KEY)
        st = dict(st) if isinstance(st, dict) else {}
        st.update(update)
        meta[STAMP_KEY] = st
        row.metadata = meta
        row.save(update_fields=["metadata"])
    trade.metadata = meta


def stamp_value(result: dict, *, now) -> dict:
    """The managed-tick stamp a replay `result` leaves, as a value (pure):
    what `stamp` writes on the row, and what the Orcs' care ghost keeps on
    its own state for a replay of its own levels (bot_program/orcs/ghost)."""
    cursor = _parse(result.get("bars_through"))
    moves = _prune(list(result.get("moves") or []), cursor)
    return {
        "tick_at": now.isoformat(),
        "seen_at": now.isoformat(),
        "bars_through": result.get("bars_through"),
        "stop": result.get("stop"),
        "target": result.get("target"),
        "moves": [[_iso(at), s, t] for at, s, t in moves],
        "ref": result.get("ref"),
        "basis": result.get("basis"),
    }


def stamp(trade, result: dict, *, now) -> None:
    """Write the row's managed-tick stamp from a replay `result` (metadata
    only, under the row's lock)."""
    _write_stamp(trade, stamp_value(result, now=now))


def seen(trade, *, now) -> bool:
    """A shut-market tick saw the row (base.manage_positions' wait): its
    seen_at is refreshed at most every SEEN_EVERY, so a weekend is never an
    unmanaged stretch. Only a row the replay already stamped: a first touch
    must not hide the stretch before it. Never raises."""
    try:
        st = _stamp_of(trade)
        if not st.get("tick_at"):
            return False
        was = _parse(st.get("seen_at")) or _parse(st.get("tick_at"))
        if was is not None and now - was < SEEN_EVERY:
            return False
        _write_stamp(trade, {"seen_at": now.isoformat()})
        return True
    except Exception as e:  # noqa: BLE001 — a lost seen is a later flag
        logger.warning("[paper_exits] seen stamp failed for #%s: %s",
                       getattr(trade, "pk", "?"), e)
        return False


def exit_record(hit: dict, *, now) -> dict:
    """The JSON the booked row carries as metadata["paper_exit"]."""
    out = {"model": MODEL_BAR_REPLAY, "reason": hit["reason"],
           "tf": hit["tf"], "bar_ts": _iso(hit["bar_ts"]),
           "open": hit["open"], "high": hit["high"], "low": hit["low"],
           "close": hit["close"], "level": hit["level"],
           "gapped": bool(hit["gapped"]), "worst": hit["worst"],
           "source": hit["source"], "at": _iso(hit["at"]),
           "booked_at": now.isoformat()}
    if hit.get("unconfirmed_gap"):
        out["unconfirmed_gap"] = True
    return out
