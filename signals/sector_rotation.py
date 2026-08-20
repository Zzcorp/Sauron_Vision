"""Sector rotation model — track money flow between sectors.

Which sectors led over a window, which are picking up pace, and what rotation
that ordering suggests. This is a read-only dashboard model: nothing here
writes a Signal. The tradeable form of the same idea is the
`cross_sectional_rank` evaluator in `signals.opportunity_scanner`, and both
measure a window through the SAME primitive (`window_return`), so a sector
ranking and an instrument ranking cannot end up disagreeing about what a
return is or about which windows are too thin to have one.

Four things this file has to be careful about.

`now` is pinned by the caller, never read from the clock mid-computation.
Every query is upper-bounded by that instant, so replaying an old day sees the
bars that existed on that day. The reads used to be unbounded, which is a
no-op while the caller is the live dashboard and lookahead the moment anything
else asks.

A sector with nothing measurable in it is ABSENT from the result, never zero.
A zero sorts into the middle of the leaders table and reads as "flat" — a
claim about a sector nobody measured.

Leaders and laggards are disjoint or they are not published. Taking the top
three and the bottom three of a five-sector table names the middle sector as
both, and the rotation it then suggests is out of a sector and into itself.

The two windows the momentum read compares have to be comparable in both of
the ways a comparison can go wrong. In UNITS: each side is a per-BAR log pace
taken from the member's own bar count, because a five-day window and a
thirty-day one hold different numbers of bars per calendar day, so dividing by
the calendar length leaves exactly the window-length dependence the division
was meant to remove. And in MEMBERSHIP: both sides are averaged over the
members measured in BOTH windows, because a mean over whoever happened to be
measurable in each is two different sectors wearing one name.

Caveat worth knowing before reading a chart off this: every read is gated on
`Instrument.sector`, and `instruments.services.INSTRUMENTS_DATA` does not
populate that column — so on a platform seeded from it `analyze()` answers
`no_sector_data` rather than drawing an empty rotation.
"""
import logging
import math
import statistics
from collections import defaultdict
from datetime import timedelta

logger = logging.getLogger(__name__)


# A sector mean taken over fewer members than this is one or two stocks wearing
# a sector's name, and the whole rotation thesis is about capital moving
# between GROUPS. Three is the smallest count in which a single outlier is
# outvoted rather than decisive. Sectors under it are still REPORTED — the
# reader can see the member count and judge — but they are kept out of the
# leaders, laggards and suggestions, which are the outputs someone acts on.
MIN_SECTOR_MEMBERS = 3

# One trading week: short enough that a move in it is news rather than trend,
# long enough that a single gap does not define it.
SHORT_WINDOW_DAYS = 5

# The most sectors named on either end of the table. Ten GICS sectors split
# three-and-three leaves four in the middle, which is the point — a leader is
# only a leader relative to something it is beating.
ROTATION_SLICE = 3

# Below this many ranked sectors the direction read is not a read: it asks
# whether two of the TOP THREE belong to a risk group, and with three or fewer
# sectors on the table the top three IS the table, so every answer is
# "whatever we happen to cover" rather than "where the money went".
MIN_SECTORS_FOR_DIRECTION = 4


