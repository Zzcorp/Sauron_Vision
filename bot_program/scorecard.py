"""THE SCORECARD (2026-10-02): is the book paid for its losses?

The operator: "our Sauron is unfortunately not winning over the long run...
too many losing trades on my part, maybe?" The week's closed rows said
otherwise. 15 of 24 won — 62%, a good rate. What lost was the PAYOFF and
two stops: the average winner was +0.42R, 12 of the 15 winners were closed
by hand at +0.28R on average (several in one minute), and two paper stops
did not hold (-8.12R, -1.84R). With those two the book needed winners of
+1.09R; without them it was level — +0.42R paid against the +0.43R a 68%
win rate needs. Never paid.

No page said so. Aragorn grades a rule by its expectancy, which is the
right verdict and the wrong diagnosis: a negative number does not say
whether the fault is the win rate, the size of the wins or the size of
the losses. This module splits it:

  win rate, average win, average loss   the three numbers expectancy is
  payoff, break-even win rate           the payoff a book needs at its win
                                        rate, against the one it gets
  closed by hand                        how many winners were cut short,
                                        at what R, and what they had seen
                                        (MFE, from position care)
  gave back                             losers that had been +1R first
  overshoot                             a loss past -OVERSHOOT_R: a stop
                                        that did not hold

Read-only and pure where it can be: `summarize` takes plain rows, so the
scorecard command, the close dialog and a test all ask the same question
of the same arithmetic. Unmeasured exits (realized_r NULL) are counted
and left out — never read as zero.

WHICH EXIT CLOSED IT (2026-10-07, PR51a; `scorecard --by exit`). Before any
exit is changed, the operator reads which exit closed each live trade:
care's own lock (break-even, trail, the weekend or event lock...), the
venue's stop or target, the time stop, a hand. `exit_of` reads what the row
recorded and never re-derives it from prices. Two lines go with it: how
many exit prices are inferred (a mark or the level the venue held, not a
broker fill), and how many live stock and ETF closes the venue made outside
the regular session — measured only from the window the reconcile writes
(venue_exit.CLOSED_BETWEEN_KEY), "unmeasured" without one.
"""
from __future__ import annotations

from datetime import datetime, time as dtime, timedelta

#: A closed loss worse than this is a stop that did not hold: a gap, a
#: stop nobody watched, a reconciliation that booked late.
OVERSHOOT_R = 1.2
#: The R a winner is said to have "reached" before it was cut or given back.
REACHED_R = 1.0
#: Fewer closed trades than this, and the scorecard says the sample is thin.
THIN_SAMPLE = 20
#: The tag manual_close.CLOSE_REASON leaves on a row closed by hand.
HAND_CLOSE_TAG = "closed:MANUAL"
#: the outcome strings bot_grading writes (bot_grading.py:167-195); never a
#: new spelling (tests/test_scorecard_by_exit.py grades real rows to pin them)
TIME_STOP, HIT_TARGET, STOPPED_OUT = "time_stop", "hit_target", "stopped_out"
#: The tag the reconcile leaves on a row the venue closed and it booked
#: (reconcile_asset._close_as_orphan).
RECONCILED_TAG = "reconciled-orphan"
#: The window the reconcile writes when eToro's order read said "closed"
#: (2026-10-07, = venue_exit.CLOSED_BETWEEN_KEY): [lo_iso, hi_iso], the last
#: venue reading that showed the position open and the first list read that
#: did not. Not the venue's close time — eToro publishes none. The close
#: lies in [lo - LIST_LAG_S, hi], not in [lo, hi] (2026-10-07, review): the
#: list keeps a closed position listed for up to ~60 s, so the reading that
#: set lo may have come after the close.
CLOSE_WINDOW_KEY = "venue_closed_between"
#: How long eToro's /portfolio keeps listing a position it has closed
#: (= EtoroTrader.PORTFOLIO_LAG_S, measured 2026-09-23; copied here and
#: pinned by a test). The window's lower bound is widened by it before the
#: session side is read.
LIST_LAG_S = 60
#: The classes whose live closes eToro fills in its extended session
#: (= morgul.VENUE_SESSION_CLASSES; morgul imports this module, so the
#: tuple is copied here and pinned by a test).
VENUE_SESSION_CLASSES = ("stock", "etf")
#: The regular US session, New York time. Exchange holidays are not
#: modelled (market_data/feeds.py says the same of its own clock): a close
#: at 11:00 New York on a holiday reads as inside.
REGULAR_OPEN_NY, REGULAR_CLOSE_NY = dtime(9, 30), dtime(16, 0)


