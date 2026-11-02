"""THE 4H CLEAN-UP ALSO CLEARS AN OLD GRID BESIDE ANOTHER OLD GRID
(2026-11-01).

prune_offgrid_4h listed a public off-grid 4h row only when an ON-grid row
of the same instrument overlapped it. That clears London (its winter grid
is the UTC grid), New York (its summer grid is) and Tokyo (one grid, where
the new grid's window reaches). It left the CET-zone indices. Yahoo's old
4h grid for DAX40, CAC40, IBEX35 or STOXX50 was anchored at CET's
midnight (23:00 UTC: bars at 03, 07, 11... UTC) or at CEST's (22:00 UTC:
02, 06, 10... UTC), as the ~200-day window opened in winter or in summer,
and both are off the UTC grid. Where both were stored before the new
grid's 200-bar window, two near-identical 4h candles an hour apart stayed,
and the command still answered "No off-grid 4h duplicates of the public
feed.". The bots read 300 to 500 4h bars, which reach those stretches.

Now, among an instrument's public off-grid 4h rows, a row that overlaps a
public off-grid row on another grid is listed too. Each overlapping
stretch prefers one grid: the grid of the bars just before and after the
stretch (continuity), or else the later anchor (the grid whose bars open
an hour after the other's). A venue's row is never listed, on any grid;
off-grid history with nothing overlapping it stays; the London series is
cleared as before, with the same words.

No hour loses its bar (2026-11-01, on review of the first cut, which
deleted a row whenever its twin of the same 4h period stayed):
- where a grid STARTS inside a session (its first pass wrote 200 bars from
  wherever the 200th fell), the hour before its first bar was in the other
  grid's twin only, and was lost;
- where a grid STOPS inside a session, its newest bar was written while
  that period traded on: kept, it lost the hours its twin held;
- a row with no twin stayed even where its only hour sat inside a kept bar
  (Sydney's 05:00 UTC bar beside 02:00, Chicago's 10:00 beside 13:00),
  and the command still said there was nothing left.
So a row goes only when every hour of its span is in a whole bar that
stays or in a 4h period another grid shows empty (at a session's edge,
beside no bar of the UTC grid), and each session keeps one grid whole:
the grid changes between two sessions, never inside one. Grids that all
end where the UTC grid begins were cut there by the first rule (on this
run or an earlier one), not stopped. The empty line is said only when
nothing overlapping is left.

No test reaches a network or a broker: the rows are written here, and the
old feed's grids are replayed from its own rule (resample origin
"start_day" in the exchange's zone, the last 200 bars of a 202-day
window per pass).

Run with:  python manage.py test tests.test_prune_offgrid_pairs
"""
import bisect
from datetime import date, datetime, timedelta, timezone as dt_tz
from io import StringIO
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

UTC = dt_tz.utc
H = timedelta(hours=1)
FOUR_H = 4 * 3600

#: Monday 2026-03-02, 00:00 UTC. Ten weekdays from it: Mar 2-6, Mar 9-13.
MONDAY = datetime(2026, 3, 2, tzinfo=UTC)

#: One session's bars on each grid, in UTC hours.
CET = (7, 11, 15)        # anchored at CET's midnight, 23:00 UTC
CEST = (6, 10, 14)       # anchored at CEST's midnight, 22:00 UTC
UTC_GRID = (4, 8, 12)    # the feed's grid since 2026-10-31
GMT = (8, 12, 16)        # London's winter grid: the UTC grid
BST = (7, 11, 15)        # London's summer grid, anchored at 23:00 UTC

#: Xetra's hourly bars in winter, 09:00 to 17:00 Berlin: 08:00 to 16:00
#: UTC. Both old grids hold them, three bars a session each.
XETRA_WINTER = tuple(range(8, 17))

#: The grids by name, as the command prints them.
G1 = "01:00, 05:00, 09:00... UTC"
G2 = "02:00, 06:00, 10:00... UTC"
G3 = "03:00, 07:00, 11:00... UTC"

#: The empty answer, word for word: the operator's sheet waits for it.
EMPTY = "No off-grid 4h duplicates of the public feed."

#: The second rule, as the command prints it under the rows it lists.
RULE_WORDS = ("Where two old grids overlap, each stretch keeps one grid: the "
              "grid of the bars just before and after it (continuity), else "
              "the later anchor (the grid whose bars open an hour after the "
              "other's). A session (a run of bars with no hour between them) "
              "keeps one grid whole, so the grid changes between sessions, "
              "never inside one: a session the kept grid does not hold every "
              "hour of (such as one where a grid starts or stops) keeps the "
              "other grid. "
              "A row goes only when every hour of its span is in a whole bar "
              "that stays (a grid's last bar before it stopped may be short) "
              "or in a 4h period another grid shows empty (no bar at a "
              "session's edge, that grid written on both sides): one bar per "
              "period, and no hour loses its bar.")


def _whole(preferred):
    """Why a session keeps the grid its stretch does not prefer."""
    return (f"which holds every hour of the session(s) there; the "
            f"{preferred} grid does not")


def _left_words(rows, symbols):
    """The overlapping rows the command leaves, as it says it."""
    return (f"{rows} overlapping off-grid 4h row(s) in {symbols} symbol(s) "
            f"are left as they are: no grid holds every hour of their "
            f"session, so deleting either could leave an hour without a "
            f"bar.")


def _days(n=10, first=MONDAY):
    """n weekdays from `first` on."""
    out, d = [], first
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


DAYS = _days()

#: Monday 2025-07-07, 00:00 UTC: Sydney's winter (AEST), Chicago's
#: summer (CDT). Ten weekdays from it.
JULY_DAYS = _days(first=datetime(2025, 7, 7, tzinfo=UTC))


def _inst(symbol):
    from instruments.models import Instrument
    return Instrument.objects.create(symbol=symbol, name=symbol,
                                     asset_class="index", is_active=True)


def _put(inst, ts, source="yfinance_public", px=100.0):
    from market_data.models import PriceData
    return PriceData.objects.create(
        instrument=inst, timeframe="4h", timestamp=ts, open=px,
        high=px + 1, low=px - 1, close=px, volume=1, source=source)


def _bars(inst, days, hours, source="yfinance_public"):
    for day in days:
        for h in hours:
            _put(inst, day + h * H, source)


def _stamps(days, hours):
    return sorted(day + h * H for day in days for h in hours)


def _hours(days, hours=XETRA_WINTER):
    """The trading hours (UTC) on `days`."""
    return [day + h * H for day in days for h in hours]


def _left(inst):
    """The instrument's 4h timestamps, oldest first."""
    from market_data.models import PriceData
    return sorted(PriceData.objects.filter(instrument=inst, timeframe="4h")
                  .values_list("timestamp", flat=True))


def _overlapping(inst):
    """The instrument's public 4h bars that overlap the bar before them."""
    from market_data.models import PriceData
    stamps = sorted(PriceData.objects
                    .filter(instrument=inst, timeframe="4h",
                            source__endswith="_public")
                    .values_list("timestamp", flat=True))
    return [(a, b) for a, b in zip(stamps, stamps[1:]) if b - a < 4 * H]


