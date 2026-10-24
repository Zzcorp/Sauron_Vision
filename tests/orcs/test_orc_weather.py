"""THE DAY'S WEATHER (bot_program/orcs/weather.py, spec §7.5.3) and the
trading day it is computed on (bot_program/orcs/sessions.py): the day
rolls at 17:00 New York on both sides of the clock change; calm, eventful
or stormy per (user, class); re-run upward only, never lowered within the
day; the caps are shown, never applied, in O1.

Run with:  python manage.py test tests.orcs.test_orc_weather
"""
from datetime import date, datetime, timedelta
from datetime import timezone as dt_tz
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from tests.orcs.helpers import _user

UTC = dt_tz.utc


class TheTradingDayTests(SimpleTestCase):

    def test_the_roll_at_17_new_york_in_summer(self):
        from bot_program.orcs.sessions import day_bounds, trading_day
        # EDT: 17:00 New York is 21:00 UTC
        self.assertEqual(trading_day(datetime(2026, 10, 21, 20, 59,
                                              tzinfo=UTC)),
                         date(2026, 10, 21))
        self.assertEqual(trading_day(datetime(2026, 10, 21, 21, 0,
                                              tzinfo=UTC)),
                         date(2026, 10, 22))
        start, end = day_bounds(date(2026, 10, 22))
        self.assertEqual(start, datetime(2026, 10, 21, 21, 0, tzinfo=UTC))
        self.assertEqual(end, datetime(2026, 10, 22, 21, 0, tzinfo=UTC))

    def test_the_roll_at_17_new_york_in_winter(self):
        from bot_program.orcs.sessions import day_bounds, trading_day
        # EST: 17:00 New York is 22:00 UTC
        self.assertEqual(trading_day(datetime(2026, 12, 2, 21, 30,
                                              tzinfo=UTC)),
                         date(2026, 12, 2))
        self.assertEqual(trading_day(datetime(2026, 12, 2, 22, 0,
                                              tzinfo=UTC)),
                         date(2026, 12, 3))
        start, end = day_bounds(date(2026, 12, 3))
        self.assertEqual(end - start, timedelta(hours=24))
        self.assertEqual(start.hour, 22)

    def test_the_day_that_changes_the_clock_is_25_hours(self):
        from bot_program.orcs.sessions import day_bounds
        # the US clocks fall back on Sunday 2026-11-01 at 02:00, inside
        # the trading day that rolls at 17:00 that Sunday
        start, end = day_bounds(date(2026, 11, 1))
        self.assertEqual(end - start, timedelta(hours=25))

    def test_sessions_in_order_and_closed_ones(self):
        from bot_program.orcs.sessions import (SESSION_NAMES,
                                               closed_sessions,
                                               session_windows)
        wins = session_windows(date(2026, 10, 22))
        self.assertEqual([w[0] for w in wins], list(SESSION_NAMES))
        self.assertEqual(SESSION_NAMES, ("asia", "london", "ny_am",
                                         "ny_lunch", "ny_pm"))
        asia = wins[0]
        self.assertEqual(asia[1], datetime(2026, 10, 22, 0, 0, tzinfo=UTC))
        self.assertEqual(asia[2], datetime(2026, 10, 22, 4, 0, tzinfo=UTC))
        london = wins[1]
        self.assertEqual((london[1].hour, london[2].hour), (6, 9))
        self.assertEqual(closed_sessions(datetime(2026, 10, 22, 9, 30,
                                                  tzinfo=UTC)),
                         ["asia", "london"])
        self.assertEqual(closed_sessions(datetime(2026, 10, 21, 21, 30,
                                                  tzinfo=UTC)), [])


