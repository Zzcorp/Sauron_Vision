"""What the ingest feeds SAY versus what actually happened.

Four silences are pinned here, and every one of them looked like health.

* Crypto articles were stamped with the time we polled. The timestamp was
  built with `tzinfo=timezone.utc` on django.utils.timezone, an attribute
  Django 5 removed, so it raised on every entry and a bare `except` fell
  back to now(). Nothing crashed, nothing logged, and every 24-hour window
  downstream read the wrong column as fact.
* A dead RSS host and a fully-deduplicated feed were the same event:
  feedparser returns zero entries for both and raises for neither.
* The StockTwits per-symbol pass filtered on is_watchlist, a flag nothing in
  the platform sets, and the trending pass spent its rate-limited calls on
  symbols outside the catalogue — so the one job that exists to guarantee a
  SentimentSnapshot could not produce one.
* A Reddit integration with no credentials returned [] exactly like a quiet
  hour on r/wallstreetbets.

Run with:  python manage.py test tests.test_feed_truth
"""
import os
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

ENTRY_PUBLISHED = (2026, 8, 20, 13, 45, 0, 0, 0, 0)


def _entry(n=0, published_parsed=ENTRY_PUBLISHED):
    entry = {
        "title": f"Bitcoin does something {n}",
        # Past 200 characters on purpose: the link is stored against a unique
        # 500-character column, and truncating it collapsed distinct articles.
        "link": "https://www.coindesk.com/markets/2026/08/20/story-{}/?{}".format(
            n, "utm_source=" + "x" * 200),
        "summary": "a summary",
    }
    if published_parsed is not None:
        entry["published_parsed"] = published_parsed
    return entry


def _feed(entries, bozo=0, bozo_exception=""):
    return SimpleNamespace(entries=list(entries), bozo=bozo,
                           bozo_exception=bozo_exception)


def _one_live_feed(entries):
    """feedparser stand-in: the first feed answers, the rest are silent.

    Returned as a callable so a single test can hold both cases — a feed
    with entries and a feed without — which is the distinction the scraper
    could not previously draw.
    """
    seen = []

    def parse(url):
        seen.append(url)
        if len(seen) == 1:
            return _feed(entries)
        return _feed([], bozo=1, bozo_exception="host does not resolve")

    return parse


class CryptoNewsTimestamps(TestCase):
    """published_at must be what the entry says, never when we asked."""

    def test_published_at_is_the_entrys_time_not_the_scrape_time(self):
        from market_data.adapters.crypto_news import fetch_crypto_news
        from scraping.models import NewsArticle

        with patch("market_data.adapters.crypto_news.feedparser.parse",
                   side_effect=_one_live_feed([_entry(1)])):
            result = fetch_crypto_news(max_per_feed=5)

        self.assertEqual(result["stored"], 1)
        article = NewsArticle.objects.get()
        self.assertEqual(
            article.published_at,
            datetime(2026, 8, 20, 13, 45, tzinfo=dt_timezone.utc))
        # The scrape time is minutes-to-months away from the entry time; the
        # bug made them identical to the second.
        self.assertNotEqual(article.published_at.date(),
                            timezone.now().date())

    def test_an_entry_with_no_date_falls_back_to_now(self):
        """A feed that genuinely does not say gets now() — and only then."""
        from market_data.adapters.crypto_news import fetch_crypto_news
        from scraping.models import NewsArticle

        before = timezone.now() - timedelta(seconds=1)
        with patch("market_data.adapters.crypto_news.feedparser.parse",
                   side_effect=_one_live_feed(
                       [_entry(2, published_parsed=None)])):
            fetch_crypto_news()

        self.assertGreaterEqual(NewsArticle.objects.get().published_at, before)

    def test_the_full_link_is_stored(self):
        """Truncating to 200 against a unique column merged distinct
        articles AND stored a link that does not resolve — and wrote a
        second row for an article fetch_rss_news had already saved."""
        from market_data.adapters.crypto_news import fetch_crypto_news
        from scraping.models import NewsArticle

        entry = _entry(3)
        with patch("market_data.adapters.crypto_news.feedparser.parse",
                   side_effect=_one_live_feed([entry])):
            fetch_crypto_news()

        self.assertEqual(NewsArticle.objects.get().url, entry["link"][:500])


