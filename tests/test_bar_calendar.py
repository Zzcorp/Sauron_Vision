"""An old bar on a shut market is not a fault.

`check_bot_bars` compared every symbol against one duration and nothing else,
across 35 instruments on five different market calendars. So on any weekend it
reported an outage: 27 of 35 "stale" — every equity, every FX pair, every
soft. On 2026-09-06 that reading ("Bot bars 0/35 fresh") sent its operator,
and me, on a two-day hunt for a dead bar writer that had in fact been
dispatched every ten minutes throughout. The bar ages taken on the Sunday
reopen settled it: gold, silver, platinum, palladium, copper, WTI, Brent and
gas all fresh within three hours, every equity and FX pair still on Friday's
close. Each group was stale by exactly as much as its own market was shut.

The only genuinely dead thing that weekend was a Finnhub stream, silent for
four days, and it sat unnoticed underneath the fabricated outage. That is the
real cost: a false red spends the attention a true one needs, and teaches the
operator that the row is noise.

`feeds.window_last_closed` already drew this line and `check_feeds` had been
using it correctly all along — "what separates 'quiet because the market is
shut' from 'died during the session and the shut market is covering for it'".
This wires the same answer into the bars.

Run with:  python manage.py test tests.test_bar_calendar
"""
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

NY = ZoneInfo("America/New_York")


def _at(y, m, d, hh, mm=0):
    """A UTC instant expressed in New York wall time, which is what every
    market window in this codebase is defined against."""
    return datetime(y, m, d, hh, mm, tzinfo=NY)


def _cfg(user, *, asset_class="stock", symbols=("AAPL",)):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=f"c_{asset_class}",
        mode="paper", symbols=list(symbols), capital=Decimal("10000"),
        enabled=True)


def _bar(symbol, *, at, asset_class="stock"):
    from instruments.models import Instrument
    from market_data.models import PriceData
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    if inst.asset_class != asset_class:
        inst.asset_class = asset_class
        inst.save(update_fields=["asset_class"])
    PriceData.objects.update_or_create(
        instrument=inst, timeframe="4h", timestamp=at,
        defaults={"open": 1, "high": 2, "low": 1, "close": 1,
                  "volume": 10, "source": "test"})
    return inst


def _run(user, *, now):
    """check_bot_bars as of a fixed instant."""
    from dashboard.views_system_health import check_bot_bars
    with patch.object(timezone, "now", return_value=now):
        return check_bot_bars(user)


class TheWeekendIsNotAnOutageTests(TestCase):
    """The exact reading that cost two days, replayed."""

    def setUp(self):
        self.user = User.objects.create_user("cal_u", password="x")

    def test_an_equity_fed_to_fridays_close_is_ok_on_a_sunday(self):
        _cfg(self.user, asset_class="stock", symbols=("AAPL",))
        # Friday 2026-09-04, last 4h bar of the US session.
        _bar("AAPL", at=_at(2026, 9, 4, 12), asset_class="stock")
        row = _run(self.user, now=_at(2026, 9, 6, 18))   # Sunday evening
        self.assertEqual(row["state"], "ok", row["detail"])
        self.assertIn("waiting for it to reopen", row["detail"])

    def test_forex_fed_to_fridays_close_is_ok_on_a_saturday(self):
        _cfg(self.user, asset_class="forex", symbols=("EURUSD",))
        _bar("EURUSD", at=_at(2026, 9, 4, 15), asset_class="forex")
        row = _run(self.user, now=_at(2026, 9, 5, 10))   # Saturday
        self.assertEqual(row["state"], "ok", row["detail"])

    def test_the_whole_book_on_a_saturday_is_ok(self):
        """27 of 35 went amber every weekend. None of them should."""
        _cfg(self.user, asset_class="stock", symbols=("AAPL", "MSFT"))
        _cfg(self.user, asset_class="forex", symbols=("EURUSD", "GBPUSD"))
        for s in ("AAPL", "MSFT"):
            _bar(s, at=_at(2026, 9, 4, 12), asset_class="stock")
        for s in ("EURUSD", "GBPUSD"):
            _bar(s, at=_at(2026, 9, 4, 15), asset_class="forex")
        row = _run(self.user, now=_at(2026, 9, 5, 11))
        self.assertEqual(row["state"], "ok", row["detail"])


