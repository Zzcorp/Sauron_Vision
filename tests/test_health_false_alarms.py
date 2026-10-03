"""Three health false alarms from Saturday 2026-10-03 00:24 UTC.

check_feeds said OANDA was "RED — silent since before its market closed —
it stopped during the session": its last print was 20:58 UTC Friday, two
minutes before the 21:00 bell. It said Yahoo was "YELLOW — slower than
expected" on a Saturday with every market it marks shut. And /health/
warned "live but scans nothing: manual, manual, manual, manual" — the TAKE
TRADE lanes, which carry no symbols by design.

Run with:  python manage.py test tests.test_health_false_alarms
"""
from datetime import datetime, timedelta, timezone as dt_tz
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from market_data.feeds import Window, state_for

SAT_0024 = datetime(2026, 10, 3, 0, 24, tzinfo=dt_tz.utc)
FRI_2058 = datetime(2026, 10, 2, 20, 57, 36, tzinfo=dt_tz.utc)
FRI_0940 = datetime(2026, 10, 2, 9, 40, tzinfo=dt_tz.utc)
FRI_2355 = datetime(2026, 10, 2, 23, 55, tzinfo=dt_tz.utc)

OANDA = {"key": "oanda_stream", "label": "OANDA (stream)", "kind": "stream",
         "requires": (), "window": Window.FOREX, "ages": (60, 300)}
YAHOO = {"key": "yfinance", "label": "Yahoo Finance", "kind": "poller",
         "requires": (), "window": Window.FOREX, "ages": (900, 3600)}


class FeedClockTests(SimpleTestCase):

    def _state(self, feed, latest, now=SAT_0024):
        age = (now - latest).total_seconds()
        return state_for(feed, latest=latest, age_seconds=age, now=now)[0]

    def test_a_stream_alive_at_the_bell_is_idle_over_the_weekend(self):
        self.assertEqual(self._state(OANDA, FRI_2058), "idle")

    def test_a_stream_that_died_in_the_morning_is_still_red(self):
        self.assertEqual(self._state(OANDA, FRI_0940), "red")

    def test_yahoo_is_idle_on_a_saturday_not_slow(self):
        self.assertEqual(self._state(YAHOO, FRI_2355), "idle")

    def test_the_registry_s_yahoo_keeps_forex_hours(self):
        from market_data import feeds
        yahoo = [f for f in feeds.FEEDS if f["key"] == "yfinance"][0]
        self.assertEqual(yahoo["window"], Window.FOREX)


class ManualLaneTests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user("hl_u", password="x")

    def _cfg(self, name, asset_class="forex", symbols=()):
        from bot_program.models import AssetBotConfig
        return AssetBotConfig.objects.create(
            user=self.user, asset_class=asset_class, name=name, mode="live",
            enabled=True, symbols=list(symbols), capital=Decimal("1000"))

    def test_the_manual_lane_is_counted_not_warned_about(self):
        from dashboard.views_system_health import check_live_mode_readiness
        self._cfg("manual", "forex")
        self._cfg("manual", "stock")
        row = check_live_mode_readiness(self.user)
        self.assertEqual(row["state"], "ok", row)
        self.assertIn("2 manual TAKE TRADE lane(s) (forex, stock) carry no "
                      "symbols by design", row["detail"])
        self.assertIn("0 live bot(s)", row["detail"])

    def test_another_symbol_less_live_config_is_still_a_warning(self):
        from dashboard.views_system_health import check_live_mode_readiness
        self._cfg("manual", "forex")
        self._cfg("L", "stock")
        row = check_live_mode_readiness(self.user)
        self.assertEqual(row["state"], "warn")
        self.assertIn("scans nothing: L", row["detail"])
        self.assertNotIn("manual", row["detail"].split("scans nothing")[1])