def _listed(symbol):
    """The timestamps the command would delete for `symbol`."""
    from market_data.management.commands.prune_offgrid_4h import \
        offgrid_duplicates
    return sorted(ts for _pk, ts, _s in offgrid_duplicates().get(symbol, []))


def _groups(symbol):
    from market_data.management.commands.prune_offgrid_4h import \
        offgrid_groups
    return offgrid_groups().get(symbol, [])


def _run(*args):
    out = StringIO()
    call_command("prune_offgrid_4h", *args, stdout=out, no_color=True)
    return out.getvalue()


def _span(rows):
    return (f"{rows[0]:%Y-%m-%d %H:%M} to {rows[-1]:%Y-%m-%d %H:%M} UTC")


class _OnePeriodOneBar:
    """What the clean-up promises, read off the table."""

    def assertOneBarPerPeriod(self, stamps):
        """No two bars of one 4h period: no two stamps within two hours."""
        for a, b in zip(stamps, stamps[1:]):
            self.assertGreater((b - a).total_seconds(), 2 * 3600,
                               f"two bars of one 4h period: {a} and {b}")

    def assertNoPeriodLost(self, before, after):
        """Every deleted bar's period keeps a bar: its twin, within two
        hours of it, stays."""
        kept = sorted(after)
        for gone in sorted(set(before) - set(after)):
            i = bisect.bisect_left(kept, gone)
            near = kept[max(0, i - 1):i + 1]
            self.assertTrue(
                any(abs((k - gone).total_seconds()) <= 2 * 3600
                    for k in near),
                f"the 4h period of {gone} lost its bar")

    def assertNoHourLost(self, hours, after):
        """Every trading hour of `hours` is in a 4h bar that is left
        (2026-11-01). The bar opening last at or before an hour is the
        only one that can hold it."""
        kept = sorted(after)
        for h in hours:
            i = bisect.bisect_right(kept, h) - 1
            self.assertTrue(i >= 0 and h < kept[i] + 4 * H,
                            f"the trading hour {h} lost its bar")


# ═══ 1. A CET series with both old grids over one stretch ══════════════

class TwoOldGridsKeepOneTests(_OnePeriodOneBar, TestCase):
    """DAX40: the CEST grid alone, then both grids over a stretch, then
    the CET grid alone. Nothing is on the UTC grid there, so the first
    rule (beside the UTC grid) saw nothing."""

    def setUp(self):
        self.dax = _inst("DAX40")
        _bars(self.dax, DAYS[0:3], CEST)
        _bars(self.dax, DAYS[3:7], CEST + CET)
        _bars(self.dax, DAYS[7:10], CET)
        self.before = _left(self.dax)

    def test_the_stretch_is_listed_one_grid_per_session(self):
        # The bars before the stretch are CEST's, the bars after it CET's:
        # continuity cannot decide, so the stretch prefers the later anchor
        # (CET's midnight, 23:00 UTC; its bars open an hour after CEST's).
        # Its first session, Mar 5, keeps CEST's bars (2026-11-01, on
        # review): CET's grid starts there, nothing on it shows whether
        # 06:00 UTC traded (CEST's 06:00 bar), and CEST's bars hold every
        # hour of CET's. The grid changes overnight, between two sessions.
        self.assertEqual(_listed("DAX40"), sorted(
            _stamps(DAYS[3:4], CET) + _stamps(DAYS[4:7], CEST)))
        first, body = _groups("DAX40")
        self.assertEqual(
            (first["rule"], first["kept"], first["why"], first["preferred"]),
            ("pair", 2 * 3600, "whole", 3 * 3600))
        self.assertEqual(body["rule"], "pair")
        self.assertEqual(body["kept"], 3 * 3600)
        self.assertEqual(body["why"], "split")

    def test_yes_leaves_one_bar_per_period_and_no_gap(self):
        _run("--yes")
        after = _left(self.dax)
        self.assertEqual(after, _stamps(DAYS[0:4], CEST)
                         + _stamps(DAYS[4:10], CET))
        self.assertOneBarPerPeriod(after)
        self.assertNoPeriodLost(self.before, after)
        self.assertNoHourLost(_hours(DAYS), after)
        # Three bars per session, every session.
        for day in DAYS:
            self.assertEqual(
                sum(1 for t in after if t.date() == day.date()), 3, day)

    def test_the_lone_stretches_beside_it_stay(self):
        _run("--yes")
        after = set(_left(self.dax))
        for t in _stamps(DAYS[0:3], CEST) + _stamps(DAYS[7:10], CET):
            self.assertIn(t, after)

    def test_the_empty_line_comes_only_once_the_pairs_are_gone(self):
        # The words the operator's sheet waits for were said while both
        # grids were still in the table.
        self.assertNotEqual(_run(), EMPTY + "\n")
        _run("--yes")
        self.assertEqual(_run(), EMPTY + "\n")


class AGridStartingInsideASessionTests(_OnePeriodOneBar, TestCase):
    """DAX40 (2026-11-01, on review): the stretch prefers CET's grid, the
    later anchor, and CET's grid STARTS on Mar 5 inside the session. Its
    first pass wrote its 200 bars from wherever the 200th fell (a Xetra
    session has 3 bars, and 200 = 66 x 3 + 2), so that day holds only its
    last bar or two. The hour before CET's first bar is in CEST's bar
    alone: the first cut deleted that bar as the twin of CET's, left the
    hour without a bar, and said that no period had lost its bar."""

    def _check(self, first_cet):
        dax = _inst("DAX40")
        _bars(dax, DAYS[0:3], CEST)
        _bars(dax, DAYS[3:4], CEST + first_cet)
        _bars(dax, DAYS[4:7], CEST + CET)
        _bars(dax, DAYS[7:10], CET)
        self.assertNoHourLost(_hours(DAYS), _left(dax))
        dry = _run()
        _run("--yes")
        after = _left(dax)
        self.assertNoHourLost(_hours(DAYS), after)
        self.assertOneBarPerPeriod(after)
        # Mar 5 keeps CEST's bars whole, CET's grid from Mar 6 on: the
        # grid changes overnight.
        self.assertEqual(after, _stamps(DAYS[0:4], CEST)
                         + _stamps(DAYS[4:10], CET))
        self.assertIn(
            f"  DAX40: {len(first_cet)} off-grid 4h row(s) of "
            f"yfinance_public on the {G3} grid beside the {G2} grid's, "
            f"{_span(_stamps(DAYS[3:4], first_cet))}; kept: the {G2} grid, "
            f"{_whole(G3)}", dry.splitlines())
        self.assertEqual(_run(), EMPTY + "\n")

    def test_its_first_session_holds_its_last_two_bars(self):
        # CET's 11:00 and 15:00 bars: CEST's 10:00 bar alone holds 10:00.
        self._check((11, 15))

    def test_its_first_session_holds_its_last_bar(self):
        # CET's 15:00 bar: CEST's 14:00 bar alone holds 14:00.
        self._check((15,))