def exit_of(trade) -> str:
    """Which exit closed the row, from what the row recorded (never re-derived from
    prices), first match wins:
      "by hand"            HAND_CLOSE_TAG in trade.reason
      "care: <lock>"       metadata["care_exit"] (care's own close: trail, breakeven,
                           weekend lock, event lock, structure, no progress, weekend cut,
                           event cut, stressed market, crisis — "(beyond the crowd)" kept)
      "time stop"          outcome == "time_stop"
      "target"             outcome == "hit_target"
      "stop at <lock>"     outcome == "stopped_out" and the venue's stop was last moved by
                           care's mirror, to the row's stop: that lock filled at the
                           venue; <lock> from the move (_care_lock_at_the_venue)
      "stop"               outcome == "stopped_out" and the venue's stop was last set by
                           anything else: the stop sent with the order, the engine's
                           break-even or trail knobs, an operator's level
      "other: <outcome>"   anything else ("other: ungraded" when no outcome)"""
    meta = trade.metadata if isinstance(trade.metadata, dict) else {}
    if HAND_CLOSE_TAG in (trade.reason or ""):
        return "by hand"
    lock = str(meta.get("care_exit") or "").strip()
    if lock:
        return f"care: {lock}"
    outcome = trade.outcome or ""
    if outcome == TIME_STOP:
        return "time stop"
    if outcome == HIT_TARGET:
        return "target"
    if outcome == STOPPED_OUT:
        lock = _care_lock_at_the_venue(trade, meta)
        return f"stop at {lock}" if lock else "stop"
    return f"other: {outcome or 'ungraded'}"


def _care_lock_at_the_venue(trade, meta) -> str:
    """The care lock the venue's stop rested at, or "" (2026-10-07, review).

    Read from the last stop move the VENUE accepted, never from care's
    soft_why: soft_why names care's newest lock every tick, while the venue's
    stop moves only when a mirror PATCH is accepted. A refused mirror (an
    eToro 429) leaves the break-even resting under a newer "trail"; the held
    branch of position_care._mirror_to_venue records a stop the engine's
    knobs or the operator set. base._move_broker_stop records each accepted
    move as {"to": the level the venue took, "why": why + ":broker"}, and the
    mirror's why is "care <soft_why>". Care's lock only when that last move
    is care's AND its level is still the row's stop (a later hand edit of the
    levels moves the stop and records no stop move)."""
    moves = meta.get("stop_moves")
    last = (moves[-1] if isinstance(moves, list) and moves
            and isinstance(moves[-1], dict) else {})
    why = str(last.get("why") or "").strip()
    if not why.startswith("care "):
        return ""
    to, stop = _number(last.get("to")), _number(trade.stop_loss)
    if to is None or stop is None or round(to, 8) != round(stop, 8):
        return ""
    return why[len("care "):].removesuffix(":broker").strip() or "lock"


def _number(x):
    """A positive finite float, else None (a bool is not a level)."""
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v > 0 and v != float("inf") else None


