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
import copy
import json
import unittest
from datetime import date, datetime, time as dtime, timedelta
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


def ny_day_frame(ny_day, *, run="low"):
    """24/7 1h UTC bars from 00:00 New York two days before `ny_day` to
    12:00 New York on it: flat at 100, the Asian range 99.5-100.5 (every
    bar), and on `ny_day` the bars opening at 03:00 and 04:00 New York run
    the lows to 98.8 (or the highs to 101.2), the second closing back inside.
    Built by New York wall clock, so the UTC stamps follow the season."""
    from zoneinfo import ZoneInfo
    ny = ZoneInfo("America/New_York")
    start = pd.Timestamp(datetime.combine(ny_day - timedelta(days=2), dtime(0, 0),
                                          tzinfo=ny)).tz_convert("UTC")
    end = pd.Timestamp(datetime.combine(ny_day, dtime(12, 0), tzinfo=ny)).tz_convert("UTC")
    idx = pd.date_range(start, end, freq="1h")
    rows = []
    for ts in idx:
        local = ts.tz_convert(ny)
        hi, lo, c = 100.5, 99.5, 100.0
        if local.date() == ny_day and local.hour in (3, 4):
            if run == "low":
                lo, c = 98.8, (99.2 if local.hour == 3 else 100.1)
            else:
                hi, c = 101.2, (100.8 if local.hour == 3 else 99.9)
        rows.append({"open": 100.0, "high": hi, "low": lo, "close": c, "volume": 1.0})
    return pd.DataFrame(rows, index=idx), end


def judas_frame():
    """The F1 probe's day (po3chart/probe/judas_date.py): today's London
    (2026-09-15, 06:00-08:00 UTC) fakes up to 101.0 and turns down; the
    London of the day before fakes down to 99.0 and turns up."""
    idx = pd.date_range("2026-09-10 00:00", periods=24 * 6, freq="1h", tz="UTC")
    df = pd.DataFrame([dict(open=100.0, high=100.3, low=99.7, close=100.0, volume=1.0)
                       for _ in idx], index=idx)
    for t, v in {"2026-09-15 06:00": (100.0, 101.0, 99.9, 100.8),
                 "2026-09-15 07:00": (100.8, 100.9, 99.0, 99.1),
                 "2026-09-15 08:00": (99.1, 99.4, 98.9, 99.2),
                 "2026-09-14 06:00": (100.0, 99.95, 99.0, 99.2),
                 "2026-09-14 07:00": (99.2, 101.2, 99.1, 101.0),
                 "2026-09-14 08:00": (101.0, 101.1, 100.6, 100.9)}.items():
        df.loc[pd.Timestamp(t, tz="UTC"), ["open", "high", "low", "close"]] = v
    df = df[df.index <= pd.Timestamp("2026-09-15 09:00", tz="UTC")]
    swings = [{"type": "L", "idx": 10, "price": 95.0}, {"type": "H", "idx": 12, "price": 105.0}]
    return df, swings


#: What read_day(day_frame(), [], now=OFF) carries for the chart
#: (2026-10-08): the trading day's London and New York windows by the
#: sessions table, the run of the Asian lows with its bar and its return.
STAGES = {"date": "2026-09-15", "bar": 3600,
          "london": {"opened": 1789452000, "closed": 1789462800, "state": "closed",
                     "ny": "02:00–05:00"},
          "new_york": {"opened": 1789475400, "closed": 1789502400, "state": "upcoming",
                       "ny": "08:30–16:00"},
          "sweeps": [{"side": "low", "edge": 99.5, "price": 98.8, "at": 1789455600,
                      "ny": "03:00", "session": "london", "back_at": 1789459200,
                      "back_close_at": 1789462800, "back_price": 100.1, "back_ny": "04:00"}],
          "judas": None}
OLD_KEYS = ("ok", "phase", "direction", "session", "asia", "run", "mark", "judas", "why")


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


