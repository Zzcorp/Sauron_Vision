"""Tests for Phase 46 — operational health checks for the brain stack.

Covers:
  - check_brain_failure_rate: streak of failures triggers alert; mixed → no alert;
    insufficient data → no alert
  - check_critic_dissent_rate: too-low / too-high / ok / insufficient_data
  - maybe_alert_brain_failures: dispatches staff notifications + cooldown dedupe
  - maybe_alert_critic_dissent_rate: dispatches when out-of-band
  - notify_staff: walks staff users only, respects cooldown
  - synthesize_now error path triggers maybe_alert_brain_failures
  - consolidate_now writes critic dissent rate into ConsolidationRun.notes
"""
from datetime import timedelta
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _staff(name="staff_p46"):
    u = User.objects.create_user(username=name, password="x")
    u.is_staff = True
    u.is_active = True
    u.save()
    return u


def _normal_user(name="user_p46"):
    return User.objects.create_user(username=name, password="x")


# ── check_brain_failure_rate ──────────────────────────────────────────────

class CheckBrainFailureRateTests(TestCase):
    def test_three_consecutive_failures_triggers_alert(self):
        from brain.models import BrainReport
        from brain.health import check_brain_failure_rate
        for i in range(3):
            BrainReport.objects.create(
                regime_label="unknown", error=f"api 500 #{i}",
            )
        result = check_brain_failure_rate(streak=3)
        self.assertTrue(result["alert"])
        self.assertEqual(result["consecutive_failures"], 3)
        self.assertIn("api 500", result["last_error"])

    def test_mixed_no_alert(self):
        from brain.models import BrainReport
        from brain.health import check_brain_failure_rate
        BrainReport.objects.create(regime_label="trending", error="")
        BrainReport.objects.create(regime_label="unknown", error="api 500")
        BrainReport.objects.create(regime_label="trending", error="")
        result = check_brain_failure_rate(streak=3)
        self.assertFalse(result["alert"])

    def test_insufficient_data_no_alert(self):
        from brain.health import check_brain_failure_rate
        result = check_brain_failure_rate(streak=3)
        self.assertFalse(result["alert"])
        self.assertEqual(result["n_examined"], 0)

    def test_old_failures_excluded_by_lookback(self):
        from brain.models import BrainReport
        from brain.health import check_brain_failure_rate
        # 3 failures, but all > 4h old.
        for i in range(3):
            r = BrainReport.objects.create(regime_label="unknown",
                                              error="boom")
            BrainReport.objects.filter(id=r.id).update(
                created_at=timezone.now() - timedelta(hours=5))
        result = check_brain_failure_rate(streak=3, lookback_hours=3)
        self.assertFalse(result["alert"])


# ── check_critic_dissent_rate ─────────────────────────────────────────────

class CheckCriticDissentRateTests(TestCase):
    def _vote(self, stance: str, hyp_idx=0):
        from brain.knowledge_models import Hypothesis, HypothesisVote
        h = Hypothesis.objects.create(
            claim_text=f"c{hyp_idx}", source_agent="x",
            confidence=0.5,
        )
        HypothesisVote.objects.create(
            hypothesis=h, agent="critic", stance=stance, confidence=0.5,
        )

    def test_too_low_triggers_alert(self):
        from brain.health import check_critic_dissent_rate
        # 1 dissent / 20 votes = 5% boundary; use 0/20 to be unambiguous.
        for i in range(20):
            self._vote("co_sign", hyp_idx=i)
        r = check_critic_dissent_rate()
        self.assertTrue(r["alert"])
        self.assertEqual(r["direction"], "too_low")
        self.assertEqual(r["dissent_rate"], 0.0)

    def test_too_high_triggers_alert(self):
        from brain.health import check_critic_dissent_rate
        for i in range(15):
            self._vote("dissent", hyp_idx=i)
        for i in range(15, 20):
            self._vote("co_sign", hyp_idx=i)
        # 15/20 = 75% > 50% upper band
        r = check_critic_dissent_rate()
        self.assertTrue(r["alert"])
        self.assertEqual(r["direction"], "too_high")

    def test_in_band_no_alert(self):
        from brain.health import check_critic_dissent_rate
        # 5 dissent / 20 votes = 25% — healthy
        for i in range(5):
            self._vote("dissent", hyp_idx=i)
        for i in range(5, 20):
            self._vote("co_sign", hyp_idx=i)
        r = check_critic_dissent_rate()
        self.assertFalse(r["alert"])
        self.assertEqual(r["direction"], "ok")

    def test_insufficient_data_no_alert(self):
        from brain.health import check_critic_dissent_rate
        # 5 votes < min_votes=10 default
        for i in range(5):
            self._vote("dissent", hyp_idx=i)
        r = check_critic_dissent_rate()
        self.assertFalse(r["alert"])
        self.assertEqual(r["direction"], "insufficient_data")


# ── notify_staff ──────────────────────────────────────────────────────────

