"""The marks, the panels, and what the platform believes about itself.

  quote freshness    `LiveQuote.updated_at` is `auto_now` — OUR write time.
                     The poller's only gate was `is_any_market_open()`,
                     which ORs in forex and is therefore true from Sunday
                     evening to Friday evening, so at 03:00 UTC with the
                     NYSE shut it rewrote the previous session's close
                     every 60 seconds. The mark was not the problem; the
                     REFRESHED TIMESTAMP was, because the 900-second
                     staleness gate could then never fire for a stock.

  the raw writers    Three call sites wrote LiveQuote directly, around the
                     one function that refuses a zero and honours source
                     precedence. eToro's guard admitted a literal 0 and
                     wrote it as a real price, on the row that values the
                     real-money book.

  the feed verdict   Three copies of one loop, already drifted. The digest
                     walked the registry and caught a feed that had never
                     delivered; the health page grouped by sources that HAD
                     written, so it could not. The digest mailed "NOT
                     DELIVERING: OANDA" with a link to a page reading
                     "ok — 3 sources fresh".

  the macro calendar Every forex position's event-risk read rendered a
                     confident empty list through NFP, CPI and FOMC,
                     because the one writer of EconomicEvent stores an
                     equity TICKER in `currency_affected`.

Run with:  python manage.py test tests.test_tier345_truth
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone


def _instrument(symbol="AAPL", asset_class="stock"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    return inst


def _raw(task):
    """The undecorated function behind a Celery task.

    Patching `core.task_gate.is_component_enabled` is not reliable here:
    another module in this suite patches `sys.modules`, and restoring that
    dict can drop a module first imported inside the block — so a later
    patch binds a FRESH `core.task_gate` while the decorator still closes
    over the old one, and the master-switch branch runs unpatched. Calling
    the raw function is what the rest of the suite does, and it is what
    these tests are actually about.
    """
    fn = task
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


class AClosedSessionStopsRefreshingAFossilTests(TestCase):

    def test_the_stock_poller_is_gated_on_the_US_session(self):
        from market_data.tasks import fetch_live_quotes
        with patch("core.market_calendar.is_us_market_open",
                   return_value=False):
            out = _raw(fetch_live_quotes)(None)
        self.assertEqual(out.get("reason"), "us_session_closed")

    def test_forex_hours_no_longer_keep_the_stock_poller_awake(self):
        """The old gate ORed in forex — true from Sunday evening to Friday
        evening — so this polled through every overnight with the NYSE
        shut, rewriting the previous close and, fatally, refreshing its
        timestamp so nothing could tell the mark was old."""
        from market_data.tasks import fetch_live_quotes
        with patch("core.market_calendar.is_us_market_open",
                   return_value=False) as us, \
                patch("core.market_calendar.is_any_market_open",
                      return_value=True) as anym:
            _raw(fetch_live_quotes)(None)
        self.assertTrue(us.called, "the US session is not consulted")
        self.assertFalse(anym.called, "still gated on any market anywhere")

    def test_an_open_session_still_polls(self):
        """The gate must close the overnight, not the trading day."""
        from market_data.tasks import fetch_live_quotes
        with patch("core.market_calendar.is_us_market_open",
                   return_value=True):
            out = _raw(fetch_live_quotes)(None)
        self.assertNotEqual(out.get("reason"), "us_session_closed")

    def test_the_commodity_poller_stops_rewriting_fridays_close(self):
        """The WEEKEND only. Globex futures trade nearly around the clock
        on weekdays, so gating these on the equity session would freeze
        every commodity mark through most of its real trading day — a
        worse bug than the one being fixed."""
        from market_data.tasks import fetch_commodity_quotes
        with patch("core.market_calendar.is_weekend", return_value=True):
            out = _raw(fetch_commodity_quotes)()
        self.assertEqual(out.get("reason"), "weekend")

    def test_a_weekday_still_polls_commodities_overnight(self):
        """The contract is moving on Globex at 03:00 UTC even though the
        NYSE is shut."""
        from market_data.tasks import fetch_commodity_quotes
        with patch("core.market_calendar.is_weekend", return_value=False), \
                patch("core.market_calendar.is_us_market_open",
                      return_value=False):
            out = _raw(fetch_commodity_quotes)()
        self.assertNotEqual(out.get("reason"), "weekend")



class EveryQuoteWriteGoesThroughTheOneGateTests(TestCase):
    """write_quote refuses a zero and honours SOURCE_PRIORITY. Three call
    sites went around it."""

    def test_no_raw_upserts_remain_outside_the_gate(self):
        from pathlib import Path

        from django.conf import settings
        root = Path(settings.BASE_DIR)
        hits = []
        for path in root.rglob("*.py"):
            rel = str(path.relative_to(root)).replace("\\", "/")
            if rel.startswith(("tests/", "SV_V/")) or "migrations" in rel:
                continue
            if rel == "market_data/quotes.py":
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if "LiveQuote.objects.update_or_create" in text:
                hits.append(rel)
        self.assertEqual(hits, [], f"raw LiveQuote writers: {hits}")

    def test_a_zero_rate_leaves_the_position_unpriced(self):
        """eToro's guard was `not in (None, "")`, which admits 0 — and a 0
        in LiveQuote reads downstream as a real price of zero."""
        from market_data.models import LiveQuote
        from market_data.quotes import write_quote
        inst = _instrument("ZERO1")
        self.assertFalse(write_quote("ZERO1", last=0, source="etoro",
                                     instrument=inst))
        self.assertFalse(LiveQuote.objects.filter(instrument=inst).exists())

    def test_a_real_rate_is_written(self):
        from market_data.quotes import write_quote
        inst = _instrument("REAL1")
        self.assertTrue(write_quote("REAL1", last="42.5", source="etoro",
                                    instrument=inst))

    def test_etoro_has_a_declared_precedence(self):
        """Left to DEFAULT_PRIORITY it sat below IBKR and above nothing in
        particular — a broker's own rate for a position it holds deserves
        the broker-REST tier, stated rather than inferred."""
        from market_data.quotes import SOURCE_PRIORITY
        self.assertEqual(SOURCE_PRIORITY.get("etoro"), 70)

    def test_an_hourly_read_cannot_outrank_a_live_stream(self):
        from market_data.quotes import SOURCE_PRIORITY
        self.assertGreater(SOURCE_PRIORITY["binance_ws"],
                           SOURCE_PRIORITY["ibkr"])
        self.assertGreater(SOURCE_PRIORITY["ibkr"],
                           SOURCE_PRIORITY["alpha_vantage"])


class OneVerdictAboutTheFeedsTests(TestCase):

    def test_a_feed_that_never_wrote_is_still_reported(self):
        """The health page grouped by rows that EXIST, so a feed in `never`
        contributed nothing and could not be missed."""
        from market_data.feeds import FEEDS, feed_states
        rows = feed_states()
        self.assertEqual(len([r for r in rows if r["state"] != "unregistered"]),
                         len(FEEDS))

    def test_an_undeclared_writer_is_named_not_dropped(self):
        from market_data.feeds import feed_states
        from market_data.models import LiveQuote
        LiveQuote.objects.create(instrument=_instrument("STRAY1"),
                                 last=Decimal("10"), source="mystery_feed")
        strays = [r for r in feed_states() if r["state"] == "unregistered"]
        self.assertEqual([r["source"] for r in strays], ["mystery_feed"])

    def test_the_page_and_the_digest_read_the_same_function(self):
        """Three copies had already drifted into contradicting each other."""
        import inspect

        from core import component_digest
        from dashboard import live_health, views_system_health
        for mod in (component_digest, live_health, views_system_health):
            src = inspect.getsource(mod)
            self.assertIn("feed_states", src, mod.__name__)

    def test_the_quote_check_can_report_a_failure_at_all(self):
        """It had only ok/warn branches, so NO quote condition whatever
        could turn the page red — while the digest was mailing about one."""
        import inspect

        from dashboard import views_system_health
        src = inspect.getsource(views_system_health.check_quote_freshness)
        self.assertIn('"fail"', src)

    def test_a_platform_that_never_started_is_not_a_platform_that_broke(self):
        """A fresh install has no quotes at all. Reporting FAIL there
        trains an operator to ignore the colour."""
        from dashboard.views_system_health import check_quote_freshness
        c = check_quote_freshness()
        self.assertEqual(c["state"], "warn")
        self.assertFalse(c["configured"])


class AForexPositionKnowsItIsUncheckedTests(TestCase):

    def _pos(self, symbol="EURUSD"):
        return {"symbol": symbol, "asset_class": "forex"}

    def test_an_empty_calendar_reports_blind_not_clear(self):
        from brain.position_review import _imminent_events
        rows = _imminent_events(self._pos())
        self.assertTrue(rows, "rendered as 'checked, nothing imminent'")
        self.assertTrue(rows[0].get("blind"))

    def test_the_marker_names_the_currencies_it_could_not_check(self):
        from brain.position_review import _imminent_events
        rows = _imminent_events(self._pos("EURUSD"))
        self.assertIn("EUR", rows[0]["currency_affected"])
        self.assertIn("USD", rows[0]["currency_affected"])

    def test_a_stock_position_is_unaffected(self):
        """The blind marker is about the CURRENCY branch — a single-name
        equity is matched by title, which the earnings scraper does fill."""
        from brain.position_review import _imminent_events
        self.assertEqual(_imminent_events(
            {"symbol": "AAPL", "asset_class": "stock"}), [])

    def test_a_real_macro_row_suppresses_the_marker(self):
        """Once a source exists the marker must get out of the way."""
        from brain.position_review import _imminent_events
        from market_data.models import EconomicEvent
        EconomicEvent.objects.create(
            title="Non-Farm Payrolls", currency_affected="USD",
            impact="high", datetime=timezone.now() + timedelta(hours=2))
        rows = _imminent_events(self._pos())
        self.assertFalse(any(r.get("blind") for r in rows))
        self.assertEqual(rows[0]["title"], "Non-Farm Payrolls")
