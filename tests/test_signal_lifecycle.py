"""Tests for the plain-Signal lifecycle beat task and Celery registration.

Run with:  python manage.py test tests.test_signal_lifecycle
"""
from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from tests.test_performance import _make_signal


def _quote(instrument, last):
    from market_data.models import LiveQuote
    quote, _ = LiveQuote.objects.update_or_create(
        instrument=instrument,
        defaults={"last": Decimal(last), "source": "test"},
    )
    return quote


class BeatScheduleRegistrationTests(SimpleTestCase):
    """Every beat entry must resolve to a task registered in the worker.

    autodiscover_tasks() only imports <app>.tasks; task modules outside that
    convention (signals.tasks_lifecycle, market_data.funding_alerts,
    market_data.cleanup_tasks) must be listed in app.conf.imports. This test
    simulates worker startup so a beat entry pointing at an unimported module
    fails here instead of dying as "Received unregistered task" in prod.
    """

    def test_every_beat_entry_is_registered(self):
        from config.celery import app
        app.loader.import_default_modules()
        app.finalize()
        registered = set(app.tasks.keys())
        missing = {
            name: entry["task"]
            for name, entry in app.conf.beat_schedule.items()
            if entry["task"] not in registered
        }
        self.assertEqual(missing, {})

    def test_default_queue_matches_documented_workers(self):
        # Workers are started with -Q fast,default / -Q slow,ai; unrouted
        # tasks must land on "default", not the implicit "celery" queue.
        from config.celery import app
        self.assertEqual(app.conf.task_default_queue, "default")


class RunSignalLifecycleTests(TestCase):
    def _run(self):
        from signals.tasks_lifecycle import run_signal_lifecycle
        return run_signal_lifecycle()

    def test_closes_signal_that_hit_target(self):
        sig = _make_signal(direction="bullish", entry="100", stop="95", target="110")
        _quote(sig.instrument, "111")
        counts = self._run()
        sig.refresh_from_db()
        self.assertFalse(sig.is_active)
        self.assertEqual(sig.outcome, "hit_target")
        self.assertEqual(sig.realized_r, 2.0)
        self.assertEqual(counts["closed"], 1)

    def test_active_signal_stays_open_and_tracks_extremes(self):
        sig = _make_signal(direction="bullish", entry="100", stop="95", target="110")
        _quote(sig.instrument, "104")
        counts = self._run()
        sig.refresh_from_db()
        self.assertTrue(sig.is_active)
        self.assertEqual(counts["evaluated"], 1)
        self.assertEqual(counts["closed"], 0)

    def test_signal_without_quote_counts_no_price(self):
        _make_signal(symbol="NOQUOTE", entry="100", stop="95", target="110")
        counts = self._run()
        self.assertEqual(counts["no_price"], 1)
        self.assertEqual(counts["closed"], 0)

    def test_one_bad_row_does_not_starve_the_pass(self):
        from unittest.mock import patch

        bad = _make_signal(symbol="BADROW", entry="100", stop="95", target="110")
        good = _make_signal(symbol="GOODROW", entry="100", stop="95", target="110")
        _quote(bad.instrument, "104")
        _quote(good.instrument, "111")

        import signals.performance as perf
        real = perf.evaluate_signal_outcome

        def flaky(signal, current_price=None):
            if signal.pk == bad.pk:
                raise RuntimeError("boom")
            return real(signal, current_price)

        with patch("signals.performance.evaluate_signal_outcome", side_effect=flaky):
            counts = self._run()

        good.refresh_from_db()
        self.assertFalse(good.is_active)
        self.assertEqual(counts["errors"], 1)
        self.assertEqual(counts["closed"], 1)


class BarFallbackTests(TestCase):
    """Quote-or-nothing pricing left signals immortal: LiveQuote pollers
    cover the watchlist, so an off-watchlist signal's quote path returned
    None every tick and even the 7-day TTL could never fire — crossed
    levels sat active in the rail for days. A recent 1h/4h bar close is the
    same mark the paper venue trades at, so the lifecycle now degrades to
    it exactly like PaperTrader.ticker does."""

    def _bar(self, instrument, close, minutes_ago=30, timeframe="1h"):
        from datetime import timedelta
        from django.utils import timezone
        from market_data.models import PriceData
        ts = timezone.now() - timedelta(minutes=minutes_ago)
        PriceData.objects.create(
            instrument=instrument, timeframe=timeframe, timestamp=ts,
            open=Decimal(str(close)), high=Decimal(str(close)),
            low=Decimal(str(close)), close=Decimal(str(close)),
            volume=0, source="test")

    @staticmethod
    def _fresh(sig):
        """Refetch, dropping Django's relation caches. Creating a LiveQuote
        against the same Instrument instance populates the reverse
        one-to-one cache, so the in-memory quote would mask the aged DB
        row — the lifecycle task always loads signals fresh, so the test
        must too."""
        from signals.models import Signal
        return Signal.objects.select_related("instrument").get(pk=sig.pk)

    def test_stale_quote_falls_back_to_a_recent_bar_close(self):
        from datetime import timedelta
        from django.utils import timezone
        from market_data.models import LiveQuote
        from signals.performance import evaluate_signal_outcome
        sig = _make_signal(symbol="BARFB", direction="bullish",
                           entry="100", stop="95", target="110")
        q = _quote(sig.instrument, "104")
        LiveQuote.objects.filter(pk=q.pk).update(
            updated_at=timezone.now() - timedelta(hours=2))
        self._bar(sig.instrument, 94)  # below the stop
        outcome = evaluate_signal_outcome(self._fresh(sig))
        self.assertEqual(outcome, "stopped_out")
        sig.refresh_from_db()
        self.assertFalse(sig.is_active)

    def test_a_bar_older_than_the_bound_does_not_resolve(self):
        from signals.performance import evaluate_signal_outcome
        sig = _make_signal(symbol="OLDBAR", direction="bullish",
                           entry="100", stop="95", target="110")
        self._bar(sig.instrument, 94, minutes_ago=7 * 60)  # past 6h bound
        self.assertIsNone(evaluate_signal_outcome(self._fresh(sig)))
        sig.refresh_from_db()
        self.assertTrue(sig.is_active)

    def test_a_fresh_quote_still_wins_over_bars(self):
        from signals.performance import evaluate_signal_outcome
        sig = _make_signal(symbol="QWINS", direction="bullish",
                           entry="100", stop="95", target="110")
        _quote(sig.instrument, "104")      # fresh, mid-range: stays active
        self._bar(sig.instrument, 94)      # bar says stopped — must lose
        self.assertEqual(evaluate_signal_outcome(self._fresh(sig)), "active")
