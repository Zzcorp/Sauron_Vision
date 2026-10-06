"""THE HEALTH DIGEST SAYS WHAT IS WRONG, IN WORDS THE OPERATOR CAN ACT ON
(2026-10-06).

The morning digest of 2026-10-06 carried four lines, and the operator
read three of them wrong because the platform had said them wrong:

  * BREAKING NEWS — "handled 25 rows and stored none". The headlines were
    arriving; the body fetcher (the row's second writer) had asked
    twenty-five paywalled pages and kept nothing, and the counts' sentence
    read as the news having stopped. Worse, the same twenty-five pages
    were asked again every ten minutes for three days. Now a publisher's
    no is remembered (BODY_REFUSED_KEY) and changes nothing on the row
    (idle); the road's failures are a warning in the task's own words,
    which the gate believes (judge_result on a declared warning).
  * SOCIAL SENTIMENT — "ran and produced nothing". StockTwits had refused
    every call from the box; the verdict was a quiet market's. The scraper
    counts its refusals and the task names the blocked host.
  * TRADINGVIEW IDEAS — "answered no data for 20/20 symbols". Half the
    seeded book is on the NYSE and every one of those was asked for as
    NASDAQ:<symbol>, a symbol the scanner does not know. The exchange the
    catalogue holds now picks the venue.
  * FINNHUB STREAM — silent, with an empty log. Every failed LiveQuote
    write went to log.debug (deleted in production) on a task nobody
    held, and a database connection that died under the stream failed
    every write from then on. The finnhub and OANDA streamers now have the
    futures streamer's mouth — a loud first failure, a heartbeat, a
    reconnect.
"""
import asyncio
import logging
import re
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest import mock
from unittest.mock import patch

import requests
from asgiref.sync import async_to_sync
from django.conf import settings
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.utils import timezone


def _enable(*keys):
    from core.platform_control import PlatformComponent
    for key in ("platform_master",) + keys:
        PlatformComponent.objects.update_or_create(
            key=key, defaults={"name": key, "category": "scraper",
                               "is_enabled": True})


def _instrument(symbol, asset_class="stock", *, exchange="", priced=False):
    from instruments.models import Instrument
    inst = Instrument.objects.create(
        symbol=symbol, name=f"{symbol} Inc", asset_class=asset_class,
        exchange=exchange, is_active=True)
    if priced:
        from market_data.models import PriceData
        PriceData.objects.create(
            instrument=inst, timeframe="1d", timestamp=timezone.now(),
            open=Decimal("1"), high=Decimal("2"), low=Decimal("1"),
            close=Decimal("2"), volume=100, source="test")
    return inst


# ── The gate believes a declared warning's words ─────────────────────────

class TheGateBelievesADeclaredWarningTests(SimpleTestCase):

    def test_a_warning_with_a_reason_is_reported_in_those_words(self):
        from core.task_gate import judge_result
        words = "25 article bodies tried, none kept — the headlines still arrive"
        self.assertEqual(judge_result({"status": "warning", "reason": words}),
                         ("warning", words))
        self.assertEqual(judge_result({"status": "warning", "message": words}),
                         ("warning", words))

    def test_a_bare_warning_still_falls_through_to_the_counts(self):
        from core.task_gate import judge_result
        self.assertEqual(judge_result({"status": "warning", "parsed": 3,
                                       "stored": 0}),
                         ("warning", "handled 3 rows and stored none"))

    def test_a_missing_credential_still_wins(self):
        """check_economic_calendar declares `warning` with `skipped` set:
        the not-configured verdict is the one that names what to DO."""
        from core.task_gate import judge_result
        self.assertEqual(judge_result({"status": "warning",
                                       "skipped": "no_api_key",
                                       "reason": "something else"}),
                         ("warning", "not configured: no_api_key"))


# ── The body fetcher's verdict, in its own words ──────────────────────────

def _article(url, *, age_hours=1.0):
    from scraping.models import NewsArticle
    return NewsArticle.objects.create(
        url=url, title="T", source="Test",
        published_at=timezone.now() - timedelta(hours=age_hours),
        content_summary="s", raw_content="")