class AGridStoppingInsideASessionTests(_OnePeriodOneBar, TestCase):
    """DAX40 (2026-11-01, on review): the stretch prefers CET's grid, here
    the EARLIER grid (the later anchor; the bars before and after the
    stretch disagree), and CET's grid STOPS on Mar 10 inside the session:
    its last pass, at noon, wrote its 11:00 bar with 11:00 alone in it.
    The first cut kept that bar and deleted CEST's 10:00 bar as its twin,
    the one bar holding 12:00 and 13:00 whole."""

    def setUp(self):
        self.dax = _inst("DAX40")
        _bars(self.dax, DAYS[0:3], CET)
        _bars(self.dax, DAYS[3:6], CET + CEST)
        _bars(self.dax, DAYS[6:7], (7, 11) + CEST)
        _bars(self.dax, DAYS[7:10], CEST)

    def test_its_last_session_keeps_the_other_grid(self):
        self.assertEqual(_listed("DAX40"), sorted(
            _stamps(DAYS[3:6], CEST) + _stamps(DAYS[6:7], (7, 11))))
        body, last = _groups("DAX40")
        self.assertEqual((body["kept"], body["why"]), (3 * 3600, "split"))
        self.assertEqual((last["kept"], last["why"], last["preferred"]),
                         (2 * 3600, "whole", 3 * 3600))

    def test_the_bar_holding_its_hours_whole_stays(self):
        _run("--yes")
        after = _left(self.dax)
        self.assertEqual(after, _stamps(DAYS[0:6], CET)
                         + _stamps(DAYS[6:10], CEST))
        self.assertIn(DAYS[6] + 10 * H, after)
        self.assertNotIn(DAYS[6] + 11 * H, after)
        self.assertNoHourLost(_hours(DAYS), after)
        self.assertOneBarPerPeriod(after)
        self.assertEqual(_run(), EMPTY + "\n")


class TheKeptGridFollowsItsNeighboursTests(_OnePeriodOneBar, TestCase):

    def test_continuity_beats_the_later_anchor(self):
        # CEST before and after the stretch: CEST stays, though CET's is
        # the later anchor.
        dax = _inst("DAX40")
        _bars(dax, DAYS[0:3], CEST)
        _bars(dax, DAYS[3:7], CEST + CET)
        _bars(dax, DAYS[7:10], CEST)
        self.assertEqual(_listed("DAX40"), _stamps(DAYS[3:7], CET))
        (group,) = _groups("DAX40")
        self.assertEqual((group["kept"], group["why"]), (2 * 3600, "both"))
        before = _left(dax)
        _run("--yes")
        after = _left(dax)
        self.assertEqual(after, _stamps(DAYS, CEST))
        self.assertNoPeriodLost(before, after)
        self.assertNoHourLost(_hours(DAYS), after)

    def test_one_side_decides_when_the_other_is_the_utc_grid(self):
        # The newest old-grid stretch ends where the new UTC grid begins
        # (cleared beside it by the first rule): the bar after the
        # stretch is on the UTC grid, the one before it on CEST's.
        # CEST's grid stops on Mar 10 (2026-11-01, on review): none of
        # its bars comes after, while CET's go on beside the UTC grid, so
        # CEST's last bar may be short and Mar 10 keeps CET's bars.
        dax = _inst("DAX40")
        _bars(dax, DAYS[0:3], CEST)
        _bars(dax, DAYS[3:7], CEST + CET)
        _bars(dax, DAYS[7:10], UTC_GRID + CET)
        self.assertEqual(_listed("DAX40"), sorted(
            _stamps(DAYS[3:6], CET) + _stamps(DAYS[6:7], CEST)
            + _stamps(DAYS[7:10], CET)))
        utc, pair, last = _groups("DAX40")
        self.assertEqual(utc["rule"], "utc")
        self.assertEqual(sorted(ts for _pk, ts, _s in utc["rows"]),
                         _stamps(DAYS[7:10], CET))
        self.assertEqual((pair["kept"], pair["why"]), (2 * 3600, "before"))
        self.assertEqual((last["kept"], last["why"], last["preferred"]),
                         (3 * 3600, "whole", 2 * 3600))
        # The stretch's bars (the UTC grid's rule clears the last three
        # days by its own test, overlap with an on-grid bar).
        stretch = [t for t in _left(dax) if t < DAYS[7]]
        _run("--yes")
        after = _left(dax)
        self.assertEqual(after, sorted(_stamps(DAYS[0:6], CEST)
                                       + _stamps(DAYS[6:7], CET)
                                       + _stamps(DAYS[7:10], UTC_GRID)))
        self.assertOneBarPerPeriod(after)
        self.assertNoPeriodLost(stretch, after)
        self.assertNoHourLost(_hours(DAYS[0:7]), after)

    def test_the_bar_after_decides_when_nothing_is_before(self):
        dax = _inst("DAX40")
        _bars(dax, DAYS[0:4], CEST + CET)
        _bars(dax, DAYS[4:7], CEST)
        self.assertEqual(_listed("DAX40"), _stamps(DAYS[0:4], CET))
        (group,) = _groups("DAX40")
        self.assertEqual((group["kept"], group["why"]), (2 * 3600, "after"))

    def test_no_neighbour_the_later_anchor(self):
        # Nothing before or after the stretch: it prefers the later
        # anchor, CET's. Both grids start on Mar 2 and stop on Mar 5
        # (2026-11-01, on review): Mar 2 keeps CEST's bars (its first bar
        # opens first, and nothing on CET's grid shows whether 06:00 UTC
        # traded); on Mar 5 each grid's last bar may be short, so no grid
        # holds every hour of the other's, and the session is left as it
        # is, said in the list.
        dax = _inst("DAX40")
        _bars(dax, DAYS[0:4], CEST + CET)
        self.assertEqual(_listed("DAX40"), sorted(
            _stamps(DAYS[0:1], CET) + _stamps(DAYS[1:3], CEST)))
        first, body, left = _groups("DAX40")
        self.assertEqual((first["kept"], first["why"]), (2 * 3600, "whole"))
        self.assertEqual((body["kept"], body["why"]), (3 * 3600, "none"))
        self.assertEqual(left["rule"], "left")
        self.assertEqual(sorted(ts for _pk, ts, _s in left["rows"]),
                         _stamps(DAYS[3:4], CEST + CET))

    def test_a_bar_with_no_twin_on_the_kept_grid_stays(self):
        # CET keeps the stretch, but CET has no 11:00 bar on Mar 6: the
        # CEST 10:00 bar is that period's only bar, so it stays. A missing
        # bar inside a session, between bars, is likelier a row lost than a
        # pause in trading, so it vouches for no hour, and CET's bars do not
        # hold that session: Mar 6 keeps CEST's three bars whole, and CET's
        # 07:00 and 15:00 bars go (2026-11-01, on review: the first cut
        # kept CEST's 10:00 bar alone, beside CET's 07:00).
        dax = _inst("DAX40")
        _bars(dax, DAYS[0:3], CEST)
        _bars(dax, DAYS[3:7], CEST + CET)
        _bars(dax, DAYS[7:10], CET)
        from market_data.models import PriceData
        hole = DAYS[4] + 11 * H
        PriceData.objects.filter(instrument=dax, timestamp=hole).delete()
        lone = DAYS[4] + 10 * H
        listed = _listed("DAX40")
        self.assertNotIn(lone, listed)
        self.assertEqual(len(listed), 11)
        self.assertIn(DAYS[4] + 7 * H, listed)
        self.assertIn(DAYS[4] + 15 * H, listed)
        # Mar 5 (where CET's grid starts) and Mar 6 keep CEST's bars: one
        # line, its reason true of both.
        self.assertIn(
            f"  DAX40: 5 off-grid 4h row(s) of yfinance_public on the {G3} "
            f"grid beside the {G2} grid's, "
            f"{_span([DAYS[3] + 7 * H, DAYS[4] + 15 * H])}; kept: the {G2} "
            f"grid, {_whole(G3)}", _run().splitlines())
        before = _left(dax)
        _run("--yes")
        after = _left(dax)
        self.assertIn(lone, after)
        self.assertNoPeriodLost(before, after)
        self.assertEqual([t for t in after if t.date() == DAYS[4].date()],
                         _stamps(DAYS[4:5], CEST))
        self.assertNoHourLost(_hours(DAYS), after)
        self.assertOneBarPerPeriod(after)
        self.assertEqual(_overlapping(dax), [])
        self.assertEqual(_run(), EMPTY + "\n")

    def test_a_period_beside_a_bar_on_the_utc_grid_is_not_read_as_empty(
            self):
        # CEST's bars before and after the stretch: CEST's grid is
        # preferred. On Mar 6 a venue's bar sits on the UTC grid at 16:00,
        # and the first rule, on an earlier run, deleted the old grids'
        # bars beside it, CEST's 14:00 and CET's 15:00. CEST's 14:00
        # period is empty of rows, not of trades (2026-11-01, on review):
        # CET's 11:00 bar alone holds 14:00 now, and Mar 6 keeps CET's
        # bars.
        dax = _inst("DAX40")
        _bars(dax, DAYS[0:3], CEST)
        _bars(dax, DAYS[3:7], CEST + CET)
        _bars(dax, DAYS[7:10], CEST)
        from market_data.models import PriceData
        PriceData.objects.filter(instrument=dax, timestamp__in=[
            DAYS[4] + 14 * H, DAYS[4] + 15 * H]).delete()
        _put(dax, DAYS[4] + 16 * H, source="etoro")
        # 15:00 on Mar 6 went with the first rule's earlier run.
        held = [h for h in _hours(DAYS) if h != DAYS[4] + 15 * H]
        self.assertNoHourLost(held, _left(dax))
        self.assertEqual(_listed("DAX40"), sorted(
            _stamps(DAYS[3:4], CET) + _stamps(DAYS[4:5], (6, 10))
            + _stamps(DAYS[5:7], CET)))
        body, mar6, rest = _groups("DAX40")
        self.assertEqual((body["kept"], body["why"]), (2 * 3600, "both"))
        self.assertEqual((mar6["kept"], mar6["why"]), (3 * 3600, "whole"))
        self.assertEqual((rest["kept"], rest["why"]), (2 * 3600, "both"))
        _run("--yes")
        after = _left(dax)
        self.assertIn(DAYS[4] + 11 * H, after)
        self.assertNoHourLost(held, after)
        self.assertEqual(_overlapping(dax), [])
        self.assertEqual(_run(), EMPTY + "\n")

    def test_a_stretch_cut_by_an_earlier_run_of_the_first_rule(self):
        # The operator ran the first rule's clean-up after the update of
        # 2026-10-31: CET's bars beside the UTC grid's are gone, so neither
        # old grid has a bar after the stretch. They ran into the UTC grid;
        # they did not stop, and their last bars are whole (2026-11-01, on
        # review): Mar 10 keeps CEST's bars, as the whole stretch does.
        dax = _inst("DAX40")
        _bars(dax, DAYS[0:3], CEST)
        _bars(dax, DAYS[3:7], CEST + CET)
        _bars(dax, DAYS[7:10], UTC_GRID)
        self.assertEqual(_listed("DAX40"), _stamps(DAYS[3:7], CET))
        (group,) = _groups("DAX40")
        self.assertEqual((group["kept"], group["why"]), (2 * 3600, "before"))
        _run("--yes")
        after = _left(dax)
        self.assertEqual(after, sorted(_stamps(DAYS[0:7], CEST)
                                       + _stamps(DAYS[7:10], UTC_GRID)))
        self.assertNoHourLost(_hours(DAYS[0:7]), after)
        self.assertEqual(_run(), EMPTY + "\n")


