"""The Power of Three (bot_program/power_of_three.py, 2026-10-03):
accumulation, manipulation, distribution — the day read by its sessions.

The operator: "include the consolidation, manipulation and distribution
often linked to the market sessions; very important". Asia consolidates,
London runs one side of that range to take the stops (the Judas swing),
New York leaves the other way. Pinned: the session clock, the day's
phase on constructed days, the words, the `po3` family the proving
ground judges, the positioning map carrying it, what it means for a buy
or a sell, the chart's Asian range and its card.

Run with:  python manage.py test tests.test_power_of_three
"""
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from django.test import SimpleTestCase, TestCase

from bot_program import power_of_three as P3
from tests.test_chart_signal_markers import NODE, _blocks, _node, widget, widget_source

#: 1h UTC bars in September 2026 (New York on daylight time): the Asian
#: session, 20:00 to midnight New York, is 00:00 to 04:00 UTC; London
#: 02:00-05:00 NY is 06:00-09:00 UTC; the NY AM session opens 12:30 UTC.
LONDON = pd.Timestamp("2026-09-15 07:00", tz="UTC")
NY_AM = pd.Timestamp("2026-09-15 13:00", tz="UTC")
OFF = pd.Timestamp("2026-09-15 09:30", tz="UTC")
ASIA = pd.Timestamp("2026-09-15 01:00", tz="UTC")


def day_frame(*, run="low", back=True, both=False, end_hour=23, days=2):
    """Flat at 100 with an Asian range 99.5-100.5. On the last day, London
    (07:00-08:00 UTC) runs the lows (or the highs); `back` closes the
    second bar back inside; `both` runs the other side first; `end_hour`
    cuts the day."""
    idx = pd.date_range("2026-09-14 00:00", periods=24 * days, freq="1h",
                        tz="UTC")
    idx = [ts for ts in idx
           if not (ts.date() == idx[-1].date() and ts.hour > end_hour)]
    rows = []
    for ts in idx:
        h, last = ts.hour, ts.date() == idx[-1].date()
        hi, lo, c = 100.5, 99.5, 100.0
        if last and run == "low" and h in (7, 8):
            lo = 98.8
            c = 99.2 if h == 7 else (100.1 if back else 99.3)
        if last and run == "high" and h in (7, 8):
            hi = 101.2
            c = 100.8 if h == 7 else (99.9 if back else 100.7)
        if last and both and h == 7:
            hi = 101.3                         # the other side, the same bar
        rows.append({"open": 100.0, "high": hi, "low": lo, "close": c,
                     "volume": 1.0})
    return pd.DataFrame(rows, index=pd.DatetimeIndex(idx))


class TheSessionClockTests(SimpleTestCase):

    def test_the_sessions_are_new_york_anchored(self):
        self.assertEqual(P3.session_now(LONDON), "london")
        self.assertEqual(P3.session_now(NY_AM), "ny_am")
        self.assertEqual(P3.session_now(ASIA), "asia")
        self.assertEqual(P3.session_now(OFF), "off")


class TheDayTests(SimpleTestCase):

    def test_london_runs_the_lows_and_comes_back_the_distribution_points_up(self):
        d = P3.read_day(day_frame(), [], now=OFF)
        self.assertTrue(d["ok"])
        self.assertEqual((d["phase"], d["direction"]), ("distribution", "up"))
        # the session's span rides along (2026-10-07): 00:00 and 04:00 UTC
        # on 2026-09-15, the New York evening of the 14th
        self.assertEqual(d["asia"], {"high": 100.5, "low": 99.5,
                                     "date": "2026-09-14",
                                     "opened": 1789430400,
                                     "closed": 1789444800})
        self.assertEqual(d["run"], {"below": True, "above": False,
                                    "low": 98.8, "high": None})
        self.assertIn("the lows of the Asian range were run (98.8)", d["why"])
        self.assertIn("the distribution points up", d["why"])

    def test_the_highs_run_and_back_points_down(self):
        d = P3.read_day(day_frame(run="high"), [], now=OFF)
        self.assertEqual((d["phase"], d["direction"]), ("distribution", "down"))

    def test_a_run_that_holds_is_the_manipulation_or_a_break(self):
        d = P3.read_day(day_frame(back=False, end_hour=8), [], now=OFF)
        self.assertEqual((d["phase"], d["direction"]), ("manipulation", None))
        self.assertIn("a close back inside tells", d["why"])

    def test_inside_the_range_is_accumulation(self):
        d = P3.read_day(day_frame(run="none", end_hour=5), [], now=OFF)
        self.assertEqual(d["phase"], "accumulation")
        self.assertIn("nothing has run either side", d["why"])

    def test_both_sides_run_is_no_clean_day(self):
        d = P3.read_day(day_frame(both=True), [], now=OFF)
        self.assertEqual(d["phase"], "unclear")

    def test_no_range_today_and_too_few_bars_are_unread(self):
        late = pd.Timestamp("2026-09-20 12:00", tz="UTC")
        d = P3.read_day(day_frame(), [], now=late)
        self.assertEqual(d["phase"], "unread")
        self.assertIn("no Asian range", d["why"])
        d = P3.read_day(day_frame().iloc[:5], [], now=OFF)
        self.assertIn("too few bars", d["why"])

    def test_the_words_name_the_session_and_its_part(self):
        d = P3.read_day(day_frame(), [], now=LONDON)
        words = P3.words_for(d)
        self.assertTrue(words.startswith(
            "Power of Three (the london session, the day's manipulation): "
            "Asia consolidated 99.5–100.5;"), words)
        d = P3.read_day(day_frame(), [], now=OFF)
        self.assertIn("(between sessions)", P3.words_for(d))
        self.assertIn("Power of Three unread", P3.words_for({"ok": False,
                                                              "why": "x"}))


