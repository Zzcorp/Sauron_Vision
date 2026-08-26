"""The ticker stops depending on a duplicate row to know it is stale.

The crypto scraper truncated its urls to 200 characters against a
500-character unique column, so it created a SECOND row for every
article the main scraper had already stored. `stored > 0` on nearly
every run is what fired the ticker's "new news" push. Fixing the
truncation — one article, one row — silenced the push, and the marquee
sat quiet until a page reload.

The push was never the right sole trigger: it fires only when THIS run
created rows, while the ticker shows the platform's recent news, which
other scrapers and the analyst pass also change. So both live strips
sweep on their own now, the way every other live surface here does.

Run with:  python manage.py test tests.test_ticker_liveness
"""
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase


def _shell():
    return (Path(settings.BASE_DIR) / "templates" / "base.html").read_text(
        encoding="utf-8")


class TheStripsAskForThemselvesTests(TestCase):
    def test_the_ticker_sweeps_without_being_told(self):
        """A headline can reach the platform without this run creating a
        row — the analyst pass fills a summary, another scraper got there
        first, a dedupe collapses the copy."""
        shell = _shell()
        seg = shell.split("function refreshTicker()")[1][:2400]
        self.assertIn("setInterval", seg)
        self.assertIn("document.hidden", seg)
        self.assertIn("refreshTicker();", seg)

    def test_the_ticker_catches_up_when_the_tab_comes_back(self):
        """Nobody reads a background tab, so the sweep skips it — which
        means returning to the tab must ask immediately."""
        shell = _shell()
        seg = shell.split("function refreshTicker()")[1][:2400]
        self.assertIn("visibilitychange", seg)
        self.assertIn("visibilityState === 'visible'", seg)

    def test_the_rail_sweeps_too(self):
        shell = _shell()
        seg = shell.split("function refreshSignalRail()")[1][:4200]
        self.assertIn("setInterval", seg)
        self.assertIn("refreshSignalRail();", seg)

    def test_both_strips_revive_when_the_gate_lifts(self):
        """Every poller on this platform answers sv:pin-unlocked — a
        strip that stayed asleep after an unlock would be stale exactly
        when the operator came back to work."""
        shell = _shell()
        for fn in ("refreshTicker", "refreshSignalRail"):
            seg = shell.split("function %s()" % fn)[1][:4200]
            self.assertIn("sv:pin-unlocked", seg, fn)

    def test_the_sweep_is_slow_enough_to_be_free(self):
        """Five minutes, not five seconds: this is a marquee of recent
        news, not a quote feed."""
        shell = _shell()
        seg = shell.split("function refreshTicker()")[1][:2400]
        self.assertIn("300000", seg)


class TheNewsPushStillFiresTests(TestCase):
    """The sweep is the safety net, not a replacement — an arriving
    headline should still reach an open page at once."""

    def setUp(self):
        # The task is @guarded_task: a disabled component skips before it
        # does anything, which would make both assertions below vacuous.
        from core.platform_control import PlatformComponent, seed_components
        seed_components()
        PlatformComponent.objects.filter(
            key__in=["platform_master", "scraper_crypto_news"]).update(
            is_enabled=True)

    def test_a_scrape_that_stored_rows_announces_itself(self):
        from unittest.mock import patch

        from market_data.tasks import fetch_crypto_news_task
        with patch("market_data.adapters.crypto_news.fetch_crypto_news",
                   return_value={"parsed": 5, "stored": 2}), \
                patch("dashboard.consumers.push_news_notification") as push:
            fetch_crypto_news_task()
        push.assert_called_once()
        self.assertEqual(push.call_args[0][0]["count"], 2)

    def test_a_dedupe_bound_run_is_silent_and_that_is_fine_now(self):
        """Nothing new was stored, so there is nothing to announce — the
        sweep covers the case the push cannot."""
        from unittest.mock import patch

        from market_data.tasks import fetch_crypto_news_task
        with patch("market_data.adapters.crypto_news.fetch_crypto_news",
                   return_value={"parsed": 25, "stored": 0}), \
                patch("dashboard.consumers.push_news_notification") as push:
            out = fetch_crypto_news_task()
        push.assert_not_called()
        self.assertEqual(out.get("parsed"), 25)


class TheTickerPartialStillAnswersTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("tick_u",
                                                         password="x")
        self.client.force_login(self.user)

    def test_the_partial_the_sweep_fetches_exists(self):
        """A sweep pointed at a dead endpoint is a slower way to be
        stale."""
        resp = self.client.get("/partials/ticker/")
        self.assertEqual(resp.status_code, 200)

    def test_a_fresh_article_reaches_the_partial(self):
        from django.utils import timezone

        from scraping.models import NewsArticle
        NewsArticle.objects.create(
            title="Copper squeezes shorts", source="Reuters",
            url="https://example.com/tick-1",
            published_at=timezone.now(), content_summary="x")
        body = self.client.get("/partials/ticker/").content.decode()
        self.assertIn("Copper squeezes shorts", body)