def close_window(meta) -> tuple | None:
    """(lo, hi) aware datetimes from the reconcile's CLOSE_WINDOW_KEY, or None
    when it is missing, garbled, naive (not one of ours) or reversed."""
    from django.utils import timezone
    from django.utils.dateparse import parse_datetime
    pair = meta.get(CLOSE_WINDOW_KEY) if isinstance(meta, dict) else None
    if not isinstance(pair, (list, tuple)) or len(pair) != 2:
        return None
    try:
        lo, hi = (parse_datetime(str(x)) for x in pair)
    except (TypeError, ValueError):
        return None
    if lo is None or hi is None or timezone.is_naive(lo) \
            or timezone.is_naive(hi) or hi < lo:
        return None
    return lo, hi


def _closed_at_the_venue(trade, meta) -> bool:
    """The venue made the close and the platform booked it after (a stop or
    a target struck, a hand in the broker's own app): the reconcile's tag,
    or a booking at the level the venue held, an hour of unanswered asks,
    or the window — the same facts notifications.fill_close_message reads
    as a RECORDED close (2026-10-07)."""
    return bool(RECONCILED_TAG in (trade.reason or "")
                or meta.get("exit_priced_at")
                or meta.get("venue_unproven_close")
                or meta.get(CLOSE_WINDOW_KEY))


def _inferred_exit(meta) -> bool:
    """The exit price is an estimate, not a broker fill (2026-10-07, review):
    flagged exit_price_inferred by whoever booked it (the reconcile, the
    drain's venue-level or hour-late booking), or sourced at a mark or at the
    level the venue held. A mark is every close the platform sends to eToro
    (its close answer carries no price: resolve_exit_fill books the mark)
    and every drain booking without a fill. Paper's modelled fill is not an
    estimate of a broker fill: not counted."""
    from bot_program.pending_closes import (EXIT_FILL_SOURCE_KEY,
                                            EXIT_SOURCE_MARK,
                                            EXIT_SOURCE_VENUE_STOP,
                                            EXIT_SOURCE_VENUE_TARGET)
    return bool(meta.get("exit_price_inferred")) or meta.get(
        EXIT_FILL_SOURCE_KEY) in (EXIT_SOURCE_MARK, EXIT_SOURCE_VENUE_STOP,
                                  EXIT_SOURCE_VENUE_TARGET)


def row_of(trade) -> dict:
    """The fields the scorecard reads, from one AssetBotTrade."""
    from bot_program.manual_trade import MANUAL_RULE
    meta = trade.metadata or {}
    care = meta.get("care") or {}
    mfe = care.get("mfe_r")
    try:
        mfe = float(mfe) if mfe is not None else None
    except (TypeError, ValueError):
        mfe = None
    rule = trade.rule_name or ""
    policy = meta.get("exit_policy")
    return {
        "id": trade.pk,
        "symbol": trade.symbol,
        "asset_class": trade.asset_class,
        "rule": rule,
        "lane": "manual" if rule == MANUAL_RULE else "bots",
        "venue": "paper" if trade.paper else "live",
        "r": trade.realized_r,
        "outcome": trade.outcome or "",
        "by_hand": HAND_CLOSE_TAG in (trade.reason or ""),
        # Whether a Sauron signal stood behind the entry: a bot's always
        # does; a hand-taken one carries its signal_id when it had one.
        "backed": rule != MANUAL_RULE or bool(meta.get("signal_id")),
        "mfe": mfe,
        "closed_at": trade.closed_at,
        # WHICH EXIT (2026-10-07, PR51a). The exit the row was stamped with
        # at entry: no stamp exists before PR51b, so every row reads care.
        "exit": exit_of(trade),
        "policy": ((policy.get("key") if isinstance(policy, dict) else None)
                   or "care"),
        # care's shadow arrives with PR51b; until then the row is its own
        "shadow_r": trade.realized_r,
        "inferred": _inferred_exit(meta),
        "at_venue": _closed_at_the_venue(trade, meta),
        # (lo, hi) as the reconcile wrote it: the close lies in
        # [lo - LIST_LAG_S, hi]; None when not recorded
        "venue_close_at": close_window(meta),
    }