class TheSessionSpanTests(SimpleTestCase):
    """The Asian range's own bars (2026-10-07): the chart draws the
    accumulation as a box over its session, so the read says when the
    session's first bar opened and its last bar closed."""

    def test_the_asian_range_carries_its_session_bars(self):
        a = P3.read_day(day_frame(), [], now=OFF)["asia"]
        self.assertIsInstance(a["opened"], int)
        self.assertIsInstance(a["closed"], int)
        # four 1h bars, 20:00 to midnight New York: the last one closes
        # an hour after it opens
        self.assertEqual(a["closed"] - a["opened"], 4 * 3600)

    def test_a_frame_without_times_keeps_the_two_prices(self):
        rng = P3.asian_range(day_frame(), now=OFF)
        self.assertEqual(P3._span(day_frame().reset_index(drop=True), rng), {})
        # an unreadable span costs the read nothing: the high, the low and
        # the date stay, and nothing else is guessed
        with patch.object(P3, "_span", return_value={}):
            d = P3.read_day(day_frame(), [], now=OFF)
        self.assertEqual(d["asia"], {"high": 100.5, "low": 99.5,
                                     "date": "2026-09-14"})
        self.assertEqual((d["phase"], d["direction"]), ("distribution", "up"))


class TheFamilyTests(SimpleTestCase):

    def test_the_first_bar_back_inside_after_one_side_was_run_fires(self):
        from backtester.proving import families as F
        df = day_frame()
        long_f = F.FAMILIES["po3"].fires(df, F.LONG, timeframe="1h")
        self.assertEqual(list(np.flatnonzero(long_f)), [32])   # 08:00 UTC day 2
        self.assertEqual(F.FAMILIES["po3"].fires(df, F.SHORT, timeframe="1h").sum(), 0)
        short_f = F.FAMILIES["po3"].fires(day_frame(run="high"), F.SHORT,
                                          timeframe="1h")
        self.assertEqual(list(np.flatnonzero(short_f)), [32])

    def test_both_sides_run_before_the_close_back_never_fires(self):
        from backtester.proving import families as F
        df = day_frame(both=True)
        self.assertEqual(F.FAMILIES["po3"].fires(df, F.LONG, timeframe="1h").sum(), 0)
        self.assertEqual(F.FAMILIES["po3"].fires(df, F.SHORT, timeframe="1h").sum(), 0)

    def test_it_is_registered_for_the_generator(self):
        from backtester.proving import families as F
        fam = F.FAMILIES["po3"]
        self.assertEqual(fam.live_rules, {})
        self.assertEqual(fam.defaults, {"session": "asia"})