class TheReasonKindsTests(SimpleTestCase):

    def test_the_road_and_the_publishers_are_told_apart(self):
        from scraping.tasks import _body_reason_kind as kind
        for reason, want in (
                ("ok", "ok"),
                ("fetch failed: ConnectionError", "transport"),
                ("deadline (30s)", "transport"),
                ("read failed: ChunkedEncodingError", "transport"),
                ("http 503", "transport"),
                ("error: RuntimeError", "transport"),
                ("http 403", "refusal"),
                ("http 404", "refusal"),
                ("robots", "refusal"),
                ("too short (12 chars) — paywall or wall", "refusal"),
                ("content-type application/pdf", "refusal"),
                ("private address", "refusal"),
                ("too many redirects (>5)", "refusal")):
            self.assertEqual(kind(reason), want, reason)

    def test_the_words_fold_the_reasons_largest_first(self):
        from scraping.tasks import _body_reason_words as words
        self.assertEqual(
            words({"too short (12 chars) — paywall or wall": 2,
                   "too short (300 chars) — paywall or wall": 1,
                   "robots": 1, "fetch failed: ConnectionError": 3}),
            "paywall or wall 3, unreachable 3, robots 1")
        self.assertEqual(words({}), "")

    def test_a_cache_that_cannot_be_read_remembers_nothing(self):
        from scraping.tasks import _bodies_refused, _remember_refusal
        with patch("django.core.cache.cache.get_many",
                   side_effect=RuntimeError("redis down")):
            self.assertEqual(_bodies_refused([1, 2]), set())
        with patch("django.core.cache.cache.set",
                   side_effect=RuntimeError("redis down")):
            _remember_refusal(1, "robots", 72)   # logged, never raised
        self.assertEqual(_bodies_refused([]), set())