class SectorRotationModel:
    """Track and predict sector rotation patterns."""

    # Typical business cycle sector order
    CYCLE_ORDER = [
        'Technology', 'Consumer Discretionary', 'Industrials',
        'Materials', 'Energy', 'Financial Services',
        'Consumer Staples', 'Healthcare', 'Utilities', 'Real Estate',
    ]

    def analyze(self, lookback_days=30, now=None):
        """Analyze sector rotation as of `now` (default: the live clock).

        Returns dict with:
            sector_performance: {sector: return_pct} for every MEASURED sector
            sector_members: {sector: count of members that could be measured}
            rotation_direction: str (risk_on, risk_off, late_cycle, ...)
            leading_sectors / lagging_sectors: disjoint lists, possibly empty
            momentum: {sector: accelerating|decelerating|reversing_*|stable}
            suggested rotations
        """
        from django.utils import timezone

        now = now or timezone.now()
        members = self._sector_members()
        if not members:
            # Distinguished from "measured nothing": the column is empty, which
            # is a configuration fact an operator can act on, not a quiet market.
            return {'error': 'no_sector_data',
                    'detail': 'no active stock carries a sector label',
                    'lookback_days': lookback_days,
                    'as_of': now.isoformat()}

        long_returns = self._member_returns(members, lookback_days, now)
        short_days = min(lookback_days, SHORT_WINDOW_DAYS)
        # A caller asking for a five-day view would otherwise run the identical
        # query twice and compare a window with itself.
        short_returns = (long_returns if short_days == lookback_days
                         else self._member_returns(members, short_days, now))

        stats = self._sector_stats(members, long_returns)
        if not stats:
            return {'error': 'insufficient sector data',
                    'detail': (f'no sector has a member with {lookback_days} days '
                               f'of price history on or before {now:%Y-%m-%d}'),
                    'lookback_days': lookback_days,
                    'as_of': now.isoformat()}

        representative = {sector: values['return']
                          for sector, values in stats.items()
                          if values['members'] >= MIN_SECTOR_MEMBERS}
        ordered = sorted(representative.items(), key=lambda kv: kv[1], reverse=True)

        # Half the table at most on each end, so the two slices never overlap.
        # `ordered[-k:]` would be the whole list at k=0, hence the explicit index.
        k = min(ROTATION_SLICE, len(ordered) // 2)
        leading = [sector for sector, _ in ordered[:k]]
        lagging = [sector for sector, _ in ordered[len(ordered) - k:]]

        # The pace comparison runs over the members measured in BOTH windows.
        # A member with thirty days of history and nothing in the last five —
        # a halted stock, a feed that stopped on Tuesday — belongs to one
        # window's mean and not the other's, so comparing those two means
        # compares two differently composed sectors that happen to share a
        # name. The published performance table is untouched by this: it is a
        # single-window measurement and has nothing to be paired against.
        paired = set(short_returns) & set(long_returns)
        momentum = self._momentum_analysis(
            self._sector_stats(members, {i: short_returns[i] for i in paired}),
            self._sector_stats(members, {i: long_returns[i] for i in paired}))

        return {
            'sector_performance': {sector: round(values['return'], 4)
                                   for sector, values in stats.items()},
            'sector_members': {sector: values['members']
                               for sector, values in stats.items()},
            'rotation_direction': self._detect_direction(ordered),
            'leading_sectors': leading,
            'lagging_sectors': lagging,
            'momentum': momentum,
            'suggestions': self._suggest_rotation(ordered, momentum, k),
            'lookback_days': lookback_days,
            'as_of': now.isoformat(),
        }

    def _sector_members(self):
        """{sector: [instrument, ...]} for active, sector-labelled stocks."""
        from instruments.models import Instrument

        out = defaultdict(list)
        rows = (Instrument.objects
                .filter(is_active=True, asset_class='stock', sector__isnull=False)
                .exclude(sector=''))
        for instrument in rows:
            out[instrument.sector].append(instrument)
        return dict(out)

    def _member_returns(self, members, lookback_days, now):
        """{instrument_id: {'return': r, 'pace': per-bar log return}} over the
        window ending at `now`.

        One query for every sector at once — the old shape ran one per
        instrument and then ran the whole thing twice more for the momentum
        comparison, so a ten-sector board cost hundreds of round trips per page
        load.

        The pace is measured HERE, against the member's own bar count, because
        this is the only place that count exists. Dividing the finished return
        by the window's calendar length instead reads a five-day window as
        five bars and a thirty-day one as thirty, when a five-day window holds
        three or four bars and a thirty-day one holds about twenty-one — so the
        two paces come out in different units and the comparison stays
        window-length dependent, which is the whole thing dividing by the
        window was for.

        Log returns, because they add across bars: one divided by its bar count
        is a true per-bar pace, and a tape advancing the same percentage every
        bar reads identically in both windows. A simple return compounds, so
        `((1+r)**n - 1) / n` grows with `n` all by itself and a steady tape
        would still score as decelerating.

        An instrument whose window holds fewer than two bars is ABSENT from the
        result rather than counted at zero, which is what keeps a sector's mean
        an average of the members that moved rather than of the members that
        have a row in the instrument table. A window ending at or below zero is
        absent for the same reason, and return and pace always leave together:
        a member present in one of a sector's two means and not the other is
        the same defect one level down.
        """
        from market_data.models import PriceData
        from signals.opportunity_scanner import window_return

        ids = [instrument.id
               for group in members.values() for instrument in group]
        if not ids:
            return {}
        cutoff = now - timedelta(days=lookback_days)
        rows = (PriceData.objects
                .filter(instrument_id__in=ids, timeframe='1d',
                        timestamp__gte=cutoff, timestamp__lte=now)
                .order_by('instrument_id', 'timestamp')
                .values_list('instrument_id', 'close'))
        series = {}
        for instrument_id, close in rows.iterator():
            series.setdefault(instrument_id, []).append(float(close))

        out = {}
        for instrument_id, closes in series.items():
            value = window_return(closes)
            if value is None or 1.0 + value <= 0.0:
                continue
            out[instrument_id] = {
                'return': value,
                'pace': math.log(1.0 + value) / (len(closes) - 1),
            }
        return out

    def _sector_stats(self, members, returns):
        """{sector: {'return': mean, 'pace': mean, 'members': n}} over MEASURED
        members only.

        The member count travels with the mean because the two are read
        together: "Energy +4%" means something different across eleven names
        than across one, and the caller cannot tell them apart from the mean.

        The sector's pace is the mean of its members' paces, not its mean
        return divided by something. Members do not all hold the same number of
        bars in the same window — one listed halfway through it, another's feed
        skipped a week — so a single divisor would price every one of them at
        whichever bar count the window nominally has.
        """
        out = {}
        for sector, group in members.items():
            measured = [returns[instrument.id] for instrument in group
                        if instrument.id in returns]
            if not measured:
                continue
            out[sector] = {
                'return': statistics.fmean(m['return'] for m in measured),
                'pace': statistics.fmean(m['pace'] for m in measured),
                'members': len(measured),
            }
        return out

    def _detect_direction(self, ordered):
        """Detect rotation direction from which groups lead the table."""
        if len(ordered) < MIN_SECTORS_FOR_DIRECTION:
            return 'unknown'

        top_sectors = set(sector for sector, _ in ordered[:ROTATION_SLICE])

        risk_on = {'Technology', 'Consumer Discretionary', 'Industrials', 'Financial Services'}
        risk_off = {'Consumer Staples', 'Healthcare', 'Utilities', 'Real Estate'}
        late_cycle = {'Energy', 'Materials', 'Industrials'}

        on_count = len(top_sectors & risk_on)
        off_count = len(top_sectors & risk_off)
        late_count = len(top_sectors & late_cycle)

        if on_count >= 2:
            return 'risk_on'
        elif off_count >= 2:
            return 'risk_off'
        elif late_count >= 2:
            return 'late_cycle'
        else:
            return 'transitioning'

    def _momentum_analysis(self, short_stats, long_stats):
        """Compare the recent PACE of each sector with its whole-window pace.

        Both sides arrive as per-BAR log paces, built by `_member_returns` from
        each member's own bar count. The comparison used to be between the two
        windows' TOTAL returns, which the longer window wins by construction in
        any trend: a sector running +0.4% a day for five days read as
        `decelerating` against its own +0.3%-a-day thirty-day figure — the exact
        sectors a rotation model exists to spot were the ones it labelled as
        fading. Dividing each total by its window's CALENDAR length was half a
        fix and looked like a whole one: the two windows do not hold the same
        number of bars per calendar day, so the ratios were still measured in
        different units and the answer still moved with the window length.

        The two sides also have to be the same sector. `_sector_stats` averages
        whichever members it could measure, so `analyze` narrows both windows
        to the members measured in BOTH before they get here.

        The reversal branches are also reachable now. Tested after the
        accelerating/decelerating pair, `short > 0 > long` always matched
        `short > long and short > 0` first, so `reversing_up` and
        `reversing_down` were labels the function could never return.

        A sector measured in only one of the two windows is absent from the
        result: there is no pace to compare it against.
        """
        momentum = {}
        for sector in set(short_stats) | set(long_stats):
            short = short_stats.get(sector)
            long = long_stats.get(sector)
            if short is None or long is None:
                continue

            short_pace = short['pace']
            long_pace = long['pace']

            if short_pace > 0 and long_pace < 0:
                momentum[sector] = 'reversing_up'
            elif short_pace < 0 and long_pace > 0:
                momentum[sector] = 'reversing_down'
            elif short_pace > long_pace and short_pace > 0:
                momentum[sector] = 'accelerating'
            elif short_pace < long_pace and long_pace > 0:
                momentum[sector] = 'decelerating'
            else:
                momentum[sector] = 'stable'

        return momentum

    def _suggest_rotation(self, ordered, momentum, k):
        """Suggest sector rotation trades from the two disjoint ends."""
        suggestions = []

        for sector, ret in ordered[:k]:
            state = momentum.get(sector)
            # Into what is leading AND still gaining pace. A leader that is
            # decelerating is the one already priced in.
            if state in ('accelerating', 'reversing_up'):
                suggestions.append({
                    'action': 'overweight',
                    'sector': sector,
                    'reason': f"Leading sector, {state} ({ret*100:+.1f}%)",
                })

        for sector, ret in ordered[len(ordered) - k:]:
            state = momentum.get(sector)
            if state in ('decelerating', 'reversing_down'):
                suggestions.append({
                    'action': 'underweight',
                    'sector': sector,
                    'reason': f"Lagging sector, {state} ({ret*100:+.1f}%)",
                })

        return suggestions