class TheLaterAnchorTests(SimpleTestCase):

    def test_the_grid_whose_bars_open_an_hour_after_the_other_s(self):
        from market_data.management.commands.prune_offgrid_4h import \
            _later_anchor
        # CET's midnight (23:00 UTC: bars at 03, 07, 11... UTC) over
        # CEST's (22:00 UTC: 02, 06, 10...).
        self.assertEqual(_later_anchor({2 * 3600, 3 * 3600}), 3 * 3600)
        # Sydney's AEST midnight (14:00 UTC: 02, 06, 10...) over AEDT's
        # (13:00 UTC: 01, 05, 09...); Helsinki's and Chicago's clocks
        # land on the same two grids.
        self.assertEqual(_later_anchor({3600, 2 * 3600}), 2 * 3600)
        # Two grids two hours apart: neither opens first, the larger
        # offset is kept.
        self.assertEqual(_later_anchor({3600, 3 * 3600}), 3 * 3600)


# ═══ 2. London, New York, Tokyo: the UTC grid's rule, as before ═══════

class TheUtcGridRuleIsUnchangedTests(TestCase):

    def test_london_is_cleared_beside_the_utc_grid_as_before(self):
        # FTSE100: the summer grid alone (history), then the winter grid
        # (the UTC grid) beside the summer grid, then the winter grid.
        ftse = _inst("FTSE100")
        _bars(ftse, DAYS[0:3], BST)
        _bars(ftse, DAYS[3:7], GMT + BST)
        _bars(ftse, DAYS[7:10], GMT)
        rows = _stamps(DAYS[3:7], BST)
        self.assertEqual(_listed("FTSE100"), rows)
        # The dry run prints what it printed before this change: the UTC
        # grid's rule, and no word of the old-grid rule.
        self.assertEqual(_run(), (
            f"  FTSE100: 12 off-grid 4h row(s) of yfinance_public beside "
            f"the UTC grid's, {_span(rows)}\n"
            "Dry run: 12 row(s) in 1 symbol(s) would be deleted, nothing "
            "was. Run again with --yes to delete them.\n"))
        _run("--yes")
        self.assertEqual(_left(ftse), sorted(_stamps(DAYS[0:3], BST)
                                             + _stamps(DAYS[3:10], GMT)))

    def test_tokyo_one_old_grid_its_history_stays(self):
        # Tokyo's session is 00:00-06:00 UTC; its one old grid is anchored
        # at JST's midnight, 15:00 UTC: bars at 23:00 (the day before) and
        # 03:00. The new grid stands beside it on the last three days.
        nikkei = _inst("NIKKEI225")
        for day in DAYS:
            _put(nikkei, day - H)
            _put(nikkei, day + 3 * H)
        for day in DAYS[7:10]:
            _put(nikkei, day)
            _put(nikkei, day + 4 * H)
        rows = sorted([d - H for d in DAYS[7:10]]
                      + [d + 3 * H for d in DAYS[7:10]])
        self.assertEqual(_listed("NIKKEI225"), rows)
        self.assertEqual(_run(), (
            f"  NIKKEI225: 6 off-grid 4h row(s) of yfinance_public beside "
            f"the UTC grid's, {_span(rows)}\n"
            "Dry run: 6 row(s) in 1 symbol(s) would be deleted, nothing "
            "was. Run again with --yes to delete them.\n"))
        _run("--yes")
        self.assertEqual(_left(nikkei), sorted(
            [d - H for d in DAYS[0:7]] + [d + 3 * H for d in DAYS[0:7]]
            + [d for d in DAYS[7:10]] + [d + 4 * H for d in DAYS[7:10]]))