class NotifyStaffTests(TestCase):
    def test_walks_only_staff(self):
        from bot_program.notifications import notify_staff
        from alerts.models import UserNotificationPrefs, Notification
        s1 = _staff("s1")
        s2 = _staff("s2")
        u = _normal_user("regular")
        # Need prefs rows so dispatch_notification doesn't bail.
        for x in (s1, s2, u):
            UserNotificationPrefs.objects.create(user=x, receive_bot_alerts=True)
        result = notify_staff(title="x", body="y")
        self.assertEqual(result["n_staff"], 2)
        self.assertEqual(result["n_delivered"], 2)
        # Regular user got nothing.
        self.assertEqual(Notification.objects.filter(user=u).count(), 0)

    def test_cooldown_dedupes(self):
        from bot_program.notifications import notify_staff
        from alerts.models import UserNotificationPrefs
        s = _staff()
        UserNotificationPrefs.objects.create(user=s, receive_bot_alerts=True)
        notify_staff(title="dupe-test")
        # Second call within cooldown → skipped.
        result = notify_staff(title="dupe-test")
        self.assertEqual(result["n_skipped_cooldown"], 1)
        self.assertEqual(result["n_delivered"], 0)


# ── maybe_alert_brain_failures ────────────────────────────────────────────

class MaybeAlertBrainFailuresTests(TestCase):
    def test_no_alert_no_failures(self):
        from brain.models import BrainReport
        from brain.health import maybe_alert_brain_failures
        for _ in range(3):
            BrainReport.objects.create(regime_label="trending", error="")
        r = maybe_alert_brain_failures()
        self.assertFalse(r["alerted"])

    def test_alert_dispatched_to_staff(self):
        from brain.models import BrainReport
        from brain.health import maybe_alert_brain_failures
        from alerts.models import UserNotificationPrefs, Notification
        s = _staff()
        UserNotificationPrefs.objects.create(user=s, receive_bot_alerts=True)
        for i in range(3):
            BrainReport.objects.create(regime_label="unknown",
                                          error=f"api boom {i}")
        r = maybe_alert_brain_failures()
        self.assertTrue(r["alerted"])
        self.assertGreaterEqual(Notification.objects.filter(user=s).count(), 1)


# ── maybe_alert_critic_dissent_rate ──────────────────────────────────────

class MaybeAlertCriticDissentTests(TestCase):
    def test_alert_dispatched_when_out_of_band(self):
        from brain.knowledge_models import Hypothesis, HypothesisVote
        from brain.health import maybe_alert_critic_dissent_rate
        from alerts.models import UserNotificationPrefs, Notification
        s = _staff()
        UserNotificationPrefs.objects.create(user=s, receive_bot_alerts=True)
        # All co_sign — too low.
        for i in range(15):
            h = Hypothesis.objects.create(claim_text=f"c{i}",
                                            source_agent="x", confidence=0.5)
            HypothesisVote.objects.create(
                hypothesis=h, agent="critic", stance="co_sign", confidence=0.5)
        r = maybe_alert_critic_dissent_rate()
        self.assertTrue(r["alerted"])
        self.assertEqual(r["direction"], "too_low")
        self.assertGreaterEqual(Notification.objects.filter(user=s).count(), 1)

    def test_no_alert_when_in_band(self):
        from brain.knowledge_models import Hypothesis, HypothesisVote
        from brain.health import maybe_alert_critic_dissent_rate
        # 4 dissent / 16 = 25% — healthy
        for i in range(4):
            h = Hypothesis.objects.create(claim_text=f"d{i}",
                                            source_agent="x", confidence=0.5)
            HypothesisVote.objects.create(
                hypothesis=h, agent="critic", stance="dissent",
                confidence=0.5)
        for i in range(12):
            h = Hypothesis.objects.create(claim_text=f"c{i}",
                                            source_agent="x", confidence=0.5)
            HypothesisVote.objects.create(
                hypothesis=h, agent="critic", stance="co_sign", confidence=0.5)
        r = maybe_alert_critic_dissent_rate()
        self.assertFalse(r["alerted"])
        self.assertEqual(r["direction"], "ok")


# ── synthesize_now error path triggers alert ─────────────────────────────

class SynthesizeNowAlertHookTests(TestCase):
    def test_error_path_calls_maybe_alert(self):
        from brain.synthesizer import synthesize_now
        # Stub provider failure.
        def bad_init(self, *a, **kw):
            self.agent_name = "sauron_mind"
            self.provider_name = "stub"
            self.model = "stub"
            self.provider = MagicMock()
            self.provider.complete = MagicMock(side_effect=RuntimeError("boom"))
        with patch("brain.synthesizer.SauronMindAgent.__init__", bad_init):
            with patch("brain.health.maybe_alert_brain_failures") as alerter:
                synthesize_now()
        alerter.assert_called_once()


# ── consolidate_now records critic dissent rate ──────────────────────────

class ConsolidationDissentNotesTests(TestCase):
    def test_dissent_rate_reflected_in_run_notes(self):
        from brain.knowledge_models import (
            Hypothesis, HypothesisVote, ConsolidationRun,
        )
        from brain.consolidation import consolidate_now
        # Healthy 25% dissent rate.
        for i in range(4):
            h = Hypothesis.objects.create(claim_text=f"d{i}",
                                            source_agent="x", confidence=0.5)
            HypothesisVote.objects.create(
                hypothesis=h, agent="critic", stance="dissent", confidence=0.5)
        for i in range(12):
            h = Hypothesis.objects.create(claim_text=f"c{i}",
                                            source_agent="x", confidence=0.5)
            HypothesisVote.objects.create(
                hypothesis=h, agent="critic", stance="co_sign", confidence=0.5)
        consolidate_now()
        run = ConsolidationRun.objects.first()
        self.assertIn("critic_dissent=", run.notes)
        # Healthy band → "ok" in the notes
        self.assertIn("ok", run.notes)