class TheBodiesVerdictIsInItsOwnWordsTests(TestCase):

    def setUp(self):
        from core.platform_control import PlatformComponent
        cache.clear()
        _enable()
        self.then = timezone.now() - timedelta(minutes=4)
        PlatformComponent.objects.update_or_create(
            key="scraper_news",
            defaults={"name": "Breaking News", "category": "scraper",
                      "is_enabled": True, "last_status": "error",
                      "last_message": "rss: feed.example.com answered 503",
                      "last_run_at": self.then, "run_count": 9,
                      "error_count": 1})

    def _run(self, fake, **kw):
        from scraping.tasks import fetch_news_bodies
        with patch("scraping.article_body.fetch_article_body",
                   side_effect=fake) as f:
            out = fetch_news_bodies(**kw)
        return out, f

    def _row(self):
        from core.platform_control import PlatformComponent
        return PlatformComponent.objects.get(key="scraper_news")

    def test_every_publisher_refused_is_idle_and_remembered(self):
        _article("https://example.com/1")
        _article("https://example.com/2")
        paywall = lambda url, **kw: ("", "too short (12 chars) — paywall or wall")  # noqa: E731
        out, f = self._run(paywall)
        self.assertEqual(f.call_count, 2)
        self.assertIn("2 article bodies tried, none kept", out["idle"])
        self.assertIn("paywall or wall 2", out["idle"])
        self.assertIn("headlines still arrive", out["idle"])
        self.assertNotIn("attempted", out)
        # the row is the news's, and nothing about the news changed
        row = self._row()
        self.assertEqual((row.last_status, row.last_message, row.run_count),
                         ("error", "rss: feed.example.com answered 503", 9))
        # a publisher's no is not asked again
        out2, f2 = self._run(paywall)
        f2.assert_not_called()
        self.assertIn("2 refused by their publishers, not asked again",
                      out2["idle"])
        self.assertEqual(out2["refused_remembered"], 2)

    def test_the_road_is_a_warning_in_the_tasks_words(self):
        from core.task_gate import judge_result
        for i, host in enumerate("abcde"):
            _article(f"https://{host}.example.com/{i}", age_hours=1 + i)

        def road(url, **kw):
            if "d.example" in url or "e.example" in url:
                return "", "robots"
            return "", "fetch failed: ConnectionError"

        out, f = self._run(road)
        self.assertEqual(out["status"], "warning")
        self.assertIn("5 article bodies tried, none kept", out["reason"])
        self.assertIn("3 host(s) unreachable or timed out", out["reason"])
        self.assertIn("unreachable 3", out["reason"])
        self.assertIn("the headlines still arrive", out["reason"])
        self.assertEqual(judge_result(out), ("warning", out["reason"]))
        row = self._row()
        self.assertEqual(row.last_status, "warning")
        self.assertIn("article bodies", row.last_message)
        self.assertNotIn("handled", row.last_message)
        # the road is asked again next pass; the publishers' no is not
        out2, f2 = self._run(road)
        self.assertEqual(f2.call_count, 3)
        self.assertEqual(out2["refused_remembered"], 2)

    def test_a_refused_majority_is_idle_and_the_road_is_retried(self):
        _article("https://a.example.com/1", age_hours=1)
        _article("https://b.example.com/2", age_hours=2)
        _article("https://c.example.com/3", age_hours=3)

        def mixed(url, **kw):
            if "a.example" in url:
                return "", "deadline (30s)"
            return "", "http 403"

        out, _f = self._run(mixed)
        self.assertIn("3 article bodies tried, none kept", out["idle"])
        self.assertIn("http 403 2", out["idle"])
        self.assertIn("the 2 refused are not asked again", out["idle"])
        self.assertEqual(self._row().last_status, "error")
        out2, f2 = self._run(mixed)
        self.assertEqual(f2.call_count, 1)
        self.assertEqual(f2.call_args[0][0], "https://a.example.com/1")

    def test_a_dead_link_or_two_is_not_the_road(self):
        """One unreachable host in a batch of two is a dead link: idle,
        nothing remembered, asked again next pass."""
        _article("https://a.example.com/1", age_hours=1)
        _article("https://b.example.com/2", age_hours=2)
        dead = lambda url, **kw: ("", "fetch failed: ConnectionError")  # noqa: E731
        out, _f = self._run(dead)
        self.assertNotIn("status", {k: v for k, v in out.items()
                                    if v == "warning"})
        self.assertIn("2 article bodies tried, none kept (unreachable 2)",
                      out["idle"])
        self.assertNotIn("not asked again", out["idle"])
        self.assertEqual(self._row().last_status, "error")
        _out2, f2 = self._run(dead)
        self.assertEqual(f2.call_count, 2)

    def test_a_batch_that_filled_some_is_a_success_with_the_counts(self):
        from core.task_gate import judge_result
        from scraping.models import NewsArticle
        a = _article("https://a.example.com/1", age_hours=1)
        _article("https://b.example.com/2", age_hours=2)

        def some(url, **kw):
            return ("the body", "ok") if "a.example" in url else ("", "robots")

        out, _f = self._run(some)
        self.assertEqual((out["attempted"], out["stored"], out["filled"]),
                         (2, 1, 1))
        self.assertNotIn("idle", out)
        self.assertEqual(judge_result(out), ("success", "handled 2, stored 1"))
        self.assertEqual(self._row().last_status, "success")
        self.assertEqual(NewsArticle.objects.get(pk=a.pk).raw_content,
                         "the body")

    def test_the_batch_is_filled_past_the_remembered_refusals(self):
        """Four remembered refusals at the top of the queue must not starve
        the batch: the candidates are read BODY_CANDIDATE_FACTOR deep."""
        for i in range(4):
            _article(f"https://refused.example.com/{i}", age_hours=1 + i * 0.1)
        _article("https://fresh.example.com/5", age_hours=2)
        self._run(lambda url, **kw: ("", "http 403"), limit=4)
        out, f = self._run(lambda url, **kw: ("the body", "ok"), limit=2)
        self.assertEqual(f.call_count, 1)
        self.assertEqual(f.call_args[0][0], "https://fresh.example.com/5")
        self.assertEqual(out["filled"], 1)


# ── StockTwits: a blocked host is not a quiet market ─────────────────────

def _resp(status, payload=None):
    m = mock.MagicMock()
    m.status_code = status
    m.json.return_value = payload if payload is not None else {}
    return m


class StockTwitsRefusalsAreCountedTests(SimpleTestCase):

    def setUp(self):
        from scraping.scrapers import stocktwits as st
        st.reset_refusals()
        limiter = patch("core.rate_limiter.rate_limiter.wait_if_needed")
        limiter.start()
        self.addCleanup(limiter.stop)
        self.addCleanup(st.reset_refusals)

    def test_a_403_is_a_refusal_with_words(self):
        from scraping.scrapers import stocktwits as st
        with patch("scraping.scrapers.stocktwits.requests.get",
                   return_value=_resp(403)):
            self.assertIsNone(st._get("https://api.stocktwits.com/x"))
        self.assertEqual(st.refusals(),
                         {"calls": 1, "refused": 1, "last": "HTTP 403"})

    def test_a_429_and_a_timeout_have_their_own_words(self):
        from scraping.scrapers import stocktwits as st
        with patch("scraping.scrapers.stocktwits.requests.get",
                   return_value=_resp(429)):
            st._get("https://api.stocktwits.com/x")
        self.assertEqual(st.refusals()["last"], "HTTP 429 (rate limit)")
        with patch("scraping.scrapers.stocktwits.requests.get",
                   side_effect=requests.exceptions.Timeout("slow")):
            st._get("https://api.stocktwits.com/x")
        self.assertEqual(st.refusals(),
                         {"calls": 2, "refused": 2, "last": "timed out"})

    def test_an_answer_is_not_a_refusal_and_reset_forgets(self):
        from scraping.scrapers import stocktwits as st
        with patch("scraping.scrapers.stocktwits.requests.get",
                   return_value=_resp(200, {"response": {"status": 200}})):
            self.assertEqual(st._get("https://api.stocktwits.com/x"),
                             {"response": {"status": 200}})
        self.assertEqual(st.refusals(), {"calls": 1, "refused": 0, "last": ""})
        st.reset_refusals()
        self.assertEqual(st.refusals(), {"calls": 0, "refused": 0, "last": ""})