# ═══ 3. A venue's rows: never listed, never deleted ═══════════════════

class AVenuesRowIsNeverListedTests(TestCase):

    def test_a_venue_row_on_the_dropped_grid_stays(self):
        # The stretch prefers CET's grid (the later anchor); one CEST bar
        # is a venue's, beside its CET twin: it is not the public feed's.
        # Mar 3 keeps CET's bars and drops the public CEST bars around the
        # venue's (2026-11-01, on review: Mar 2 keeps CEST's, where both
        # grids start, and Mar 5, where both stop, is left as it is).
        dax = _inst("DAX40")
        _bars(dax, DAYS[0:4], CET)
        for day in DAYS[0:4]:
            for h in CEST:
                src = "etoro" if (day, h) == (DAYS[1], 10) else \
                    "yfinance_public"
                _put(dax, day + h * H, src)
        listed = _listed("DAX40")
        self.assertEqual(len(listed), 8)
        self.assertNotIn(DAYS[1] + 10 * H, listed)
        self.assertIn(DAYS[1] + 6 * H, listed)
        self.assertIn(DAYS[1] + 14 * H, listed)
        from market_data.management.commands.prune_offgrid_4h import \
            offgrid_duplicates
        for _pk, _ts, src in offgrid_duplicates()["DAX40"]:
            self.assertTrue(src.endswith("_public"), src)
        _run("--yes")
        from market_data.models import PriceData
        self.assertTrue(PriceData.objects.filter(
            instrument=dax, timestamp=DAYS[1] + 10 * H,
            source="etoro").exists())

    def test_a_venue_row_on_either_old_grid_is_never_listed(self):
        # A venue's whole series on both old grids: nothing is listed.
        dax = _inst("DAX40")
        _bars(dax, DAYS[0:4], CEST + CET, source="etoro")
        self.assertEqual(_listed("DAX40"), [])
        self.assertEqual(_run(), EMPTY + "\n")

    def test_the_delete_reads_the_source_again(self):
        # A listed row that a venue's bar replaced between the list and
        # the delete (the bar pass writes in another process) stays.
        from market_data.management.commands import prune_offgrid_4h as cmd
        from market_data.models import PriceData
        dax = _inst("DAX40")
        _bars(dax, DAYS[0:4], CEST + CET)
        taken = DAYS[2] + 6 * H
        self.assertIn(taken, _listed("DAX40"))
        real = cmd.offgrid_groups

        def then_the_venue_writes(symbol=""):
            found = real(symbol)
            PriceData.objects.filter(instrument=dax, timestamp=taken) \
                .update(source="etoro")
            return found

        with patch.object(cmd, "offgrid_groups", then_the_venue_writes):
            text = _run("--yes")
        self.assertTrue(PriceData.objects.filter(
            instrument=dax, timestamp=taken, source="etoro").exists())
        self.assertIn("Deleted 8 off-grid 4h row(s) in 1 symbol(s).", text)
        self.assertIn("1 listed row(s) were no longer the public feed's", text)


# ═══ 4. Off-grid history with nothing overlapping it stays ════════════

class ALoneStretchStaysTests(TestCase):

    def test_two_old_grids_one_after_the_other_stay(self):
        # The grid moved over a night: CEST's bars, then CET's, nothing
        # overlapping. Both are history; nothing is listed.
        dax = _inst("DAX40")
        _bars(dax, DAYS[0:5], CEST)
        _bars(dax, DAYS[5:10], CET)
        before = _left(dax)
        self.assertEqual(_listed("DAX40"), [])
        self.assertEqual(_run(), EMPTY + "\n")
        _run("--yes")
        self.assertEqual(_left(dax), before)

    def test_one_old_grid_alone_stays(self):
        cac = _inst("CAC40")
        _bars(cac, DAYS, CET)
        self.assertEqual(_listed("CAC40"), [])
        self.assertEqual(_run("--symbol", "cac40"),
                         EMPTY[:-1] + " for CAC40.\n")


# ═══ 5. The output, and the dry run's promise ═════════════════════════

class TheOutputTests(TestCase):
    """CAC40: both old grids, nothing beside them (both start on Mar 2 and
    stop on Mar 5). DAX40: CEST's grid, both old grids, then the UTC grid
    with CET's bars beside it (CEST's grid stops on Mar 10)."""

    def setUp(self):
        self.cac = _inst("CAC40")
        _bars(self.cac, DAYS[0:4], CEST + CET)
        self.dax = _inst("DAX40")
        _bars(self.dax, DAYS[0:3], CEST)
        _bars(self.dax, DAYS[3:7], CEST + CET)
        _bars(self.dax, DAYS[7:10], UTC_GRID + CET)
        self.lines = [
            f"  CAC40: 3 off-grid 4h row(s) of yfinance_public on the {G3} "
            f"grid beside the {G2} grid's, "
            f"{_span(_stamps(DAYS[0:1], CET))}; kept: the {G2} grid, "
            f"{_whole(G3)}",
            f"  CAC40: 6 off-grid 4h row(s) of yfinance_public on the {G2} "
            f"grid beside the {G3} grid's, "
            f"{_span(_stamps(DAYS[1:3], CEST))}; kept: the {G3} grid, the "
            f"later anchor (no bar beside the stretch is on one of its "
            f"grids)",
            f"  CAC40: 6 off-grid 4h row(s) of yfinance_public on the {G2} "
            f"and {G3} grids overlap, "
            f"{_span(_stamps(DAYS[3:4], CEST + CET))}; left as they are: "
            f"no grid holds every hour of the session(s) there",
            f"  DAX40: 9 off-grid 4h row(s) of yfinance_public beside the "
            f"UTC grid's, {_span(_stamps(DAYS[7:10], CET))}",
            f"  DAX40: 9 off-grid 4h row(s) of yfinance_public on the {G3} "
            f"grid beside the {G2} grid's, "
            f"{_span(_stamps(DAYS[3:6], CET))}; kept: the {G2} grid, the "
            f"grid of the bar before the stretch",
            f"  DAX40: 3 off-grid 4h row(s) of yfinance_public on the {G2} "
            f"grid beside the {G3} grid's, "
            f"{_span(_stamps(DAYS[6:7], CEST))}; kept: the {G3} grid, "
            f"{_whole(G2)}",
            RULE_WORDS,
        ]

    def _count(self):
        from market_data.models import PriceData
        return PriceData.objects.filter(timeframe="4h").count()

    def test_the_dry_run_lists_by_symbol_with_the_rule(self):
        n = self._count()
        text = _run()
        self.assertEqual(text.splitlines(), self.lines + [
            "Dry run: 30 row(s) in 2 symbol(s) would be deleted, nothing "
            "was. Run again with --yes to delete them.",
            _left_words(6, 1)])
        self.assertEqual(self._count(), n)

    def test_yes_deletes_what_the_dry_run_listed_and_counts_it(self):
        from market_data.management.commands.prune_offgrid_4h import \
            offgrid_duplicates
        from market_data.models import PriceData
        promised = {pk for rows in offgrid_duplicates().values()
                    for pk, _ts, _s in rows}
        self.assertEqual(len(promised), 30)
        every = set(PriceData.objects.values_list("pk", flat=True))
        text = _run("--yes")
        self.assertEqual(text.splitlines(), self.lines + [
            "Deleted 30 off-grid 4h row(s) in 2 symbol(s).",
            _left_words(6, 1)])
        gone = every - set(PriceData.objects.values_list("pk", flat=True))
        self.assertEqual(gone, promised)
        # What is left overlapping is said again, and the empty line is
        # not (2026-11-01, on review): it means nothing overlaps.
        self.assertEqual(_run().splitlines(), [
            self.lines[2], "Nothing to delete. " + _left_words(6, 1)])
        self.assertEqual(_overlapping(self.dax), [])
        self.assertEqual(len(_overlapping(self.cac)), 5)

    def test_one_symbol(self):
        text = _run("--symbol", "CAC40")
        self.assertEqual(text.splitlines(), self.lines[0:3] + [RULE_WORDS,
            "Dry run: 9 row(s) in 1 symbol(s) would be deleted, nothing "
            "was. Run again with --yes to delete them.",
            _left_words(6, 1)])