def rows(*, days=30, user=None, venue=None, now=None) -> list:
    """Closed rows of the last `days` days, as scorecard rows."""
    from django.utils import timezone

    from bot_program.asset_models import AssetBotTrade
    now = now or timezone.now()
    qs = AssetBotTrade.objects.filter(
        status="CLOSED", closed_at__gte=now - timedelta(days=days))
    if user is not None:
        qs = qs.filter(config__user=user)
    if venue == "live":
        qs = qs.filter(paper=False)
    elif venue == "paper":
        qs = qs.filter(paper=True)
    return [row_of(t) for t in qs.order_by("-closed_at")]


def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def summarize(rows_) -> dict:
    """Every number the scorecard prints, for one group of rows.

    `expectancy` is the mean R per measured trade. `payoff` is the average
    win over the average loss; `breakeven_win_rate` the win rate that
    payoff needs to stand still, and `needed_avg_win` the average win the
    ACTUAL win rate needs — the two ways of saying the same gap."""
    measured = [r for r in rows_ if r.get("r") is not None]
    rs = [float(r["r"]) for r in measured]
    wins = [x for x in rs if x > 0]
    losses = [x for x in rs if x < 0]
    n = len(rs)
    win_rate = len(wins) / n if n else None
    avg_win = _mean(wins)
    avg_loss = _mean(losses)
    payoff = (avg_win / abs(avg_loss)
              if avg_win is not None and avg_loss else None)
    breakeven = 1.0 / (1.0 + payoff) if payoff else None
    needed = (abs(avg_loss) * (1 - win_rate) / win_rate
              if avg_loss is not None and win_rate else None)

    hand = [r for r in measured if r["by_hand"]]
    hand_wins = [r for r in hand if float(r["r"]) > 0]
    hand_win_mfe = [r["mfe"] for r in hand_wins if r["mfe"] is not None]
    gave_back = [r for r in measured
                 if float(r["r"]) < 0 and r["mfe"] is not None
                 and r["mfe"] >= REACHED_R]
    overshoot = [r for r in measured if float(r["r"]) < -OVERSHOOT_R]
    return {
        "n": n,
        "unmeasured": len(rows_) - n,
        "thin": n < THIN_SAMPLE,
        "wins": len(wins), "losses": len(losses),
        "win_rate": win_rate,
        "avg_win": avg_win, "avg_loss": avg_loss,
        "expectancy": _mean(rs),
        "sum_r": sum(rs) if rs else None,
        "payoff": payoff,
        "breakeven_win_rate": breakeven,
        "needed_avg_win": needed,
        "by_hand": len(hand),
        "by_hand_wins": len(hand_wins),
        "by_hand_win_avg": _mean([float(r["r"]) for r in hand_wins]),
        "by_hand_win_mfe": _mean(hand_win_mfe),
        "targets_hit": sum(1 for r in measured
                           if r["outcome"] == "hit_target"),
        "gave_back": len(gave_back),
        "overshoot": [(r["id"], r["symbol"], round(float(r["r"]), 2))
                      for r in overshoot],
    }


def diagnosis(s) -> str:
    """One sentence: which of the three numbers is losing the money."""
    if not s["n"]:
        return "No measured closed trade in this window."
    if s["expectancy"] is not None and s["expectancy"] > 0:
        return (f"Paid: {s['expectancy']:+.2f}R a trade.")
    if s["avg_win"] is None:
        return "No winner in this window: the entries, not the exits."
    if s["avg_loss"] is None:
        return "No loser in this window."
    if (s["needed_avg_win"] is not None
            and s["avg_win"] < s["needed_avg_win"]
            and (s["win_rate"] or 0) >= 0.5):
        cut = ""
        if s["by_hand_wins"]:
            cut = (f" {s['by_hand_wins']} of {s['wins']} winners were closed "
                   f"by hand at {s['by_hand_win_avg']:+.2f}R on average.")
        return (f"The win rate is not the problem ({s['win_rate'] * 100:.0f}%): "
                f"winners average {s['avg_win']:+.2f}R where this win rate "
                f"needs {s['needed_avg_win']:+.2f}R.{cut}")
    if s["overshoot"]:
        return (f"{len(s['overshoot'])} loss(es) went past -{OVERSHOOT_R}R: "
                f"stops that did not hold.")
    return (f"The win rate is: {s['win_rate'] * 100:.0f}% against the "
            f"{s['breakeven_win_rate'] * 100:.0f}% this payoff needs.")


