"""THE ONE PRICING FUNCTION (spec §6.1): the only prices any grade uses,
for the real legs and every simulated arm alike. Pure: no database, no
clock, no model.

Two prices, each for one job (§2.1):
  p   the tick price (the ticker's lastPrice, base._mark_price), on which
      everything that TRIGGERS is measured;
  m   the closing-side venue mark: the bid for a long, the ask for a
      short (venue_mark.closing_side); with no bid/ask in hand,
      p - d x half_spread, half_spread from the cost model paper_fill_price
      charges (risk_levels.paper_fill_price: half the round trip a side).

An exit is priced:
  market_exit_px(tick)        m less the one-way modelled cost;
  stop_exit_px(stop, tick)    the stop less the one-way cost, or, when the
                              tick gapped past the stop by more than the
                              spread, market_exit_px(tick);
  target_exit_px(target)      the target less the one-way cost, never
                              better (base.py's paper exit charges the cost
                              on a target too).
A booked price never enters a grade: an eToro market close books the tick's
lastPrice (pending_closes.resolve_exit_fill), so an Orc graded at its
booked price would exit for free while the ghost paid the cost. `cf` is the
round trip as a fraction of the price, frozen per idea at its seed.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Tick:
    """One mark: when, the tick price, and the venue's bid and ask when
    the tick carried them."""
    at: object
    p: float
    bid: Optional[float] = None
    ask: Optional[float] = None


def d(side) -> int:
    """+1 for a long, -1 for a short."""
    return 1 if str(side or "").upper() == "BUY" else -1


def _pos(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v > 0 and v == v and v != float("inf") else None


def half_spread(p, cf) -> float:
    """Half the modelled round trip at price p (paper_fill_price's model)."""
    return float(p) * float(cf or 0.0) / 2.0


def one_way(px, cf) -> float:
    """The one-way modelled cost at price px."""
    return float(px) * float(cf or 0.0) / 2.0


def closing_mark(tick, side, cf) -> float:
    """m: the bid for a long, the ask for a short, else p less the modelled
    half spread on the closing side."""
    sign = d(side)
    if sign > 0 and _pos(tick.bid) is not None:
        return float(tick.bid)
    if sign < 0 and _pos(tick.ask) is not None:
        return float(tick.ask)
    return float(tick.p) - sign * half_spread(tick.p, cf)


def spread_of(tick, cf) -> float:
    """The tick's spread: ask - bid when both are known, else p x cf."""
    bid, ask = _pos(tick.bid), _pos(tick.ask)
    if bid is not None and ask is not None and ask >= bid:
        return ask - bid
    return float(tick.p) * float(cf or 0.0)


def market_exit_px(tick, side, cf) -> float:
    m = closing_mark(tick, side, cf)
    return m - d(side) * one_way(m, cf)


def stop_exit_px(stop, tick, side, cf) -> float:
    """At the stop less the one-way cost; at market when the tick sits past
    the stop by more than the spread (a gap through it)."""
    stop = float(stop)
    if tick is not None:
        m = closing_mark(tick, side, cf)
        if d(side) * (stop - m) > spread_of(tick, cf):
            return market_exit_px(tick, side, cf)
    return stop - d(side) * one_way(stop, cf)


def target_exit_px(target, side, cf) -> float:
    """At the target less the one-way cost: never better than the target."""
    target = float(target)
    return target - d(side) * one_way(target, cf)


def level_exit_px(level, side, cf) -> float:
    """A price a bar traded (a resting stop at its level, a gap at the
    bar's open, a bar's close) less the one-way cost: the paper replay's
    booking (base._close_trade charges the half cost on top of it)."""
    level = float(level)
    return level - d(side) * one_way(level, cf)


def r_of(px, entry, risk_per_unit, side):
    """d x (px - entry) / risk per unit, or None unmeasured."""
    entry, rpu, px = _pos(entry), _pos(risk_per_unit), _pos(px)
    if entry is None or rpu is None or px is None:
        return None
    return d(side) * (px - entry) / rpu
