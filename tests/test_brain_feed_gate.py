"""The brain stops paying Opus rates to read a frozen frame.

`run_sauron_mind` fired hourly off the clock alone. When the 4h bar writer
stopped on a Thursday, the synthesizer went on publishing confident hourly
regime reads computed from Thursday's closes — flipping its own regime label
three times in 24 hours on data that had not moved, telling the operator to
"trade the Hurst number", and posting predictions that then graded
ungradeable (nothing had closed either) until its own trust score reached
zero. Twenty-four Opus calls a day, each wrong in a way no reader could see.

Two fixes, both pinned here: every probe now carries the age of its newest
bar, and a run whose probes are ALL stale is skipped rather than made.

Run with:  python manage.py test tests.test_brain_feed_gate
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.utils import timezone


def _instrument(symbol="AAPL", asset_class="stock", watch=True):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    if watch and not inst.is_watchlist:
        inst.is_watchlist = True
        inst.save(update_fields=["is_watchlist"])
    return inst


def _bars(inst, *, n=40, age_hours, timeframe="4h", step_hours=4):
    """`n` closes whose NEWEST is `age_hours` old."""
    from market_data.models import PriceData
    newest = timezone.now() - timedelta(hours=age_hours)
    for i in range(n):
        ts = newest - timedelta(hours=step_hours * i)
        px = Decimal(str(100 + (i % 7) - (i % 3)))     # not monotone
        PriceData.objects.update_or_create(
            instrument=inst, timeframe=timeframe, timestamp=ts,
            defaults={"open": px, "high": px + 1, "low": px - 1,
                      "close": px, "volume": 1000, "source": "test"})


class EveryProbeCarriesTheAgeOfItsNewestBarTests(TestCase):

    def _probes(self):
        from brain.synthesizer import _build_world_snapshot
        return _build_world_snapshot().get("regime_probes") or []

    def test_a_fresh_probe_reports_its_age_and_is_not_stale(self):
        _bars(_instrument("AAPL"), age_hours=2)
        probe = next(p for p in self._probes() if p["symbol"] == "AAPL")
        self.assertIsNotNone(probe["last_bar_age_hours"])
        self.assertLess(probe["last_bar_age_hours"], 4)
        self.assertFalse(probe["stale"])

    def test_a_frozen_frame_is_labelled_stale_with_its_age(self):
        """The arithmetic is not wrong — it is about a week that ended. A
        number with no age beside it reads exactly like a live measurement."""
        from brain.synthesizer import STALE_PROBE_HOURS
        _bars(_instrument("AMZN"), age_hours=STALE_PROBE_HOURS + 6)
        probe = next(p for p in self._probes() if p["symbol"] == "AMZN")
        self.assertTrue(probe["stale"])
        self.assertGreater(probe["last_bar_age_hours"], STALE_PROBE_HOURS)
        # And the reading itself is still computed, so the model can see
        # both the number and the reason to discount it.
        self.assertIsNotNone(probe["hurst"])

    def test_the_snapshot_counts_fresh_and_stale(self):
        from brain.synthesizer import STALE_PROBE_HOURS
        from brain.synthesizer import _build_world_snapshot
        _bars(_instrument("AAPL"), age_hours=2)
        _bars(_instrument("AMZN"), age_hours=STALE_PROBE_HOURS + 6)
        snap = _build_world_snapshot()
        self.assertEqual(snap["regime_probes_fresh"], 1)
        self.assertEqual(snap["regime_probes_stale"], 1)


class AllStaleProbesSkipTheSynthesisTests(TestCase):

    def setUp(self):
        User.objects.create_user("brain_staff", password="x", is_staff=True)

    def _run(self):
        from brain.synthesizer import synthesize_now
        return synthesize_now()

    def test_a_dead_feed_makes_no_llm_call_and_writes_no_report(self):
        from unittest.mock import patch

        from brain.models import BrainReport
        from brain.synthesizer import STALE_PROBE_HOURS
        for sym in ("AAPL", "AMZN", "MSFT"):
            _bars(_instrument(sym), age_hours=STALE_PROBE_HOURS + 10)
        before = BrainReport.objects.count()
        with patch("ai_agents.providers.claude_provider.ClaudeProvider"
                   ".complete") as complete:
            out = self._run()
        complete.assert_not_called()
        self.assertEqual(out["status"], "skipped")
        self.assertIn("stale", out["reason"])
        # No report row at all — not an error row: an error row feeds the
        # consecutive-failure alert and would page the operator about the
        # brain when the fault is in the feed.
        self.assertEqual(BrainReport.objects.count(), before)

    def test_the_operator_is_told_once_that_the_brain_is_quiet(self):
        from brain.synthesizer import STALE_PROBE_HOURS
        for sym in ("AAPL", "AMZN", "MSFT"):
            _bars(_instrument(sym), age_hours=STALE_PROBE_HOURS + 10)
        self._run()
        from alerts.models import Notification
        self.assertTrue(Notification.objects.filter(
            title__icontains="not synthesising").exists())

    def test_one_fresh_probe_is_not_a_regime_read(self):
        """The model cannot know the other seven numbers came from a dead
        frame — it produced 'eight instruments, all coin flips' with total
        confidence off exactly that input."""
        from unittest.mock import patch

        from brain.synthesizer import MIN_FRESH_PROBES, STALE_PROBE_HOURS
        self.assertGreater(MIN_FRESH_PROBES, 1)
        _bars(_instrument("AAPL"), age_hours=2)
        for sym in ("AMZN", "MSFT", "NVDA"):
            _bars(_instrument(sym), age_hours=STALE_PROBE_HOURS + 10)
        with patch("ai_agents.providers.claude_provider.ClaudeProvider"
                   ".complete") as complete:
            out = self._run()
        complete.assert_not_called()
        self.assertEqual(out["status"], "skipped")

    def test_enough_fresh_probes_and_the_synthesis_runs(self):
        """The gate must refuse a dead feed, not go quiet every weekend."""
        from unittest.mock import patch

        from brain.synthesizer import STALE_PROBE_HOURS
        _bars(_instrument("AAPL"), age_hours=2)
        _bars(_instrument("AMZN"), age_hours=3)
        _bars(_instrument("MSFT"), age_hours=STALE_PROBE_HOURS + 10)
        with patch("ai_agents.providers.claude_provider.ClaudeProvider"
                   ".complete",
                   return_value=("{}", {"input_tokens": 1, "output_tokens": 1,
                                        "cost_usd": 0.0})) as complete:
            out = self._run()
        complete.assert_called_once()
        self.assertNotEqual(out.get("status"), "skipped")

    def test_no_probes_at_all_does_not_trip_the_gate(self):
        """A fresh install has no bars for anything; that is the "not set up
        yet" state the health page already reports, and skipping here would
        hide it behind a feed complaint."""
        from unittest.mock import patch

        with patch("ai_agents.providers.claude_provider.ClaudeProvider"
                   ".complete",
                   return_value=("{}", {"input_tokens": 1, "output_tokens": 1,
                                        "cost_usd": 0.0})) as complete:
            out = self._run()
        complete.assert_called_once()
        self.assertNotEqual(out.get("status"), "skipped")


class TheSpendGuardNamesTheTierItActuallySpendsTests(SimpleTestCase):
    """spend.can_spend keys DEEP_TIER_SHARE off the guard's tier string, so a
    deep agent guarded as "balanced" is exempt from the reserve that exists
    to contain it — and eats the budget the critic is held back for."""

    def test_the_two_deep_brain_tasks_are_guarded_as_deep(self):
        import inspect

        from brain import tasks
        src = inspect.getsource(tasks)
        for task in ("run_sauron_mind", "run_earnings_reviewer"):
            head = src.split(f"def {task}(")[0].rsplit("@shared_task", 1)[1]
            self.assertIn('tier="deep"', head,
                          f"{task} spends Opus money; its guard must say so")

    def test_the_agents_behind_them_really_are_deep_tier(self):
        from brain.earnings_reviewer import EarningsReviewerAgent
        from brain.synthesizer import SauronMindAgent
        self.assertEqual(SauronMindAgent.default_tier, "deep")
        self.assertEqual(EarningsReviewerAgent.default_tier, "deep")


class SonnetFiveIsPricedAtItsOwnRateTests(SimpleTestCase):
    """$3/$15 is Sonnet 4.6's rate and was copied onto Sonnet 5. The
    balanced tier is this platform's workhorse, so every one of its ledger
    rows read 50% high and AI_DAILY_BUDGET_USD stopped work at about two
    thirds of the money the operator had authorised."""

    def test_sonnet_5_costs_two_and_ten(self):
        from ai_agents.catalog import pricing_for
        p = pricing_for("claude-sonnet-5")
        self.assertEqual(p["input"], 2.0)
        self.assertEqual(p["output"], 10.0)

    def test_it_is_cheaper_than_the_generation_it_replaced(self):
        from ai_agents.catalog import pricing_for
        new, old = pricing_for("claude-sonnet-5"), pricing_for("claude-sonnet-4-6")
        self.assertLess(new["input"], old["input"])
        self.assertLess(new["output"], old["output"])

    def test_the_other_two_tier_defaults_are_unchanged(self):
        from ai_agents.catalog import pricing_for
        self.assertEqual(pricing_for("claude-opus-5"),
                         {"input": 5.0, "output": 25.0})
        self.assertEqual(pricing_for("claude-haiku-4-5"),
                         {"input": 1.0, "output": 5.0})