class TheEmptyLineMeansNothingOverlapsTests(TestCase):
    """The empty line is the operator's all-clear (2026-11-01, on review):
    it is said only when no public off-grid bars overlap. DAX40: CEST's
    grid alone, then both grids over Mar 4 and Mar 5, where the series
    ends: both grids stop inside Mar 5's session, each one's last bar may
    be short of hours, so neither grid holds every hour of the other's."""

    def setUp(self):
        self.dax = _inst("DAX40")
        _bars(self.dax, DAYS[0:2], CEST)
        _bars(self.dax, DAYS[2:4], CEST + CET)
        self.held = _stamps(DAYS[3:4], CEST + CET)
        self.lines = [
            f"  DAX40: 3 off-grid 4h row(s) of yfinance_public on the {G3} "
            f"grid beside the {G2} grid's, "
            f"{_span(_stamps(DAYS[2:3], CET))}; kept: the {G2} grid, the "
            f"grid of the bar before the stretch",
            f"  DAX40: 6 off-grid 4h row(s) of yfinance_public on the {G2} "
            f"and {G3} grids overlap, {_span(self.held)}; left as they "
            f"are: no grid holds every hour of the session(s) there",
        ]

    def test_the_dry_run_says_what_it_leaves(self):
        self.assertEqual(_run().splitlines(), self.lines + [
            RULE_WORDS,
            "Dry run: 3 row(s) in 1 symbol(s) would be deleted, nothing "
            "was. Run again with --yes to delete them.",
            _left_words(6, 1)])
        self.assertEqual(_listed("DAX40"), _stamps(DAYS[2:3], CET))

    def test_the_empty_line_is_not_said_while_bars_overlap(self):
        _run("--yes")
        self.assertEqual(_overlapping(self.dax), [
            (a, b) for a, b in zip(self.held, self.held[1:])])
        self.assertEqual(_run().splitlines(), [
            self.lines[1], "Nothing to delete. " + _left_words(6, 1)])
        self.assertEqual(_run("--yes").splitlines(), [
            self.lines[1], "Nothing to delete. " + _left_words(6, 1)])
        self.assertEqual(_left(self.dax)[-6:], self.held)


# ═══ 6. Sydney's and Chicago's clocks: a bar without a twin ═══════════

class SydneyInTheAestSeasonTests(_OnePeriodOneBar, TestCase):
    """ASX200 in Sydney's winter (2026-11-01, on review): Yahoo's hourly
    bars open at 00:00 to 05:00 UTC (10:00 to 15:00 AEST). The old grid
    anchored at AEDT's midnight (13:00 UTC) has bars at 21:00 (the evening
    before), 01:00 and 05:00 UTC; the one anchored at AEST's (14:00 UTC),
    at 22:00 and 02:00. The AEDT grid's 05:00 bar holds 05:00 alone, inside
    the AEST grid's 02:00 bar, and has no twin (the AEST grid's 06:00
    period is empty): the first cut kept it beside the 02:00 bar, every
    session, and then said there was nothing left."""

    AEDT = (-3, 1, 5)
    AEST = (-2, 2)
    HOURS = tuple(range(0, 6))

    def setUp(self):
        self.asx = _inst("ASX200")
        _bars(self.asx, JULY_DAYS[0:3], self.AEDT)
        _bars(self.asx, JULY_DAYS[3:7], self.AEDT + self.AEST)
        _bars(self.asx, JULY_DAYS[7:10], self.AEST)

    def test_no_bar_overlaps_when_the_empty_line_is_said(self):
        _run("--yes")
        self.assertEqual(_run(), EMPTY + "\n")
        self.assertEqual(_overlapping(self.asx), [])

    def test_one_grid_per_session_and_no_hour_lost(self):
        # The stretch prefers the AEST grid (the later anchor). Its first
        # session keeps the AEDT grid's bars: the AEST grid starts there,
        # and nothing on it shows whether 21:00 UTC traded.
        self.assertEqual(_listed("ASX200"), sorted(
            _stamps(JULY_DAYS[3:4], self.AEST)
            + _stamps(JULY_DAYS[4:7], self.AEDT)))
        first, body = _groups("ASX200")
        self.assertEqual((first["kept"], first["why"]), (3600, "whole"))
        self.assertEqual((body["kept"], body["why"]), (2 * 3600, "split"))
        self.assertEqual(body["grids"], [3600])
        _run("--yes")
        after = _left(self.asx)
        self.assertEqual(after, sorted(_stamps(JULY_DAYS[0:4], self.AEDT)
                                       + _stamps(JULY_DAYS[4:10], self.AEST)))
        self.assertOneBarPerPeriod(after)
        self.assertNoHourLost(_hours(JULY_DAYS, self.HOURS), after)