class TheStagesTests(SimpleTestCase):
    """The three stages on the chart (2026-10-08). The operator: "I only
    have the Asia session noted on the chart, not the 3 stages of
    manipulation, accumulation and distribution." read_day gains ONE key,
    `stages`, for the chart to draw: the trading day's London and New York
    windows by the sessions table, each run of an Asian edge with its bar
    and its return, and the trading day's Judas swing with its bar times.
    Every other key keeps its value."""

    def _without_stages(self, df, swings, now):
        with patch.object(P3, "_stages_or_none", return_value=None):
            return P3.read_day(df, swings, now=now)

    # S1
    def test_the_stages_ride_along_and_the_old_keys_keep_their_values(self):
        d = P3.read_day(day_frame(), [], now=OFF)
        self.assertEqual(d["stages"], STAGES)
        bare = self._without_stages(day_frame(), [], OFF)
        self.assertIsNone(bare["stages"])
        for k in OLD_KEYS:
            self.assertEqual(d[k], bare[k], k)
        self.assertEqual((d["phase"], d["direction"]), ("distribution", "up"))

    # S2
    def test_a_run_still_holding_has_no_return(self):
        now = pd.Timestamp("2026-09-15 08:30", tz="UTC")
        d = P3.read_day(day_frame(back=False, end_hour=8), [], now=now)
        self.assertEqual(d["phase"], "manipulation")
        self.assertEqual(d["stages"]["sweeps"], [
            {"side": "low", "edge": 99.5, "price": 98.8, "at": 1789455600, "ny": "03:00",
             "session": "london", "back_at": None, "back_close_at": None, "back_price": None,
             "back_ny": None}])
        self.assertEqual(d["stages"]["london"]["state"], "open")
        self.assertEqual(d["stages"]["new_york"]["state"], "upcoming")

    # S3
    def test_the_highs_swept_mirror(self):
        d = P3.read_day(day_frame(run="high"), [], now=OFF)
        self.assertEqual((d["phase"], d["direction"]), ("distribution", "down"))
        self.assertEqual(d["stages"]["sweeps"], [
            {"side": "high", "edge": 100.5, "price": 101.2, "at": 1789455600, "ny": "03:00",
             "session": "london", "back_at": 1789459200, "back_close_at": 1789462800,
             "back_price": 99.9, "back_ny": "04:00"}])

    # S4
    def test_both_sides_run_lists_both_in_time_order(self):
        d = P3.read_day(day_frame(both=True), [], now=OFF)
        self.assertEqual(d["phase"], "unclear")
        got = [(s["side"], s["price"], s["at"], s["back_at"], s["back_close_at"], s["back_price"])
               for s in d["stages"]["sweeps"]]
        # the low first on a bar that ran both: its high came back at its own close
        self.assertEqual(got, [("low", 98.8, 1789455600, 1789459200, 1789462800, 100.1),
                               ("high", 101.3, 1789455600, 1789455600, 1789459200, 99.2)])

    # S5
    def test_inside_the_range_has_no_run(self):
        now = pd.Timestamp("2026-09-15 05:30", tz="UTC")
        d = P3.read_day(day_frame(run="none", end_hour=5), [], now=now)
        self.assertEqual(d["phase"], "accumulation")
        st = d["stages"]
        self.assertEqual(st["sweeps"], [])
        self.assertIsNone(st["judas"])
        self.assertEqual((st["london"]["state"], st["new_york"]["state"]),
                         ("upcoming", "upcoming"))
        self.assertEqual(st["date"], "2026-09-15")

    # S6
    def test_the_windows_are_new_york_anchored_through_the_year(self):
        cases = [
            # summer (EDT): London 06:00-09:00 UTC, New York 12:30-20:00
            (date(2026, 9, 15), (1789452000, 1789462800), (1789475400, 1789502400), 7),
            # winter (EST): an hour later in UTC
            (date(2026, 11, 3), (1793689200, 1793700000), (1793712600, 1793739600), 8),
            # the US on EDT, the UK still on GMT: the killzone follows New
            # York (06:00 UTC), not London's own 08:00
            (date(2026, 3, 16), (1773640800, 1773651600), (1773664200, 1773691200), 7),
            # the spring-forward Sunday: 02:00 does not exist, London opens
            # at 03:00 EDT (07:00 UTC) and lasts two hours
            (date(2026, 3, 8), (1772953200, 1772960400), (1772973000, 1773000000), 7),
        ]
        for day, london, new_york, utc_hour in cases:
            df, now = ny_day_frame(day)
            d = P3.read_day(df, [], now=now)
            st = d["stages"]
            self.assertEqual(st["date"], day.isoformat(), day)
            self.assertEqual((st["london"]["opened"], st["london"]["closed"]), london, day)
            self.assertEqual((st["new_york"]["opened"], st["new_york"]["closed"]), new_york, day)
            self.assertEqual(st["london"]["ny"], "02:00–05:00")
            self.assertEqual(st["new_york"]["ny"], "08:30–16:00")
            self.assertEqual(len(st["sweeps"]), 1, day)
            s = st["sweeps"][0]
            self.assertEqual(s["ny"], "03:00", day)
            at = pd.Timestamp(datetime.combine(day, dtime(utc_hour, 0)), tz="UTC")
            self.assertEqual(s["at"], int(at.timestamp()), day)
            self.assertEqual(s["back_ny"], "04:00", day)
            self.assertEqual(s["session"], "london", day)
        self.assertEqual(london[1] - london[0], 2 * 3600, "two hours on the short night")

    # S7
    def test_the_four_hour_read(self):
        df = day_frame()
        g = df.resample("4h", origin="epoch", label="left", closed="left")
        df4 = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(),
                            "low": g["low"].min(), "close": g["close"].last(),
                            "volume": g["volume"].sum()}).dropna()
        self.assertEqual(len(df4), 12)
        d = P3.read_day(df4, [], now=OFF)
        st = d["stages"]
        self.assertEqual(st["bar"], 14400)
        s = st["sweeps"][0]
        # One 4h bar spans the sessions (2026-10-15): the run is said as its
        # bar's span on the New York clock and the first session the bar
        # overlaps (London, where the 07:00 UTC extreme printed), not the
        # clock at the bar's open ('00:00', 'off'); the return by the bar's
        # close (12:00 UTC, 08:00 New York), where that close printed.
        self.assertEqual((s["side"], s["at"], s["ny"], s["session"]),
                         ("low", 1789444800, "00:00–04:00", "london"))
        self.assertEqual((s["back_at"], s["back_close_at"], s["back_price"], s["back_ny"]),
                         (1789459200, 1789473600, 100.0, "08:00"))
        # the 1h read keeps the clock at the bar: STAGES, byte for byte
        self.assertEqual(P3.read_day(df, [], now=OFF)["stages"]["sweeps"], STAGES["sweeps"])

    # S7b
    def test_a_wide_bar_s_session_is_the_first_it_overlaps(self):
        """A 4h bar from midnight New York overlaps London alone (Asia ended
        as it opened); one from 20:00 New York is Asia's; a 2h bar at
        05:00-07:00 New York overlaps no session; 09:00 UTC + 4h reaches
        New York AM at 08:30."""
        self.assertEqual(P3._bar_session(pd.Timestamp("2026-09-15 04:00", tz="UTC"), 14400), "london")
        self.assertEqual(P3._bar_session(pd.Timestamp("2026-09-15 00:00", tz="UTC"), 14400), "asia")
        self.assertEqual(P3._bar_session(pd.Timestamp("2026-09-15 09:00", tz="UTC"), 7200), "off")
        self.assertEqual(P3._bar_session(pd.Timestamp("2026-09-15 09:00", tz="UTC"), 14400), "ny_am")
        self.assertEqual(P3._ny_span(pd.Timestamp("2026-09-15 04:00", tz="UTC"), 14400), "00:00–04:00")
        with patch("signals.smc.sessions.new_york_timezone", return_value=None):
            self.assertEqual(P3._bar_session(OFF, 14400), "unknown")
            self.assertIsNone(P3._ny_span(OFF, 14400))

    # S8
    def test_the_stages_judas_is_the_trading_day_s_london(self):
        from signals.smc.session_setups import detect_judas_swings
        df, swings = judas_frame()
        now = pd.Timestamp("2026-09-15 09:30", tz="UTC")
        d = P3.read_day(df, swings, now=now)
        today = [s for s in detect_judas_swings(df, swings, session="london")
                 if str(s["session_date"]) == "2026-09-15"][0]
        self.assertEqual(d["stages"]["judas"], {
            "direction": "SHORT", "open": 100.0, "open_at": 1789452000, "open_ny": "02:00",
            "extreme": 101.0, "extreme_at": 1789452000, "extreme_ny": "02:00",
            "words": today["why_now"]})
        self.assertIn("faked to 101.0000", today["why_now"])
        # The old key is untouched by this build: it still names the London
        # of the Asian session's own New York date (F1, decision D1).
        bare = self._without_stages(df, swings, now)
        self.assertEqual(d["judas"], bare["judas"])

    # S9
    def test_a_stages_failure_costs_the_read_nothing(self):
        with patch.object(P3, "_sweeps", side_effect=RuntimeError("boom")):
            d = P3.read_day(day_frame(), [], now=OFF)
        self.assertIsNone(d["stages"])
        whole = P3.read_day(day_frame(), [], now=OFF)
        self.assertTrue(d["ok"])
        self.assertEqual(d["phase"], "distribution")
        for k in OLD_KEYS:
            self.assertEqual(d[k], whole[k], k)

    # S10
    def test_the_windows_need_a_tz_database(self):
        with patch("signals.smc.sessions.new_york_timezone", return_value=None):
            self.assertIsNone(P3._window(date(2026, 9, 15), "london", "london", OFF))
            self.assertIsNone(P3._ny_clock(OFF))
        self.assertIsNone(P3._window(date(2026, 9, 15), "nowhere", "london", OFF))

    # S11
    def test_the_stages_are_plain_json(self):
        d = P3.read_day(day_frame(), [], now=OFF)
        json.dumps(d)
        st = d["stages"]
        for win in (st["london"], st["new_york"]):
            self.assertIs(type(win["opened"]), int)
            self.assertIs(type(win["closed"]), int)
        for s in st["sweeps"]:
            self.assertIs(type(s["at"]), int)
            self.assertIs(type(s["back_at"]), int)
            self.assertIs(type(s["back_close_at"]), int)
            self.assertIs(type(s["price"]), float)
        self.assertIs(type(st["bar"]), int)
        df, swings = judas_frame()
        j = P3.read_day(df, swings, now=pd.Timestamp("2026-09-15 09:30", tz="UTC"))
        json.dumps(j)
        self.assertIs(type(j["stages"]["judas"]["extreme_at"]), int)

    # S12
    def test_power_of_three_carries_the_stages_and_says_none_on_failure(self):
        day = P3.power_of_three("X", now=OFF, bars=(day_frame(), [], "1h"))
        self.assertEqual(day["stages"]["date"], "2026-09-15")
        with patch.object(P3, "_frame", side_effect=RuntimeError("down")):
            day = P3.power_of_three("X", now=OFF)
        self.assertFalse(day["ok"])
        self.assertIn("stages", day)
        self.assertIsNone(day["stages"])

    def test_an_unread_day_says_none(self):
        late = pd.Timestamp("2026-09-20 12:00", tz="UTC")
        self.assertIsNone(P3.read_day(day_frame(), [], now=late)["stages"])
        self.assertIsNone(P3.read_day(day_frame().iloc[:5], [], now=OFF)["stages"])
        self.assertIsNone(P3.read_day(None, [], now=OFF)["stages"])

    def test_the_accumulation_before_any_bar_after_the_range(self):
        """The range's last bar is the newest: accumulation, no run, no
        Judas, the windows still said."""
        df = day_frame(run="none", end_hour=3)
        now = pd.Timestamp("2026-09-15 03:30", tz="UTC")
        d = P3.read_day(df, [], now=now)
        self.assertEqual(d["phase"], "accumulation")
        self.assertEqual(d["stages"]["sweeps"], [])
        self.assertIsNone(d["stages"]["judas"])
        self.assertEqual(d["stages"]["london"]["state"], "upcoming")


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

    # ── The stages reach the chart and nothing that trades (2026-10-08) ──
    CANNED = {"ok": True, "phase": "distribution", "direction": "up",
              "session": "ny_am", "asia": {"high": 100.5, "low": 99.5,
                                           "date": "2026-10-02"},
              "run": {"below": True, "above": False, "low": 98.8, "high": None},
              "judas": None, "timeframe": "1h", "why": "x",
              "words": "Power of Three (the ny am session, the day's distribution): x."}

    def _canned(self, stages=True):
        day = copy.deepcopy(self.CANNED)
        if stages:
            day["stages"] = copy.deepcopy(STAGES)
        return day

    def _walk(self, node, path="$"):
        """Every key path in a nested dict/list."""
        if isinstance(node, dict):
            for k, v in node.items():
                yield path + "." + str(k), k
                yield from self._walk(v, path + "." + str(k))
        elif isinstance(node, (list, tuple)):
            for i, v in enumerate(node):
                yield from self._walk(v, "%s[%d]" % (path, i))

    # M1
    def test_the_stages_reach_the_chart_and_nothing_that_trades(self):
        from bot_program import positioning as P
        from tests.test_positioning import _seed, _tape
        _seed("PO3STG", _tape(), asset_class="forex")
        with patch("bot_program.power_of_three.power_of_three",
                   return_value=self._canned()):
            pm = P.positioning_map("PO3STG", asset_class="forex", direction="BUY")
        with patch("bot_program.power_of_three.power_of_three",
                   return_value=self._canned(stages=False)):
            bare = P.positioning_map("PO3STG", asset_class="forex", direction="BUY")
        self.assertEqual(pm["po3_stages"], STAGES)
        self.assertNotIn("stages", pm["po3"])
        self.assertIsNone(bare["po3_stages"])
        c = P.compact(pm)
        self.assertNotIn("stages", c["po3"])
        self.assertNotIn("po3_stages", c)
        self.assertEqual(c, P.compact(bare), "compact() is the same map with or without stages")
        self.assertEqual(pm["words"], bare["words"])
        self.assertEqual(pm["side"]["words"], bare["side"]["words"])
        self.assertEqual(P.side_read(pm, "SELL")["words"], P.side_read(bare, "SELL")["words"])

    # M2
    def test_the_chart_reply_carries_the_stages(self):
        from django.contrib.auth.models import User
        from django.core.cache import cache

        from tests.test_positioning import _seed, _tape
        _seed("PO3CHT", _tape(), asset_class="forex")
        self.client.force_login(User.objects.create_user("po3_chart", password="x"))
        cache.delete("chart:positioning:PO3CHT")
        cache.delete("chart:levels:PO3CHT")
        # The daily frame, as test_positioning's chart reply: the 1h frame
        # falls through to the public feed (yfinance) when no 1h PriceData
        # is seeded, a live call to Yahoo from a test. The positioning reply
        # is built for any frame.
        with patch("bot_program.power_of_three.power_of_three",
                   return_value=self._canned()):
            reply = self.client.get("/api/chart-data/", {
                "symbol": "PO3CHT", "timeframe": "1d", "overlays": "1"}).json()
        cache.delete("chart:positioning:PO3CHT")
        self.assertTrue(reply["positioning"]["ok"], reply.get("positioning"))
        self.assertEqual(reply["positioning"]["po3"]["stages"], STAGES)
        self.assertEqual(reply["positioning"]["po3"]["phase"], "distribution")
        self.assertNotIn("po3_stages", reply["positioning"])

    # M3
    def test_the_ticket_and_the_reviewer_read_no_stages(self):
        from bot_program import manual_trade
        from brain import position_review
        from brain.position_review_agent import build_snapshot
        from tests.test_positioning import _seed, _tape
        _seed("PO3TKT", _tape(), asset_class="forex")
        with patch("bot_program.power_of_three.power_of_three",
                   return_value=self._canned()):
            ticket = manual_trade._positioning("PO3TKT", "forex", "BUY")
            facts = {"symbol": "PO3TKT", "asset_class": "forex", "side": "BUY"}
            review = position_review._positioning({}, facts)
        self.assertTrue(ticket["ok"])
        self.assertTrue(review["ok"])
        self.assertEqual(ticket["po3"]["phase"], "distribution")
        self.assertNotIn("stages", ticket["po3"])
        self.assertNotIn("stages", review["po3"])
        snap = build_snapshot({
            "position": {"book": "bot", "position_id": 1, "symbol": "PO3TKT",
                         "side": "long", "asset_class": "forex"},
            "facts": dict(facts, positioning=review), "triggers": []})
        keys = [k for _p, k in self._walk(snap)]
        self.assertIn("po3", keys, "the reviewer reads the day")
        self.assertNotIn("stages", keys)
        self.assertNotIn("po3_stages", keys)
        self.assertNotIn("sweeps", keys)


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