class ABlockedHostIsAnErrorNotAQuietMarketTests(TestCase):

    def setUp(self):
        from core.platform_control import seed_components
        seed_components()
        _enable("scraper_sentiment")
        limiter = patch("core.rate_limiter.rate_limiter.wait_if_needed")
        limiter.start()
        self.addCleanup(limiter.stop)

    def _run(self, response):
        with patch("scraping.scrapers.reddit_sentiment.reddit_unavailable_reason",
                   return_value="reddit_no_credentials"), \
             patch("scraping.scrapers.stocktwits.requests.get",
                   return_value=response):
            from scraping.tasks import fetch_social_sentiment
            return fetch_social_sentiment()

    def test_every_call_refused_names_the_blocked_host(self):
        from core.task_gate import judge_result
        _instrument("MSFT", priced=True)
        out = self._run(_resp(403))
        # the trending list and MSFT's stream: two calls, both refused
        self.assertEqual((out["stocktwits_calls"], out["stocktwits_refused"],
                          out["stored"]), (2, 2, 0))
        self.assertEqual(out["status"], "error")
        self.assertIn("StockTwits refused 2 of 2 calls (last: HTTP 403)",
                      out["error"])
        self.assertIn("blocked or rate-limited from this host", out["error"])
        self.assertEqual(judge_result(out)[0], "error")

    def test_a_pass_with_nothing_to_walk_keeps_the_counts_verdict(self):
        """No refusal, nothing stored: the counts still say "ran and
        produced nothing", and the words for that are the gate's."""
        from core.task_gate import judge_result
        out = self._run(_resp(200, {"response": {"status": 200},
                                    "symbols": []}))
        self.assertEqual(out["status"], "success")
        self.assertNotIn("error", out)
        self.assertEqual(out["stocktwits_refused"], 0)
        self.assertEqual(judge_result(out),
                         ("warning", "ran and produced nothing"))


# ── TradingView: the catalogue's exchange picks the venue ────────────────

class TheScannerIsAskedOnTheCataloguesExchangeTests(SimpleTestCase):

    def test_a_stock_goes_to_its_own_exchange(self):
        from scraping.scrapers.tradingview import _resolve_tv_symbol as r
        self.assertEqual(r("JPM", "stock", "NYSE"), "NYSE:JPM")
        self.assertEqual(r("XOM", "stock", "nyse"), "NYSE:XOM")
        self.assertEqual(r("AAPL", "stock", "NASDAQ"), "NASDAQ:AAPL")
        self.assertEqual(r("IWM", "etf", "NYSE"), "NYSE:IWM")
        self.assertEqual(r("SAP", "stock", "XETRA"), "XETR:SAP")
        self.assertEqual(r("SHEL", "stock", "LSE"), "LSE:SHEL")
        self.assertEqual(r("MC", "stock", "EURONEXT"), "EURONEXT:MC")

    def test_the_hand_map_and_the_fallback_still_hold(self):
        from scraping.scrapers.tradingview import _resolve_tv_symbol as r
        self.assertEqual(r("SPY", "etf", "NYSE"), "AMEX:SPY")
        self.assertEqual(r("AAPL", "stock", ""), "NASDAQ:AAPL")
        self.assertEqual(r("JPM", "stock", "SOMEWHERE"), "NASDAQ:JPM")
        self.assertEqual(r("EURUSD", "forex", "FOREX"), "FX:EURUSD")
        self.assertEqual(r("ADAUSD", "crypto", "CRYPTO"), "BINANCE:ADAUSDT")
        self.assertEqual(r("NYSE:JPM", "stock", "NASDAQ"), "NYSE:JPM")

    def test_the_fetch_asks_for_the_venue_spelling(self):
        from scraping.scrapers.tradingview import fetch_technical_analysis
        with patch("core.rate_limiter.rate_limiter.wait_if_needed"), \
             patch("scraping.scrapers.tradingview.requests.post",
                   side_effect=requests.exceptions.ConnectionError("x")):
            out = fetch_technical_analysis("JPM", asset_class="stock",
                                           exchange="NYSE")
        self.assertEqual(out["tv_symbol"], "NYSE:JPM")
        self.assertNotIn("recommendation_value", out)