class TheWeatherTests(TestCase):

    def setUp(self):
        self.user = _user("orc_weather")
        self.now = datetime(2026, 10, 21, 15, 0, tzinfo=UTC)

    def _inputs(self, **kw):
        base = {"atr_ratio": 1.0,
                "regime": {"brain_changed": False, "brain_conf": 0.8},
                "prints": {"in_24h": 0, "within_3h": 0, "in_window": False},
                "news": {"blind": False, "ratio": 1.0},
                "stress": {"fresh": True, "score": 10.0, "vix_term": 0.9},
                "gap": {"shut_within_6h": False, "gap_r": None},
                "posture_level": "calm", "posture_fresh": True,
                "prints_today": 0, "regime_label": "risk_on"}
        base.update(kw)
        return base

    def test_one_row_per_user_class_and_trading_day(self):
        from bot_program.orcs.models import OrcDayBaseline
        from bot_program.orcs.weather import current
        row = current(self.user, "forex", self.now, inputs=self._inputs())
        again = current(self.user, "forex", self.now + timedelta(hours=1),
                        inputs=self._inputs())
        self.assertEqual(row.pk, again.pk)
        self.assertEqual(row.trading_day, date(2026, 10, 21))
        self.assertEqual(row.day_class, "calm")
        self.assertEqual(row.routing_version, "table-v1")
        tomorrow = current(self.user, "forex",
                           datetime(2026, 10, 21, 21, 30, tzinfo=UTC),
                           inputs=self._inputs())
        self.assertEqual(tomorrow.trading_day, date(2026, 10, 22))
        self.assertEqual(OrcDayBaseline.objects.count(), 2)

    def test_stormy_rules(self):
        from bot_program.orcs.weather import current
        row = current(self.user, "index", self.now,
                      inputs=self._inputs(posture_level="crisis"))
        self.assertEqual(row.day_class, "stormy")
        row = current(self.user, "forex", self.now,
                      inputs=self._inputs(prints_today=3))
        self.assertEqual(row.day_class, "stormy")

    def test_upward_only_on_a_posture_or_regime_change_never_lowered(self):
        from bot_program.orcs.weather import current
        row = current(self.user, "forex", self.now, inputs=self._inputs())
        self.assertEqual(row.day_class, "calm")
        # the same posture and regime: nothing is re-run, even on worse
        # numbers
        same = current(self.user, "forex", self.now + timedelta(hours=1),
                       inputs=self._inputs(prints={"in_24h": 2,
                                                   "within_3h": 2,
                                                   "in_window": True}))
        self.assertEqual(same.day_class, "calm")
        # the posture changed: re-run, raised
        up = current(self.user, "forex", self.now + timedelta(hours=2),
                     inputs=self._inputs(posture_level="stressed"))
        self.assertEqual(up.day_class, "stormy")
        self.assertEqual(len(up.history), 2)
        # it changed back: never lowered within the day
        back = current(self.user, "forex", self.now + timedelta(hours=3),
                       inputs=self._inputs(posture_level="calm"))
        self.assertEqual(back.day_class, "stormy")
        self.assertGreaterEqual(back.score, up.score)

    def test_a_higher_score_on_a_lower_class_never_lowers_the_class(self):
        """Stormy by its posture on a low score; then the posture is calm
        and the score higher: the score rises, the class stays stormy."""
        from bot_program.orcs.weather import current
        up = current(self.user, "forex", self.now,
                     inputs=self._inputs(posture_level="crisis"))
        self.assertEqual(up.day_class, "stormy")
        later = current(self.user, "forex", self.now + timedelta(hours=1),
                        inputs=self._inputs(stress={"fresh": True,
                                                    "score": 45.0,
                                                    "vix_term": 0.9},
                                            prints={"in_24h": 1,
                                                    "within_3h": 1,
                                                    "in_window": False}))
        self.assertGreater(later.score, up.score)
        self.assertEqual(later.day_class, "stormy")
        self.assertEqual(later.history[-1]["day_class"], "stormy")

    def test_caps_for_display_only(self):
        from bot_program.orcs.weather import caps_for
        self.assertEqual(caps_for("calm", True)["wakes_per_day"], 12)
        self.assertEqual(caps_for("eventful", True)["wakes_per_day"], 14)
        self.assertEqual(caps_for("stormy", True)["wakes_per_day"], 16)
        self.assertEqual(caps_for("stormy", False)["wakes_per_day"], 12)
        self.assertEqual(caps_for("stormy", True)["frontier_quota"], 4)
        self.assertTrue(caps_for("calm", True)["display_only"])
        for v in caps_for("calm", True).values():
            self.assertNotIsInstance(v, float, "no dollar figure")

    def test_inputs_read_with_crisis_mode_off_and_no_analyst(self):
        """No stress reading and no analyst: the day is still computed,
        their components are dashes, never an abstention."""
        from bot_program.orcs.weather import current, market_inputs
        inputs = market_inputs(self.user, "forex", self.now)
        self.assertFalse(inputs["stress"]["fresh"])
        self.assertTrue(inputs["news"]["blind"])
        row = current(self.user, "forex", self.now)
        self.assertEqual(row.day_class, "calm")
        comps = row.components["market"]
        self.assertEqual(comps["stress"]["dash"],
                         "— (not measured: crisis_mode off)")
        self.assertTrue(comps["news"]["dash"].startswith(
            "— (tags blind since"))
        # the class's day reads no volatility: it is one row's, per wake
        self.assertEqual(comps["vol"]["dash"],
                         "— (read per position on each wake, not per class)")
        self.assertEqual(comps["vol"]["s"], 0)

    def test_a_failing_input_never_raises(self):
        from bot_program.orcs.weather import market_inputs
        with patch("bot_program.orcs.sources.posture",
                   side_effect=RuntimeError("down")):
            out = market_inputs(self.user, "forex", self.now)
        self.assertIn("stress", out)
