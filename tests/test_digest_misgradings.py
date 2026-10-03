"""Five rows of the 2026-10-03 digest ("7 things need attention") that were
the grading, not the component:

  * Opportunity Scanner — "not configured: 132": `resolve_pending_flags`
    counted flags whose horizon had not passed under `skipped`, the word
    the gate reserves for a missing credential.
  * Crypto News — "handled 25 rows and stored none": five feeds answered
    and every headline was already on file, every ten minutes.
  * Crypto Prices — "ran and produced nothing": the websocket stream held
    every symbol, so every REST write was refused, every two minutes.
  * TradingView Ideas — "handled 20 rows and stored none": the task
    counted requests, not answers, and the resolver sent forex and crypto
    to NASDAQ.
  * Alpha Vantage — "never delivered": true by design (OANDA outranks it),
    but all weekend OANDA was no longer "fresh", so the feed it covers for
    fell from `yielding` to `never`.

The two that are not here — the FMP economic calendar's 402 and Reddit's
missing credentials — are real and need the operator, not code.

Run with:  python manage.py test tests.test_digest_misgradings
"""
import os
from datetime import datetime, timezone as dt_tz
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase


def _enable(*keys):
    from core.platform_control import PlatformComponent, seed_components
    seed_components()
    PlatformComponent.objects.filter(
        key__in=["platform_master", *keys]).update(is_enabled=True)


def _instrument(symbol, asset_class):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class,
                                 "is_active": True})
    return inst


class TheScannerIsNotUnconfiguredTests(TestCase):

    def test_flags_not_yet_due_are_not_a_missing_credential(self):
        from core.task_gate import judge_result
        from signals.opportunity_scanner import resolve_pending_flags
        out = resolve_pending_flags()
        self.assertIn("not_due", out)
        self.assertNotIn("skipped", out)
        self.assertEqual(judge_result(out), ("success", "ok"))

    def test_the_old_shape_is_what_the_digest_read(self):
        """Documents the misgrading, so nobody puts the word back."""
        from core.task_gate import judge_result
        self.assertEqual(judge_result({"hit": 0, "skipped": 132}),
                         ("warning", "not configured: 132"))


class CryptoNewsWithNothingNewTests(TestCase):

    def setUp(self):
        _enable("scraper_crypto_news")

    def _run(self, scraper_result):
        with patch("market_data.adapters.crypto_news.fetch_crypto_news",
                   return_value=scraper_result), \
             patch("dashboard.consumers.push_news_notification"):
            from market_data.tasks import fetch_crypto_news_task
            return fetch_crypto_news_task()

    def test_feeds_answered_and_all_headlines_known_is_a_skip_with_its_reason(self):
        from core.task_gate import judge_result
        out = self._run({"parsed": 25, "stored": 0, "feeds_ok": 5,
                         "feeds_dead": []})
        self.assertEqual(out["status"], "skipped")
        self.assertEqual(out["reason"],
                         "5 feed(s) answered; all 25 headlines already stored")
        self.assertEqual(out["articles"], 0)
        self.assertEqual(judge_result(out)[0], "success")

    def test_dead_feeds_are_still_the_warning_they_are(self):
        from core.task_gate import judge_result
        out = self._run({"parsed": 0, "stored": 0, "feeds_ok": 0,
                         "feeds_dead": ["coindesk", "cointelegraph"]})
        self.assertEqual(out["status"], "success")
        self.assertEqual(judge_result(out),
                         ("warning", "ran and produced nothing"))

    def test_new_rows_still_grade_as_work_done(self):
        from core.task_gate import judge_result
        out = self._run({"parsed": 25, "stored": 2, "feeds_ok": 5,
                         "feeds_dead": []})
        self.assertEqual(out["status"], "success")
        self.assertEqual(judge_result(out)[0], "success")


class CryptoPricesHeldByTheStreamTests(TestCase):

    def setUp(self):
        _enable("scraper_crypto")
        self.inst = _instrument("BTCUSD", "crypto")

    def _run(self, feed):
        with patch("market_data.public_feed.public_feed_for",
                   return_value=feed):
            from market_data.tasks import fetch_crypto_quotes
            return fetch_crypto_quotes()

    def test_every_symbol_held_by_the_websocket_is_a_skip_not_nothing(self):
        from market_data.models import LiveQuote
        LiveQuote.objects.create(instrument=self.inst, last=Decimal("50000"),
                                 source="binance_ws")
        feed = MagicMock()
        out = self._run(feed)
        self.assertEqual(out["status"], "skipped")
        self.assertEqual(out["reason"],
                         "1 symbol(s) held by fresher higher-priority sources")
        feed.ticker.assert_not_called()

    def test_an_unheld_symbol_is_still_polled_and_written(self):
        feed = MagicMock()
        feed.ticker.return_value = {"lastPrice": "50000",
                                    "priceChangePercent": "1.2"}
        out = self._run(feed)
        self.assertEqual((out["status"], out["fetched"], out["attempted"],
                          out["held"]), ("success", 1, 1, 0))
        from market_data.models import LiveQuote
        self.assertEqual(LiveQuote.objects.get(instrument=self.inst).source,
                         "binance_public")