class TheExchangeTravelsWithTheSymbolTests(TestCase):

    def setUp(self):
        _enable("scraper_tradingview")
        self.insts = [_instrument("JPM", "stock", exchange="NYSE"),
                      _instrument("AAPL", "stock", exchange="NASDAQ")]

    def test_the_task_passes_the_catalogues_exchange(self):
        with patch("scraping.tasks._scan_universe", return_value=self.insts), \
             patch("scraping.scrapers.tradingview.fetch_technical_analysis",
                   return_value={"recommendation_value": 0.3}) as fta:
            from scraping.tasks import fetch_tradingview_ideas
            out = fetch_tradingview_ideas()
        self.assertEqual((out["status"], out["answered"]), ("success", 2))
        self.assertEqual(fta.call_args_list[0].kwargs["exchange"], "NYSE")
        self.assertEqual(fta.call_args_list[1].kwargs["exchange"], "NASDAQ")


# ── The finnhub and OANDA streamers have a mouth ─────────────────────────

def _cmd(name):
    return (Path(settings.BASE_DIR) / "market_data" / "management"
            / "commands" / (name + ".py")).read_text(encoding="utf-8")


class _FreshStats:
    """STATS is module state shared by one streamer per container. Tests
    must not inherit each other's counts."""
    module = None

    def setUp(self):
        super().setUp()
        self._saved = dict(self.module.STATS)
        for key in self.module.STATS:
            self.module.STATS[key] = 0

    def tearDown(self):
        self.module.STATS.clear()
        self.module.STATS.update(self._saved)
        super().tearDown()


class TheStreamersSourceTests(SimpleTestCase):

    def test_no_streamer_swallows_a_failed_write_at_debug(self):
        for name in ("stream_finnhub", "stream_oanda"):
            src = _cmd(name)
            self.assertNotIn('log.debug("update_live_quote: %s", e)', src, name)
            self.assertNotIn('log.debug("tick: %s", e)', src, name)
            self.assertIn("_fire(update_live_quote(", src, name)
            self.assertIsNone(
                re.search(r"asyncio\.create_task\(\s*update_live_quote\(", src),
                f"{name}: the LiveQuote write is still fired as a task "
                f"nobody holds")
            self.assertIn("_fire(_heartbeat(stop))", src, name)
            self.assertIn("close_old_connections", src, name)

    def test_the_connect_line_reaches_production_logs(self):
        """The root logger sits at WARNING in production: an INFO connect
        line is why a twelve-hour-old container's log was empty."""
        self.assertIn('log.warning("finnhub: connecting', _cmd("stream_finnhub"))

    def test_the_other_pins_still_hold(self):
        """What test_feed_change_truth and test_paper_market_hours pin on
        these files is unchanged by the mouth."""
        self.assertIn("broadcast(sym, last, None, vol)", _cmd("stream_finnhub"))
        self.assertIn("broadcast(sym, mid, None,", _cmd("stream_oanda"))
        self.assertIn("update_live_quote(sym, bid, ask)", _cmd("stream_oanda"))


