"""News was the one high-volume writer with no retention at all.

Liquidations, funding, order books and intraday bars all prune nightly.
News never did — every scraper run appended forever, and `raw_content`
(the full scraped body) is nearly all of its weight.

The two rules here are shaped by what actually reads that data, which is
the part worth guarding: the analyst falls back to `raw_content` when a
summary is missing, the detail page renders the body, and notifications
deep-link to /news/<pk>/. A retention rule that ignored any of those three
would trade disk for a broken answer.

Run with:  python manage.py test tests.test_news_retention
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _article(title, *, days_ago, summary="a summary", body="the full body"):
    from scraping.models import NewsArticle
    return NewsArticle.objects.create(
        title=title, source="test",
        url=f"https://example.com/{title.replace(' ', '-')}-{days_ago}",
        published_at=timezone.now() - timedelta(days=days_ago),
        content_summary=summary, raw_content=body)


class BodyStrippingTests(TestCase):
    def test_an_old_summarised_body_is_stripped(self):
        from market_data.cleanup_tasks import cleanup_news_bodies
        old = _article("old news", days_ago=200)
        self.assertEqual(cleanup_news_bodies(), 1)
        old.refresh_from_db()
        self.assertEqual(old.raw_content, "")
        # Everything that answers a question survives.
        self.assertEqual(old.content_summary, "a summary")
        self.assertEqual(old.title, "old news")

    def test_a_recent_body_is_untouched(self):
        from market_data.cleanup_tasks import cleanup_news_bodies
        fresh = _article("todays news", days_ago=1)
        cleanup_news_bodies()
        fresh.refresh_from_db()
        self.assertEqual(fresh.raw_content, "the full body")

    def test_an_unsummarised_article_keeps_its_body(self):
        """The analyst reads `content_summary or raw_content[:2000]`. Strip
        the body of an article that never got a summary and there is
        nothing left to analyse OR to read."""
        from market_data.cleanup_tasks import cleanup_news_bodies
        raw_only = _article("never summarised", days_ago=400, summary="")
        cleanup_news_bodies()
        raw_only.refresh_from_db()
        self.assertEqual(raw_only.raw_content, "the full body")

    def test_it_is_idempotent(self):
        from market_data.cleanup_tasks import cleanup_news_bodies
        _article("old news", days_ago=200)
        self.assertEqual(cleanup_news_bodies(), 1)
        self.assertEqual(cleanup_news_bodies(), 0,
                         "a second pass must not rewrite rows it already emptied")


class ArticleDeletionTests(TestCase):
    def test_articles_past_the_window_are_removed(self):
        from market_data.cleanup_tasks import cleanup_news
        from scraping.models import NewsArticle
        _article("ancient", days_ago=500)
        _article("recent", days_ago=10)
        self.assertEqual(cleanup_news(), 1)
        self.assertEqual(
            list(NewsArticle.objects.values_list("title", flat=True)), ["recent"])

    def test_an_article_a_notification_links_to_is_kept_forever(self):
        """The platform spent a day repairing notification links that led
        nowhere. Deleting the article under a live link would put one back."""
        from alerts.models import Notification
        from market_data.cleanup_tasks import cleanup_news
        from scraping.models import NewsArticle
        linked = _article("cited by an alert", days_ago=900)
        user = User.objects.create_user("news_u")
        Notification.objects.create(
            user=user, notification_type="news", title="Critical news",
            url=f"/news/{linked.pk}/")
        self.assertEqual(cleanup_news(), 0)
        self.assertTrue(NewsArticle.objects.filter(pk=linked.pk).exists())

    def test_a_malformed_notification_url_cannot_break_the_sweep(self):
        from alerts.models import Notification
        from market_data.cleanup_tasks import cleanup_news
        _article("ancient", days_ago=500)
        user = User.objects.create_user("news_u2")
        for url in ("/news/", "/news/not-a-number/", "/news/12x/"):
            Notification.objects.create(
                user=user, notification_type="news", title="t", url=url)
        self.assertEqual(cleanup_news(), 1)

    def test_an_empty_table_is_a_no_op(self):
        from market_data.cleanup_tasks import cleanup_news
        self.assertEqual(cleanup_news(), 0)


class WiringTests(TestCase):
    def test_both_passes_run_in_the_nightly_sweep(self):
        """A retention rule nothing schedules is a comment."""
        from market_data.cleanup_tasks import nightly_cleanup_all
        out = nightly_cleanup_all()
        self.assertIn("news_bodies", out)
        self.assertIn("news", out)

    def test_the_windows_are_configurable_like_every_other_one(self):
        import os
        from unittest.mock import patch

        from market_data.cleanup_tasks import cleanup_news_bodies
        _article("sixty days old", days_ago=60)
        with patch.dict(os.environ, {"RETAIN_NEWS_RAW_DAYS": "30"}):
            self.assertEqual(cleanup_news_bodies(), 1)