def group(rows_, key) -> dict:
    """{key value: rows}, in first-seen order."""
    out = {}
    for r in rows_:
        out.setdefault(key(r), []).append(r)
    return out


def inferred_line(rows_) -> str:
    """How many of these exit prices are inferred (2026-10-07, PR51a): their
    R are estimates. An exit is inferred when it was booked at a mark
    (exit_fill_source "mark": every close the platform sends to eToro, which
    publishes no closing fill, and every drain booking without one) or at
    the level the venue held (exit_price_inferred, venue_stop /
    venue_target) — _inferred_exit. Not counted: a fill a venue reported
    (exit_fill_source "broker") and paper's modelled fill."""
    k = sum(1 for r in rows_ if r.get("inferred"))
    return (f"inferred exit price: {k} of {len(rows_)} (these R are "
            f"estimates: no broker fill was read)")


def session_side(lo, hi) -> str:
    """Where the window [lo, hi] lies against the regular New York session
    (weekdays REGULAR_OPEN_NY-REGULAR_CLOSE_NY, both ends inside):
    "outside" (it touches no session), "inside" (wholly within one) or
    "spans" (it crosses a session edge: the close may be on either side)."""
    from zoneinfo import ZoneInfo
    ny = ZoneInfo("America/New_York")
    a, b = lo.astimezone(ny), hi.astimezone(ny)
    days = (b.date() - a.date()).days
    if days > 7:
        return "spans"          # a week always holds a session
    for i in range(days + 1):
        d = a.date() + timedelta(days=i)
        if d.weekday() >= 5:
            continue
        s = datetime.combine(d, REGULAR_OPEN_NY, tzinfo=ny)
        e = datetime.combine(d, REGULAR_CLOSE_NY, tzinfo=ny)
        if a <= e and b >= s:
            return "inside" if s <= a and b <= e else "spans"
    return "outside"


def outside_hours_line(rows_) -> str:
    """Of the live stock and ETF rows the venue closed (2026-10-07, PR51a):
    how many closed outside 09:30-16:00 New York — whether eToro triggers a
    resting stop there, and at what fill, is unmeasured. Read only from the
    window the reconcile writes; without one, said unmeasured. The window's
    lower bound is moved back by LIST_LAG_S first (2026-10-07, review): a
    stop filled at 15:59:30 and still listed at 16:00:20 reads "spans", not
    "outside"."""
    venue = [r for r in rows_ if r.get("venue") == "live"
             and r.get("asset_class") in VENUE_SESSION_CLASSES
             and r.get("at_venue")]
    if not venue:
        return ("outside 09:30-16:00 New York: 0 of 0 (no live stock or ETF "
                "row closed at the venue)")
    timed = [r["venue_close_at"] for r in venue if r.get("venue_close_at")]
    if not timed:
        return ("outside regular hours: unmeasured — the venue's close time "
                "is not recorded")
    sides = [session_side(lo - timedelta(seconds=LIST_LAG_S), hi)
             for lo, hi in timed]
    line = (f"outside 09:30-16:00 New York: {sides.count('outside')} of "
            f"{len(timed)}")
    notes = []
    if sides.count("spans"):
        notes.append(f"{sides.count('spans')} window(s) span the session "
                     f"edge: either side")
    if len(venue) - len(timed):
        notes.append(f"{len(venue) - len(timed)} more unmeasured — the "
                     f"venue's close time is not recorded")
    return line + (f" ({'; '.join(notes)})" if notes else "")