class CryptoFeedHealth(TestCase):
    """A dead host and a quiet one are different facts."""

    def test_a_dead_feed_is_named_in_feeds_dead(self):
        from market_data.adapters.crypto_news import (CRYPTO_RSS_FEEDS,
                                                      fetch_crypto_news)

        with patch("market_data.adapters.crypto_news.feedparser.parse",
                   side_effect=_one_live_feed([_entry(4)])):
            result = fetch_crypto_news()

        self.assertEqual(result["feeds_ok"], 1)
        # Every feed but the first returned zero entries without raising.
        self.assertEqual(len(result["feeds_dead"]), len(CRYPTO_RSS_FEEDS) - 1)
        self.assertNotIn(next(iter(CRYPTO_RSS_FEEDS)), result["feeds_dead"])

    def test_a_deduplicated_feed_is_not_a_dead_feed(self):
        """Three of the five feeds are URLs fetch_rss_news already polls, so
        zero new rows is the normal outcome. It must still be visible that
        the host answered."""
        from market_data.adapters.crypto_news import fetch_crypto_news

        entry = _entry(5)
        with patch("market_data.adapters.crypto_news.feedparser.parse",
                   side_effect=_one_live_feed([entry])):
            fetch_crypto_news()
        with patch("market_data.adapters.crypto_news.feedparser.parse",
                   side_effect=_one_live_feed([entry])):
            second = fetch_crypto_news()

        self.assertEqual(second["parsed"], 1)
        self.assertEqual(second["stored"], 0)
        self.assertEqual(second["feeds_ok"], 1)

    def test_a_raising_feed_is_dead_not_silently_skipped(self):
        from market_data.adapters.crypto_news import (CRYPTO_RSS_FEEDS,
                                                      fetch_crypto_news)

        with patch("market_data.adapters.crypto_news.feedparser.parse",
                   side_effect=OSError("connection reset")):
            result = fetch_crypto_news()

        self.assertEqual(result["feeds_ok"], 0)
        self.assertEqual(len(result["feeds_dead"]), len(CRYPTO_RSS_FEEDS))


class CryptoNewsTaskReport(TestCase):
    """The task's own vocabulary — one done key, and the feed health."""

    def setUp(self):
        from core.platform_control import PlatformComponent, seed_components
        seed_components()
        PlatformComponent.objects.filter(
            key__in=["platform_master", "scraper_crypto_news"]).update(
            is_enabled=True)

    def _run(self, scraper_result):
        with patch("market_data.adapters.crypto_news.fetch_crypto_news",
                   return_value=scraper_result), \
             patch("dashboard.consumers.push_news_notification") as push:
            from market_data.tasks import fetch_crypto_news_task
            return fetch_crypto_news_task(), push

    def test_the_report_carries_the_feed_health_and_one_done_key(self):
        out, push = self._run({"parsed": 25, "stored": 2, "feeds_ok": 4,
                               "feeds_dead": ["theblock"]})

        self.assertEqual(out["articles"], 2)
        self.assertEqual(out["parsed"], 25)
        self.assertEqual(out["feeds_dead"], ["theblock"])
        # "stored" alongside "articles" would be counted twice: judge_result
        # sums every done key it finds, so the page would claim four rows.
        self.assertNotIn("stored", out)
        push.assert_called_once()

        from core.task_gate import judge_result
        status, message = judge_result(out)
        self.assertEqual(status, "success")
        self.assertIn("2", message)

    def test_a_bare_count_from_an_older_scraper_still_reports(self):
        out, push = self._run(3)
        self.assertEqual(out["articles"], 3)
        push.assert_called_once()

    def test_a_dry_pass_stays_silent(self):
        out, push = self._run({"parsed": 25, "stored": 0, "feeds_ok": 5,
                               "feeds_dead": []})
        self.assertEqual(out["articles"], 0)
        push.assert_not_called()


def _stream(symbol, bullish=2, bearish=1):
    """A StockTwits stream payload for one symbol."""
    messages = ([{"entities": {"sentiment": {"basic": "Bullish"}}}] * bullish
                + [{"entities": {"sentiment": {"basic": "Bearish"}}}] * bearish)
    return {"response": {"status": 200},
            "symbol": {"symbol": symbol, "title": symbol,
                       "watchlist_count": 7},
            "messages": messages}


def _stocktwits_api(trending_symbols=()):
    """Stand-in for stocktwits._get that records every URL it is asked for.

    The recording is the point: the trending pass used to spend a
    rate-limited call on symbols it could never store, and the only way to
    prove it no longer does is to count the calls.
    """
    calls = []

    def _get(url, params=None, timeout=15):
        calls.append(url)
        if url.endswith("trending/symbols.json"):
            return {"response": {"status": 200},
                    "symbols": [{"symbol": s, "title": s,
                                 "watchlist_count": 1}
                                for s in trending_symbols]}
        symbol = url.rsplit("/", 1)[-1][:-len(".json")]
        return _stream(symbol)

    return _get, calls


def _instrument(symbol, asset_class="stock", *, watchlist=False, priced=False):
    from instruments.models import Instrument
    from market_data.models import PriceData
    inst = Instrument.objects.create(
        symbol=symbol, name=f"{symbol} Inc", asset_class=asset_class,
        is_active=True, is_watchlist=watchlist)
    if priced:
        PriceData.objects.create(
            instrument=inst, timeframe="1d", timestamp=timezone.now(),
            open=Decimal("1"), high=Decimal("2"), low=Decimal("1"),
            close=Decimal("2"), volume=100, source="test")
    return inst