class ChicagoInTheCdtSeasonTests(_OnePeriodOneBar, TestCase):
    """CME live cattle in Chicago's summer (2026-11-01, on review): Yahoo's
    hourly bars open at 13:00 to 18:00 UTC (08:00 to 13:00 CDT). The old
    grid anchored at CST's midnight (06:00 UTC) has bars at 10:00, 14:00
    and 18:00 UTC; the one anchored at CDT's (05:00 UTC), at 13:00 and
    17:00, kept here by continuity. The CST grid's 10:00 bar holds 13:00
    alone, inside the 13:00 bar, and has no twin (the CDT grid's 09:00
    period is empty): the first cut kept it, every session."""

    CST = (10, 14, 18)
    CDT = (13, 17)
    HOURS = tuple(range(13, 19))

    def setUp(self):
        self.cattle = _inst("LIVECATTLE")
        _bars(self.cattle, JULY_DAYS[0:3], self.CDT)
        _bars(self.cattle, JULY_DAYS[3:7], self.CST + self.CDT)
        _bars(self.cattle, JULY_DAYS[7:10], self.CDT)

    def test_no_bar_overlaps_when_the_empty_line_is_said(self):
        _run("--yes")
        self.assertEqual(_run(), EMPTY + "\n")
        self.assertEqual(_overlapping(self.cattle), [])

    def test_the_other_grid_goes_whole_and_no_hour_lost(self):
        self.assertEqual(_listed("LIVECATTLE"),
                         _stamps(JULY_DAYS[3:7], self.CST))
        (group,) = _groups("LIVECATTLE")
        self.assertEqual((group["kept"], group["why"]), (3600, "both"))
        self.assertIn(
            f"  LIVECATTLE: 12 off-grid 4h row(s) of yfinance_public on the "
            f"{G2} grid beside the {G1} grid's, "
            f"{_span(_stamps(JULY_DAYS[3:7], self.CST))}; kept: the {G1} "
            f"grid, the grid of the bars before and after the stretch",
            _run().splitlines())
        _run("--yes")
        after = _left(self.cattle)
        self.assertEqual(after, _stamps(JULY_DAYS, self.CDT))
        self.assertOneBarPerPeriod(after)
        self.assertNoHourLost(_hours(JULY_DAYS, self.HOURS), after)


# ═══ 7. The old feed's own rolling window, replayed ═══════════════════

BERLIN = ZoneInfo("Europe/Berlin")
WINDOW_DAYS = 202    # public_feed.days_for("4h", 200)
KEEP = 200           # bot_bars.DEFAULT_LIMIT


def _xetra_hours(first, last):
    """The hourly bars Yahoo serves for a Xetra index: 09:00 to 17:00
    Berlin time on weekdays, as UTC epoch seconds."""
    out, d = [], first
    while d <= last:
        if d.weekday() < 5:
            for h in range(9, 18):
                out.append(int(datetime(d.year, d.month, d.day, h,
                                        tzinfo=BERLIN).timestamp()))
        d += timedelta(days=1)
    return out


XETRA_HOURS = _xetra_hours(date(2025, 1, 1), date(2026, 11, 2))