class TheMapTests(TestCase):

    def test_the_map_carries_the_day_and_says_it(self):
        from bot_program import positioning as P
        from tests.test_positioning import _seed, _tape
        _seed("PO3MAP", _tape(), asset_class="forex")
        canned = {"ok": True, "phase": "distribution", "direction": "up",
                  "session": "ny_am", "asia": {"high": 100.5, "low": 99.5,
                                               "date": "2026-10-02"},
                  "run": {"below": True, "above": False, "low": 98.8,
                          "high": None}, "judas": None, "timeframe": "1h",
                  "why": "x", "words": "Power of Three (the ny am session, "
                                       "the day's distribution): x."}
        with patch("bot_program.power_of_three.power_of_three",
                   return_value=canned):
            pm = P.positioning_map("PO3MAP", asset_class="forex",
                                   direction="BUY")
        self.assertEqual(pm["po3"]["phase"], "distribution")
        self.assertEqual(pm["po3"]["asia"]["high"], 100.5)
        self.assertEqual(pm["po3"]["odds"]["verdict"], "unjudged")
        self.assertIn("--families po3 --timeframe 1h", pm["po3"]["odds"]["why"])
        self.assertIn("Power of Three (the ny am session", pm["words"])
        self.assertIn("The day's distribution", pm["words"])
        self.assertIn("The day's distribution is with you", pm["side"]["words"])
        c = P.compact(pm)
        self.assertEqual(c["po3"]["direction"], "up")

    def test_what_the_day_means_for_each_side(self):
        from bot_program import positioning as P
        from tests.test_positioning import _canned_map
        pm = _canned_map(po3={"phase": "distribution", "direction": "up"})
        self.assertIn("is with you", P.side_read(pm, "BUY")["words"])
        self.assertIn("points against you", P.side_read(pm, "SELL")["words"])
        pm = _canned_map(po3={"phase": "accumulation", "direction": None})
        self.assertIn("still accumulating", P.side_read(pm, "BUY")["words"])
        pm = _canned_map(po3={"phase": "manipulation", "direction": None})
        self.assertIn("a close back inside tells", P.side_read(pm, "SELL")["words"])
        pm = _canned_map(po3={"phase": "unread", "direction": None})
        self.assertNotIn("day", P.side_read(pm, "BUY")["words"])

    def test_the_command_prints_the_day(self):
        from io import StringIO

        from django.core.management import call_command

        from tests.test_positioning import _seed, _tape
        _seed("PO3CMD", _tape(), asset_class="forex")
        out = StringIO()
        call_command("positioning", "PO3CMD", stdout=out)
        text = out.getvalue()
        self.assertIn("day: ", text)
        self.assertIn("Power of Three", text)


PURE_RUN = r"""
var H = window.svHoverCards;
var out = {};
out.card = H.levelCard({price: 100.5, text: '100.50000', kind: 'Asian range high',
    side: 'above', pool: false,
    po3: {high: 100.5, low: 99.5, phase: 'distribution', direction: 'up',
          words: "Power of Three (the london session, the day's manipulation): x."}}, null);
process.stdout.write(JSON.stringify(out));
"""


class TheChartTests(SimpleTestCase):

    def test_the_asian_range_is_drawn_with_the_levels_and_hovered(self):
        src = widget_source()
        self.assertIn("function applyAsianRange(po3) {", src)
        # the box over the session's own bars (2026-10-07); without
        # primitives the two faint untitled lines are the fallback (a title
        # without its axis label is never painted)
        self.assertIn("layer.set({ asia: { high: a.high", src)
        self.assertIn("LightweightCharts.LineStyle.LargeDashed", src)
        i = src.find("function applyOverlays(bars) {")
        self.assertIn("applyAsianRange(POSMAP ? POSMAP.po3 : null);", src[i:i + 500])
        died = src.find("posLines = []; /* they died with the series */")
        self.assertIn("amdLines = [];", src[died:died + 160])
        j = src.find("function lineHit(param) {")
        self.assertIn("kind: 'Asian range high'", src[j:j + 2500])
        self.assertIn("if (!mainSeries || !activeInds.levels || !po3", src)

    @unittest.skipUnless(NODE, "node is not installed")
    def test_the_range_s_card_says_the_phase(self):
        pure, _main = _blocks(widget())
        out = _node("var window = {};\n" + pure + "\n" + PURE_RUN)
        html = out["card"]
        self.assertIn('<span class="sv-sig-side">RANGE</span>', html)
        self.assertIn('<span class="sv-sig-rule">Asian range high</span>', html)
        self.assertIn("<dt>Day</dt><dd>distribution, pointing up</dd>", html)
        self.assertIn("The accumulation: the stops build on both sides", html)
        self.assertIn("Power of Three (the london session", html)
        self.assertIn("Asia 20:00 to midnight New York", html)
        self.assertNotIn("Recomputed every minute", html)