class ADeathDuringTheSessionIsStillCaughtTests(TestCase):
    """The guard must not swallow the case the check exists for. This is the
    half that matters: forgiving a shut market must not forgive a writer that
    stopped while the market was trading."""

    def setUp(self):
        self.user = User.objects.create_user("cal_dead", password="x")

    def test_a_writer_that_died_mid_week_is_stale_on_a_sunday(self):
        _cfg(self.user, asset_class="stock", symbols=("AAPL",))
        # Wednesday — two full sessions before Friday's close.
        _bar("AAPL", at=_at(2026, 9, 2, 10), asset_class="stock")
        row = _run(self.user, now=_at(2026, 9, 6, 18))
        self.assertEqual(row["state"], "warn", row["detail"])
        self.assertIn("stale", row["detail"])

    def test_a_stale_bar_during_an_open_session_is_stale(self):
        _cfg(self.user, asset_class="stock", symbols=("AAPL",))
        # Monday 11:00 ET, newest bar from Friday: the market is OPEN and the
        # feed is not speaking.
        _bar("AAPL", at=_at(2026, 9, 4, 12), asset_class="stock")
        row = _run(self.user, now=_at(2026, 9, 7, 11))
        self.assertEqual(row["state"], "warn", row["detail"])

    def test_crypto_is_never_forgiven(self):
        """ALWAYS means there is no close to hide behind."""
        _cfg(self.user, asset_class="crypto", symbols=("BTCUSDT",))
        _bar("BTCUSDT", at=_at(2026, 9, 4, 12), asset_class="crypto")
        row = _run(self.user, now=_at(2026, 9, 6, 18))
        self.assertEqual(row["state"], "warn", row["detail"])

    def test_a_missing_instrument_still_fails(self):
        _cfg(self.user, asset_class="stock", symbols=("NOSUCH",))
        row = _run(self.user, now=_at(2026, 9, 7, 11))
        self.assertEqual(row["state"], "fail", row["detail"])


class FreshBarsStillReadFreshTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("cal_fresh", password="x")

    def test_an_open_market_with_current_bars_is_ok(self):
        _cfg(self.user, asset_class="stock", symbols=("AAPL",))
        now = _at(2026, 9, 7, 11)
        _bar("AAPL", at=now - timedelta(hours=1), asset_class="stock")
        row = _run(self.user, now=now)
        self.assertEqual(row["state"], "ok", row["detail"])
        self.assertIn("fresh", row["detail"])

    def test_no_configs_is_still_not_configured(self):
        row = _run(self.user, now=_at(2026, 9, 7, 11))
        self.assertEqual(row["state"], "ok")
        self.assertFalse(row["configured"])


class TheWindowMapTests(SimpleTestCase):

    def test_each_class_maps_to_the_calendar_it_trades_on(self):
        from dashboard.views_system_health import _bar_window
        from market_data.feeds import Window
        self.assertEqual(_bar_window("crypto"), Window.ALWAYS)
        self.assertEqual(_bar_window("stock"), Window.US_EQUITY)
        self.assertEqual(_bar_window("etf"), Window.US_EQUITY)
        self.assertEqual(_bar_window("index"), Window.US_EQUITY)
        self.assertEqual(_bar_window("forex"), Window.FOREX)

    def test_commodity_follows_the_nearly_24_5_calendar(self):
        """Metals and energy reopen with FX on Sunday evening ET — the
        operator's own bar ages proved it. Grains keep narrower hours, so this
        is an approximation whose residual error names a problem that is not
        there rather than hiding one that is."""
        from dashboard.views_system_health import _bar_window
        from market_data.feeds import Window
        self.assertEqual(_bar_window("commodity"), Window.FOREX)

    def test_an_unknown_class_is_never_forgiven(self):
        """A new asset class must show up as a bar problem until somebody
        decides its calendar, not be silently excused by a default."""
        from dashboard.views_system_health import _bar_window
        from market_data.feeds import Window
        for junk in ("", None, "warrants", "SomethingNew"):
            self.assertEqual(_bar_window(junk), Window.ALWAYS)

    def test_there_is_exactly_one_calendar_in_the_codebase(self):
        """The map must delegate to feeds.Window rather than restate it. Two
        calendars drift apart, and the drift shows up as a confident wrong
        verdict on a health page."""
        import inspect

        from dashboard import views_system_health
        src = inspect.getsource(views_system_health._bar_window)
        self.assertIn("from market_data.feeds import Window", src)
        self.assertIn("Window.US_EQUITY", src)

    def test_one_bar_period_of_grace_is_declared(self):
        """A 4h bar is stamped with its period START, so the last bar of a
        session begins up to four hours before the close. Without the grace
        every symbol reads stale for its first four shut hours."""
        from dashboard.views_system_health import (
            BAR_PERIOD_SECONDS, BAR_STALE_SECONDS)
        self.assertEqual(BAR_PERIOD_SECONDS, 4 * 3600)
        self.assertGreaterEqual(BAR_PERIOD_SECONDS, BAR_STALE_SECONDS)