class TradingViewCountsAnswersTests(TestCase):

    def setUp(self):
        _enable("scraper_tradingview")
        self.insts = [_instrument("GBPCHF", "forex"),
                      _instrument("ADAUSD", "crypto")]

    def _run(self, answer):
        with patch("scraping.tasks._scan_universe", return_value=self.insts), \
             patch("scraping.scrapers.tradingview.fetch_technical_analysis",
                   return_value=answer) as fta:
            from scraping.tasks import fetch_tradingview_ideas
            return fetch_tradingview_ideas(), fta

    def test_placeholders_for_every_symbol_are_an_error_not_a_dedupe(self):
        from core.task_gate import judge_result
        out, _ = self._run({"recommendation": "NEUTRAL", "indicators": {}})
        self.assertEqual(out["status"], "error")
        self.assertIn("answered no data for 2/2 symbols", out["error"])
        self.assertEqual(out["parsed"], 0)
        self.assertEqual(judge_result(out)[0], "error")

    def test_answers_are_counted_and_the_class_travels_with_the_symbol(self):
        out, fta = self._run({"recommendation_value": 0.3})
        self.assertEqual((out["status"], out["parsed"], out["answered"]),
                         ("success", 2, 2))
        self.assertEqual(fta.call_args_list[0].kwargs["asset_class"], "forex")
        self.assertEqual(fta.call_args_list[1].kwargs["asset_class"], "crypto")


class TheVenueSpellingTests(SimpleTestCase):

    def test_forex_and_crypto_go_to_their_venues_not_nasdaq(self):
        from scraping.scrapers.tradingview import _resolve_tv_symbol as r
        self.assertEqual(r("GBPCHF", "forex"), "FX:GBPCHF")
        self.assertEqual(r("ADAUSD", "crypto"), "BINANCE:ADAUSDT")
        self.assertEqual(r("BTCUSDT", "crypto"), "BINANCE:BTCUSDT")
        self.assertEqual(r("AAPL", "stock"), "NASDAQ:AAPL")
        self.assertEqual(r("XAUUSD", "commodity"), "TVC:GOLD")
        self.assertEqual(r("NYSE:JPM", "stock"), "NYSE:JPM")
        self.assertEqual(r("AAPL"), "NASDAQ:AAPL")


#: Both feeds configured: OANDA has to count as switched on for its row to
#: read idle or red rather than off.
KEYS = {"ALPHA_VANTAGE_API_KEY": "k", "OANDA_API_KEY": "k",
        "OANDA_ACCOUNT_ID": "001"}


class AlphaVantageOnTheWeekendTests(TestCase):

    def test_a_superseder_alive_at_the_close_still_covers_for_the_feed(self):
        from market_data.feeds import feed_states
        from market_data.models import LiveQuote
        inst = _instrument("EURUSD", "forex")
        LiveQuote.objects.create(instrument=inst, last=Decimal("1.1"),
                                 source="oanda_stream")
        # OANDA's last print of the week, two minutes before the bell.
        LiveQuote.objects.filter(instrument=inst).update(
            updated_at=datetime(2026, 10, 2, 20, 58, tzinfo=dt_tz.utc))
        saturday = datetime(2026, 10, 3, 10, 0, tzinfo=dt_tz.utc)
        with patch.dict(os.environ, KEYS):
            states = {s["source"]: s for s in feed_states(now=saturday)}
        self.assertEqual(states["alpha_vantage"]["state"], "yielding")
        self.assertEqual(states["oanda_stream"]["state"], "idle")

    def test_a_superseder_that_died_before_the_close_covers_for_nothing(self):
        from market_data.feeds import feed_states
        from market_data.models import LiveQuote
        inst = _instrument("EURUSD", "forex")
        LiveQuote.objects.create(instrument=inst, last=Decimal("1.1"),
                                 source="oanda_stream")
        LiveQuote.objects.filter(instrument=inst).update(
            updated_at=datetime(2026, 10, 2, 9, 0, tzinfo=dt_tz.utc))
        saturday = datetime(2026, 10, 3, 10, 0, tzinfo=dt_tz.utc)
        with patch.dict(os.environ, KEYS):
            states = {s["source"]: s for s in feed_states(now=saturday)}
        self.assertEqual(states["alpha_vantage"]["state"], "never")
        self.assertEqual(states["oanda_stream"]["state"], "red")
