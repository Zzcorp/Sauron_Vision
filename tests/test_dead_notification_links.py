"""Notification links that were shipped pointing at pages that never existed.

The producers were fixed and `Notification.safe_url` now guards the write
side — but the rows already in the database kept their dead links, and the
repair lived in a management command nobody had reason to run. The operator
met "Market anomaly alert → /market-data/ → Not Found" again after the code
fix had shipped.

Two layers now: a data migration repairs the stored rows on deploy, and the
dead paths resolve to their real destinations so the copies already sent to
Telegram, email and browser history stop 404ing too.

Run with:  python manage.py test tests.test_dead_notification_links
"""
from django.contrib.auth.models import User
from django.test import TestCase


class DeadPathsNowResolveTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user("deadlink_u"))

    def test_market_data_goes_to_the_quotes_page(self):
        r = self.client.get("/market-data/")
        self.assertEqual(r.status_code, 301)
        self.assertEqual(r["Location"], "/quotes/")

    def test_dashboard_goes_to_the_dashboard(self):
        r = self.client.get("/dashboard/")
        self.assertEqual(r.status_code, 301)
        self.assertEqual(r["Location"], "/")

    def test_the_destinations_are_real_pages(self):
        """Not a 404 and not a redirect back to a dead path — a real page
        or the app's own onboarding bounce."""
        for url in ("/quotes/", "/"):
            with self.subTest(url=url):
                r = self.client.get(url)
                self.assertIn(r.status_code, (200, 302))
                if r.status_code == 302:
                    self.assertNotIn(r["Location"], ("/market-data/",
                                                     "/dashboard/"))


class MigrationRepairsStoredRowsTests(TestCase):
    """The migration is what makes this fix arrive without anyone running
    a command. These pin its map against the command's and against the
    URLs that actually resolve."""

    def test_the_migration_and_the_command_agree(self):
        from importlib import import_module

        from alerts.management.commands.repair_notification_urls import REWRITES
        mig = import_module(
            "alerts.migrations.0009_repair_dead_notification_urls")
        self.assertEqual(set(mig.REWRITES), set(REWRITES),
                         "one map drifting from the other means a link the "
                         "deploy repairs and the command restores, or vice versa")

    def test_every_rewrite_target_resolves(self):
        from django.urls import Resolver404, resolve
        from importlib import import_module

        mig = import_module(
            "alerts.migrations.0009_repair_dead_notification_urls")
        for bad, good in mig.REWRITES.items():
            with self.subTest(bad=bad):
                try:
                    resolve(good)
                except Resolver404:  # pragma: no cover - assertion reports
                    self.fail(f"{bad} is repaired to {good}, which 404s too")

    def test_a_producer_writing_the_dead_path_is_still_corrected(self):
        """safe_url must keep its opinion even though the path resolves
        now: a stored notification carries the real page, not the shim."""
        from alerts.models import Notification
        self.assertEqual(Notification.safe_url("/market-data/"), "/quotes/")
        self.assertEqual(Notification.safe_url("/no-such-page-at-all/"), "")

    def test_the_repair_and_the_write_side_cover_the_same_dead_paths(self):
        """They may send /dashboard/ to different pages — old rows carrying
        it came from the briefing producers, while a NEW link saying
        "dashboard" means the dashboard — but neither may miss a dead path
        the other knows about."""
        from importlib import import_module

        from alerts.models import Notification
        mig = import_module(
            "alerts.migrations.0009_repair_dead_notification_urls")
        self.assertEqual(set(Notification.LEGACY_URL_REWRITES),
                         set(mig.REWRITES))
        self.assertEqual(Notification.LEGACY_URL_REWRITES["/market-data/"],
                         mig.REWRITES["/market-data/"])