class TheFinnhubStreamerSpeaksTests(_FreshStats, TestCase):
    from market_data.management.commands import stream_finnhub as module

    def setUp(self):
        super().setUp()
        _instrument("AAPL", "stock", exchange="NASDAQ")

    def test_a_failed_write_warns_names_the_symbol_and_reconnects(self):
        fh = self.module
        with mock.patch("market_data.quotes.write_quote",
                        side_effect=ValueError("connection already closed")), \
             mock.patch("django.db.close_old_connections") as reconnect:
            with self.assertLogs(fh.log, level=logging.WARNING) as caught:
                ok = async_to_sync(fh.update_live_quote)("AAPL", 190.5, 10)
        self.assertFalse(ok)
        self.assertEqual(fh.STATS["quotes_failed"], 1)
        joined = "\n".join(caught.output)
        self.assertIn("AAPL", joined)
        self.assertIn("ValueError", joined)
        self.assertIn("connection already closed", joined)
        reconnect.assert_called_once_with()

    def test_a_successful_write_is_counted(self):
        from market_data.models import LiveQuote
        fh = self.module
        ok = async_to_sync(fh.update_live_quote)("AAPL", 190.5, 10)
        self.assertTrue(ok)
        self.assertEqual(fh.STATS["quotes_written"], 1)
        self.assertEqual(
            LiveQuote.objects.get(instrument__symbol="AAPL").source,
            "finnhub_ws")

    def test_a_broken_feed_does_not_flood_but_does_not_hide(self):
        fh = self.module
        with self.assertLogs(fh.log, level=logging.WARNING) as caught:
            for n in range(1, 251):
                fh._report_failure("update_live_quote", "AAPL",
                                   ValueError("x"), n)
        self.assertEqual(len(caught.output), 3)
        self.assertIn("failure #1", caught.output[0])

    def test_the_heartbeat_speaks_when_nothing_arrives(self):
        fh = self.module

        async def _drive():
            stop = asyncio.Event()
            task = fh._fire(fh._heartbeat(stop))
            self.assertIn(task, fh._PENDING)
            await asyncio.sleep(0.05)
            stop.set()
            await task

        with mock.patch.object(fh, "HEARTBEAT_SEC", 0.01):
            with self.assertLogs(fh.log, level=logging.WARNING) as caught:
                asyncio.run(_drive())
        joined = "\n".join(caught.output)
        self.assertIn("0 trade prints", joined)
        self.assertIn("quotes 0 written / 0 failed", joined)
        self.assertIn("no trade print since the last line", joined)

    def test_the_heartbeat_line_counts_what_landed(self):
        fh = self.module
        fh.STATS.update(ticks=12, quotes_written=10, quotes_failed=2,
                        tick_errors=1)
        self.assertEqual(fh.heartbeat_line(),
                         "12 trade prints · quotes 10 written / 2 failed · "
                         "1 unparsed")


class TheOandaStreamerSpeaksTests(_FreshStats, TestCase):
    from market_data.management.commands import stream_oanda as module

    def setUp(self):
        super().setUp()
        _instrument("EURUSD", "forex", exchange="FOREX")

    def test_a_failed_write_warns_names_the_pair_and_reconnects(self):
        oa = self.module
        with mock.patch("market_data.quotes.write_quote",
                        side_effect=ValueError("connection already closed")), \
             mock.patch("django.db.close_old_connections") as reconnect:
            with self.assertLogs(oa.log, level=logging.WARNING) as caught:
                ok = async_to_sync(oa.update_live_quote)("EURUSD", 1.1, 1.1002)
        self.assertFalse(ok)
        self.assertEqual(oa.STATS["quotes_failed"], 1)
        joined = "\n".join(caught.output)
        self.assertIn("EURUSD", joined)
        self.assertIn("connection already closed", joined)
        reconnect.assert_called_once_with()

    def test_a_successful_write_is_counted(self):
        from market_data.models import LiveQuote
        oa = self.module
        ok = async_to_sync(oa.update_live_quote)("EURUSD", 1.1, 1.1002)
        self.assertTrue(ok)
        self.assertEqual(oa.STATS["quotes_written"], 1)
        self.assertEqual(
            LiveQuote.objects.get(instrument__symbol="EURUSD").source,
            "oanda_stream")

    def test_a_pair_the_catalogue_lacks_is_dropped_loudly_not_counted_failed(self):
        oa = self.module
        with self.assertLogs(oa.log, level=logging.WARNING) as caught:
            ok = async_to_sync(oa.update_live_quote)("XXX_YYY", 1.0, 1.0)
        self.assertFalse(ok)
        self.assertEqual((oa.STATS["quotes_failed"], oa.STATS["quotes_written"]),
                         (0, 0))
        self.assertIn("no Instrument for 'XXX_YYY'", "\n".join(caught.output))

    def test_the_heartbeat_speaks_when_nothing_arrives(self):
        oa = self.module

        async def _drive():
            stop = asyncio.Event()
            task = oa._fire(oa._heartbeat(stop))
            await asyncio.sleep(0.05)
            stop.set()
            await task

        with mock.patch.object(oa, "HEARTBEAT_SEC", 0.01):
            with self.assertLogs(oa.log, level=logging.WARNING) as caught:
                asyncio.run(_drive())
        joined = "\n".join(caught.output)
        self.assertIn("0 prices", joined)
        self.assertIn("no price since the last line", joined)