def _replayed_rows():
    """The opens (epoch seconds) of the 4h bars the feed left for a Xetra
    index: the old feed passing once a day from 2025-09-01 to 2026-10-30
    (each pass anchors its grid at the Berlin midnight of its window's
    first trading day and writes the last 200 bars), then the new feed's
    one UTC grid on 2026-11-01."""
    hours = XETRA_HOURS
    written = set()

    def window(at):
        lo = bisect.bisect_left(hours, at - WINDOW_DAYS * 86400)
        hi = bisect.bisect_right(hours, at)
        return hours[lo:hi]

    at = int(datetime(2025, 9, 1, 12, tzinfo=UTC).timestamp())
    end = int(datetime(2026, 10, 31, tzinfo=UTC).timestamp())
    while at < end:
        frame = window(at)
        first = datetime.fromtimestamp(frame[0], BERLIN)
        anchor = int(datetime(first.year, first.month, first.day,
                              tzinfo=BERLIN).timestamp())
        bins = sorted({anchor + (h - anchor) // FOUR_H * FOUR_H
                       for h in frame})
        written.update(bins[-KEEP:])
        at += 86400
    frame = window(int(datetime(2026, 11, 1, 12, tzinfo=UTC).timestamp()))
    written.update(sorted({h // FOUR_H * FOUR_H for h in frame})[-KEEP:])
    return sorted(written)


def _replayed_table(minute=5):
    """{open (epoch s): the hourly opens it holds} of the 4h bars the feed
    left for a Xetra index, each bar as its last pass wrote it (2026-11-01,
    on review): the old feed passing every hour at :`minute` from
    2025-09-01 to the update of 2026-10-31 12:`minute` UTC (the bar
    refresh runs every ten minutes and sees the same hourly bars within an
    hour), each pass anchoring its grid at the Berlin midnight of its
    window's first trading day and writing the last 200 bars, the newest
    holding its period's hours so far; then the new feed's UTC grid every
    hour to 2026-11-01. A pass whose window holds the same hourly bars as
    the pass before writes the same rows, and is skipped."""
    hours = XETRA_HOURS
    content = {}
    start = int(datetime(2025, 9, 1, 0, minute, tzinfo=UTC).timestamp())
    update = int(datetime(2026, 10, 31, 12, minute, tzinfo=UTC).timestamp())
    end = int(datetime(2026, 11, 1, 12, minute, tzinfo=UTC).timestamp())
    seen = None
    for at in range(start, end + 1, 3600):
        new = at >= update
        lo = bisect.bisect_left(hours, at - WINDOW_DAYS * 86400)
        hi = bisect.bisect_right(hours, at)
        if (lo, hi, new) == seen:
            continue
        seen = (lo, hi, new)
        anchor = 0
        if not new:
            first = datetime.fromtimestamp(hours[lo], BERLIN)
            anchor = int(datetime(first.year, first.month, first.day,
                                  tzinfo=BERLIN).timestamp())
        bins = {}
        for k in range(hi - 1, lo - 1, -1):
            b = anchor + (hours[k] - anchor) // FOUR_H * FOUR_H
            if b not in bins:
                if len(bins) == KEEP:
                    break
                bins[b] = []
            bins[b].append(hours[k])
        for b, held in bins.items():
            content[b] = tuple(sorted(held))
    return content


def _uncovered(hours, stamps):
    """The hourly bars (epoch seconds) that no 4h bar opening at `stamps`
    covers."""
    out = []
    for h in hours:
        i = bisect.bisect_right(stamps, h) - 1
        if i < 0 or h >= stamps[i] + FOUR_H:
            out.append(h)
    return out


def _grid_runs(stamps):
    """The grids of a series, one entry per run of bars on one grid."""
    runs = []
    for t in stamps:
        if not runs or runs[-1] != t % FOUR_H:
            runs.append(t % FOUR_H)
    return runs


class TheOldFeedReplayedTests(_OnePeriodOneBar, TestCase):
    """DAX40 as the old feed left it: its window opened in summer
    (CEST's grid) from mid-October 2025 to mid-May 2026 and in winter
    (CET's grid) around them, and every grid change rewrote the last 200
    bars on the new grid; then the UTC grid's first window."""

    def setUp(self):
        from market_data.models import PriceData
        self.dax = _inst("DAX40")
        self.stamps = _replayed_rows()
        PriceData.objects.bulk_create([PriceData(
            instrument=self.dax, timeframe="4h",
            timestamp=datetime.fromtimestamp(t, UTC), open=100, high=101,
            low=99, close=100, volume=1, source="yfinance_public")
            for t in self.stamps])
        first, last = self.stamps[0], self.stamps[-1] + FOUR_H
        self.hours = [h for h in XETRA_HOURS if first <= h < last]

    def test_the_replay_holds_both_old_grids_beyond_the_new_window(self):
        stamps = self.stamps
        self.assertEqual({t % FOUR_H for t in stamps},
                         {0, 2 * 3600, 3 * 3600})
        self.assertEqual(_uncovered(self.hours, stamps), [])
        new_first = min(t for t in stamps if t % FOUR_H == 0)
        twins = [a for a, b in zip(stamps, stamps[1:])
                 if b - a <= 2 * 3600 and b < new_first - FOUR_H]
        self.assertGreater(len(twins), 300)

    def test_yes_leaves_one_bar_per_period_and_no_lost_hour(self):
        text = _run("--yes")
        self.assertIn("beside the UTC grid's", text)
        self.assertIn(f"on the {G2} grid beside the {G3} grid's", text)
        after = sorted(int(t.timestamp()) for t in _left(self.dax))
        self.assertOneBarPerPeriod(
            [datetime.fromtimestamp(t, UTC) for t in after])
        # One grid per run of sessions: CET's (the later anchor where the
        # bars around a stretch disagree, and the bars before the last
        # stretch), CEST's between, then the UTC grid.
        self.assertEqual(_grid_runs(after),
                         [3 * 3600, 2 * 3600, 3 * 3600, 0])
        # No hour of trading loses its bar, but where the grid changes: a
        # bar opening an hour after the one before it ended, at most once
        # per change.
        lost = _uncovered(self.hours, after)
        self.assertLessEqual(len(lost), len(_grid_runs(after)) - 1)
        for h in lost:
            i = bisect.bisect_right(after, h)
            self.assertNotEqual(after[i - 1] % FOUR_H, after[i] % FOUR_H,
                                datetime.fromtimestamp(h, UTC))
        # And only where the UTC grid begins (2026-11-01, on review): the
        # first rule, unchanged, deletes the old grids' bars beside its
        # first bar; the second rule changes grid between two sessions.
        new_first = min(t for t in after if t % FOUR_H == 0)
        for h in lost:
            self.assertTrue(new_first - FOUR_H <= h < new_first,
                            datetime.fromtimestamp(h, UTC))
        # Every trading day keeps its bars.
        self.assertEqual({datetime.fromtimestamp(t, UTC).date()
                          for t in after},
                         {datetime.fromtimestamp(t, UTC).date()
                          for t in self.stamps})
        self.assertEqual(_run(), EMPTY + "\n")


class TheOldFeedReplayedHourlyTests(_OnePeriodOneBar, TestCase):
    """DAX40 as the old feed left it at its own cadence (2026-11-01, on
    review), each bar holding what its last pass saw. A grid change then
    falls at any hour: the new grid's 200 bars start inside a session
    (2026-02-11 here: its 11:00 and 15:00 bars), and the stopped grid's
    newest bar may be short. The daily noon replay above is the one
    alignment where a new grid's 200 bars start a session whole (2 + 198
    = 66 x 3), which hid the hour the first cut lost at a grid's start."""

    def setUp(self):
        from market_data.models import PriceData
        self.dax = _inst("DAX40")
        self.content = _replayed_table()
        self.stamps = sorted(self.content)
        PriceData.objects.bulk_create([PriceData(
            instrument=self.dax, timeframe="4h",
            timestamp=datetime.fromtimestamp(t, UTC), open=100, high=101,
            low=99, close=100, volume=len(self.content[t]),
            source="yfinance_public") for t in self.stamps])
        first, last = self.stamps[0], self.stamps[-1] + FOUR_H
        self.hours = [h for h in XETRA_HOURS if first <= h < last]

    def _held(self, stamps):
        return {h for t in stamps for h in self.content[t]}

    def test_the_replay_holds_every_hour_on_both_old_grids(self):
        self.assertEqual({t % FOUR_H for t in self.stamps},
                         {0, 2 * 3600, 3 * 3600})
        held = self._held(self.stamps)
        self.assertEqual([h for h in self.hours if h not in held], [])
        # A new grid starting inside a session: 2026-02-11 holds CET's
        # 11:00 and 15:00 bars, not its 07:00.
        day = int(datetime(2026, 2, 11, tzinfo=UTC).timestamp())
        self.assertEqual(sorted((t - day) // 3600 for t in self.stamps
                                if day <= t < day + 86400
                                and t % FOUR_H == 3 * 3600), [11, 15])

    def test_no_hour_loses_the_bar_that_holds_it(self):
        from market_data.management.commands.prune_offgrid_4h import \
            offgrid_groups
        rule_of = {int(ts.timestamp()): g["rule"]
                   for g in offgrid_groups("DAX40")["DAX40"]
                   for _pk, ts, _s in g["rows"]}
        self.assertIn("pair", rule_of.values())
        _run("--yes")
        after = sorted(int(t.timestamp()) for t in _left(self.dax))
        held = self._held(after)
        lost = [h for h in self.hours if h not in held]
        # An hour is lost only where every bar holding it was beside the
        # UTC grid's first bar (the first rule, unchanged); never by the
        # second rule.
        for h in lost:
            holders = [t for t in self.stamps if h in self.content[t]]
            self.assertEqual({rule_of.get(t) for t in holders}, {"utc"},
                             datetime.fromtimestamp(h, UTC))
        self.assertOneBarPerPeriod(
            [datetime.fromtimestamp(t, UTC) for t in after])
        self.assertEqual(_grid_runs(after),
                         [3 * 3600, 2 * 3600, 3 * 3600, 0])
        self.assertEqual(_overlapping(self.dax), [])
        self.assertEqual(_run(), EMPTY + "\n")

    def test_after_an_earlier_run_of_the_first_rule(self):
        # The operator ran the first rule's clean-up after the update of
        # 2026-10-31: the old grids' bars beside the UTC grid's are gone,
        # and with them every old-grid bar after the last stretch. Those
        # grids ran into the UTC grid; they did not stop there, and no
        # session is left as it is.
        from market_data.management.commands.prune_offgrid_4h import \
            offgrid_groups
        from market_data.models import PriceData
        on = [t for t in self.stamps if t % FOUR_H == 0]

        def beside(t):
            i = bisect.bisect_left(on, t)
            return any(abs(u - t) < FOUR_H for u in on[max(0, i - 1):i + 1])

        cut = [t for t in self.stamps if t % FOUR_H and beside(t)]
        self.assertGreater(len(cut), 300)
        PriceData.objects.filter(instrument=self.dax, timestamp__in=[
            datetime.fromtimestamp(t, UTC) for t in cut]).delete()
        before = sorted(int(t.timestamp()) for t in _left(self.dax))
        groups = offgrid_groups("DAX40")["DAX40"]
        self.assertEqual({g["rule"] for g in groups}, {"pair"})
        _run("--yes")
        after = sorted(int(t.timestamp()) for t in _left(self.dax))
        self.assertEqual(sorted(self._held(before) - self._held(after)), [])
        self.assertOneBarPerPeriod(
            [datetime.fromtimestamp(t, UTC) for t in after])
        self.assertEqual(_overlapping(self.dax), [])
        self.assertEqual(_run(), EMPTY + "\n")
