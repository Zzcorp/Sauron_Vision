"""Tests for Phase 57 — override-rate threshold alerter.

Covers:
  - check_override_rate: flags above threshold; ok within band; insufficient
    data when too few decisions; unknown agent → insufficient_data
  - maybe_alert_override_rates: dispatches staff alerts when triggered
  - Cooldown via notify_staff dedupe (1 alert / 24h per agent)
  - consolidate_now hooks the override check (no-op when no decisions)
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _staff(name="staff_p57"):
    u = User.objects.create_user(username=name, password="x")
    u.is_staff = True
    u.is_active = True
    u.save()
    return u


def _audit(kind: str, data: dict, *, hours_ago: int = 1):
    from bot_program.audit import record_event
    from bot_program.audit_models import AuditLogEntry
    entry = record_event(kind, data)
    if entry is not None and hours_ago:
        AuditLogEntry.objects.filter(id=entry.id).update(
            created_at=timezone.now() - timedelta(hours=hours_ago))
    return entry


# ── check_override_rate ──────────────────────────────────────────────────

class CheckOverrideRateTests(TestCase):
    def test_above_threshold_flags(self):
        from brain.health import check_override_rate
        # 8 rejected / 10 total = 80% > 70% threshold
        for _ in range(2):
            _audit("proposal_approved", {"proposed_name": "y"})
        for _ in range(8):
            _audit("proposal_rejected", {"proposed_name": "n"})
        r = check_override_rate("strategy_generator")
        self.assertTrue(r["alert"])
        self.assertEqual(r["direction"], "too_high")
        self.assertGreater(r["rate"], 0.7)

    def test_within_band_no_alert(self):
        from brain.health import check_override_rate
        # 1 rejected / 10 = 10% — well within band
        for _ in range(9):
            _audit("proposal_approved", {"proposed_name": "y"})
        for _ in range(1):
            _audit("proposal_rejected", {"proposed_name": "n"})
        r = check_override_rate("strategy_generator")
        self.assertFalse(r["alert"])
        self.assertEqual(r["direction"], "ok")

    def test_insufficient_decisions_no_alert(self):
        from brain.health import check_override_rate
        # Only 3 decisions — below default min_decisions=5
        for _ in range(2):
            _audit("proposal_approved", {"proposed_name": "y"})
        for _ in range(1):
            _audit("proposal_rejected", {"proposed_name": "n"})
        r = check_override_rate("strategy_generator")
        self.assertFalse(r["alert"])
        self.assertEqual(r["direction"], "insufficient_data")
        self.assertIsNone(r["rate"])

    def test_unknown_agent_insufficient_data(self):
        from brain.health import check_override_rate
        r = check_override_rate("nonexistent_agent")
        self.assertFalse(r["alert"])
        self.assertEqual(r["direction"], "insufficient_data")

    def test_excludes_outside_window(self):
        from brain.health import check_override_rate
        # Old rejections (60 days back) shouldn't count.
        for _ in range(8):
            _audit("proposal_rejected", {"proposed_name": "old"},
                    hours_ago=60 * 24)
        for _ in range(2):
            _audit("proposal_approved", {"proposed_name": "fresh"})
        r = check_override_rate("strategy_generator", lookback_days=7)
        # Only 2 fresh decisions → insufficient
        self.assertEqual(r["direction"], "insufficient_data")


# ── maybe_alert_override_rates ───────────────────────────────────────────

class MaybeAlertOverrideRatesTests(TestCase):
    def test_no_alerts_when_clean(self):
        from brain.health import maybe_alert_override_rates
        results = maybe_alert_override_rates()
        for r in results:
            self.assertFalse(r["alerted"])

    def test_alert_dispatched_when_above_threshold(self):
        from brain.health import maybe_alert_override_rates
        from alerts.models import UserNotificationPrefs, Notification
        s = _staff()
        UserNotificationPrefs.objects.create(user=s, receive_bot_alerts=True)
        # 8/10 rejected → 80% override rate
        for _ in range(2):
            _audit("proposal_approved", {"proposed_name": "y"})
        for _ in range(8):
            _audit("proposal_rejected", {"proposed_name": "n"})
        results = maybe_alert_override_rates()
        # Both agents are checked; only strategy_generator should alert.
        gen_result = next(r for r in results
                            if r["agent"] == "strategy_generator")
        self.assertTrue(gen_result["alerted"])
        # Staff received an in-app row.
        self.assertGreaterEqual(Notification.objects.filter(user=s).count(), 1)
        notif = Notification.objects.filter(user=s).first()
        # Agent name is in the title; rate detail in the body.
        self.assertIn("strategy_generator", notif.title)
        self.assertIn("80%", notif.title)

    def test_cooldown_dedupes_repeated_alerts(self):
        """Two back-to-back checks shouldn't double-fire (same title within
        the 24h cooldown window of notify_staff)."""
        from brain.health import maybe_alert_override_rates
        from alerts.models import UserNotificationPrefs, Notification
        s = _staff()
        UserNotificationPrefs.objects.create(user=s, receive_bot_alerts=True)
        for _ in range(2):
            _audit("proposal_approved", {"proposed_name": "y"})
        for _ in range(8):
            _audit("proposal_rejected", {"proposed_name": "n"})
        maybe_alert_override_rates()
        n_before = Notification.objects.filter(user=s).count()
        # Second call within cooldown — should be deduped.
        maybe_alert_override_rates()
        n_after = Notification.objects.filter(user=s).count()
        self.assertEqual(n_before, n_after)


# ── Consolidation hook ───────────────────────────────────────────────────

class ConsolidationHookTests(TestCase):
    def test_consolidate_now_calls_override_check(self):
        from brain.consolidation import consolidate_now
        from unittest.mock import patch
        with patch("brain.health.maybe_alert_override_rates",
                    return_value=[]) as alerter:
            consolidate_now()
        alerter.assert_called_once()