class StockTwitsUniverse(TestCase):
    """The per-symbol pass has to walk a universe that actually exists."""

    def test_an_empty_watchlist_still_produces_a_universe(self):
        """Not one of the 179 active instruments has is_watchlist set, so
        filtering on it alone meant this function could never return a row —
        the one pass that exists to guarantee a snapshot."""
        from scraping.models import SentimentSnapshot
        from scraping.scrapers.stocktwits import fetch_watchlist_sentiment

        _instrument("MSFT", priced=True)
        get, calls = _stocktwits_api()

        with patch("scraping.scrapers.stocktwits._get", side_effect=get):
            covered = fetch_watchlist_sentiment()

        self.assertEqual(covered, 1)
        self.assertEqual(len(calls), 1)
        snap = SentimentSnapshot.objects.get(source="stocktwits")
        self.assertEqual(snap.instrument.symbol, "MSFT")
        self.assertEqual(snap.bullish_count, 2)

    def test_a_starred_watchlist_wins_over_the_fallback(self):
        from scraping.scrapers.stocktwits import _sentiment_universe

        _instrument("MSFT", priced=True)
        _instrument("AAPL", watchlist=True, priced=True)

        symbols, universe = _sentiment_universe(8)
        self.assertEqual(symbols, ["AAPL"])
        self.assertEqual(universe, "watchlist")

    def test_the_fallback_skips_crypto_and_priceless_equities(self):
        """StockTwits spells crypto BTC.X, which the catalogue does not, and
        an instrument with no price history is nothing we can say anything
        about — either would spend a call for a row that cannot land."""
        from scraping.scrapers.stocktwits import _sentiment_universe

        _instrument("BTCUSD", asset_class="crypto", priced=True)
        _instrument("ZZZZ")  # active, no price history

        symbols, universe = _sentiment_universe(8)
        self.assertEqual(symbols, [])
        self.assertEqual(universe, "empty")

    def test_trending_spends_calls_only_on_catalogue_symbols(self):
        """parsed=30/stored=1 read as a permanent warning because the two
        numbers were counted on different universes."""
        from scraping.models import SentimentSnapshot
        from scraping.scrapers.stocktwits import fetch_trending

        _instrument("AAPL", priced=True)
        get, calls = _stocktwits_api(
            trending_symbols=["GME", "AAPL", "AMC", "SPCE"])

        with patch("scraping.scrapers.stocktwits._get", side_effect=get):
            results = fetch_trending()

        self.assertEqual([r["symbol"] for r in results], ["AAPL"])
        self.assertEqual(SentimentSnapshot.objects.count(), 1)
        # One trending call plus one stream call, not five.
        self.assertEqual(len(calls), 2)
        # What the caller counts as parsed is what we stored against.
        self.assertEqual(len(results), SentimentSnapshot.objects.count())


class RedditNotConfigured(TestCase):
    """Missing credentials must not look like a quiet news day."""

    def setUp(self):
        from core.platform_control import PlatformComponent, seed_components
        seed_components()
        PlatformComponent.objects.filter(
            key__in=["platform_master", "scraper_sentiment"]).update(
            is_enabled=True)

    def _run_social(self):
        with patch("scraping.scrapers.stocktwits.fetch_trending",
                   return_value=[]), \
             patch("scraping.scrapers.stocktwits.fetch_watchlist_sentiment",
                   return_value=0):
            from scraping.tasks import fetch_social_sentiment
            return fetch_social_sentiment()

    def test_missing_credentials_produce_the_skipped_marker(self):
        with patch.dict(os.environ, {"REDDIT_CLIENT_ID": "",
                                     "REDDIT_CLIENT_SECRET": ""}):
            out = self._run_social()

        self.assertEqual(out["skipped"], "reddit_no_credentials")
        self.assertEqual(out["reddit_skipped"], "reddit_no_credentials")

        from core.task_gate import judge_result
        status, message = judge_result(out)
        self.assertEqual(status, "warning")
        self.assertIn("not configured", message)
        self.assertIn("reddit_no_credentials", message)

    def test_the_reddit_path_survives_for_an_approved_operator(self):
        """The credentials may still be granted — the scraper is skipped,
        not removed."""
        with patch.dict(os.environ, {"REDDIT_CLIENT_ID": "id",
                                     "REDDIT_CLIENT_SECRET": "secret"}), \
             patch("scraping.scrapers.reddit_sentiment.fetch_reddit_sentiment",
                   return_value=[{"title": "a post"}]) as fetch:
            out = self._run_social()

        fetch.assert_called_once()
        self.assertNotIn("skipped", out)
        self.assertEqual(out["reddit"], 1)

    def test_the_scraper_and_the_report_agree_on_availability(self):
        """One gate: if the report says unconfigured the scraper must also
        decline, or the two drift and the page lies in the other direction."""
        from scraping.scrapers.reddit_sentiment import (
            fetch_reddit_sentiment, reddit_unavailable_reason)

        with patch.dict(os.environ, {"REDDIT_CLIENT_ID": "",
                                     "REDDIT_CLIENT_SECRET": ""}):
            self.assertEqual(reddit_unavailable_reason(),
                             "reddit_no_credentials")
            self.assertEqual(fetch_reddit_sentiment(), [])
