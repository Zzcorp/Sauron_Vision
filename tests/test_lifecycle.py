"""Lifecycle state machine tests using a mocked SmcSignal-like object."""
from django.test import SimpleTestCase
from unittest.mock import patch
from datetime import timedelta
from django.utils import timezone


class FakeSignal:
    """Stand-in that mimics SmcSignal for the lifecycle transition logic."""
    def __init__(self, **kwargs):
        self.symbol = kwargs.get("symbol", "BTCUSDT")
        self.timeframe = kwargs.get("timeframe", "4h")
        self.direction = kwargs.get("direction", "LONG")
        self.entry = kwargs.get("entry", 100.0)
        self.stop = kwargs.get("stop", 95.0)
        self.target = kwargs.get("target", 110.0)
        self.r_multiple = kwargs.get("r_multiple", 2.0)
        self.status = "ACTIVE"
        self.created_at = kwargs.get("created_at", timezone.now())
        self.triggered_at = None
        self.closed_at = None
        self.realized_r = None
        self._saved_fields = []

    def save(self, update_fields=None):
        self._saved_fields.append(update_fields)


class LifecycleTests(SimpleTestCase):
    def test_invalidation_when_stop_hit_first(self):
        from signals.lifecycle import transition_signal
        sig = FakeSignal(direction="LONG", entry=100, stop=95, target=110)
        with patch("signals.lifecycle._latest_price", return_value=94.0):
            new_status = transition_signal(sig)
        self.assertEqual(new_status, "INVALIDATED")
        self.assertEqual(sig.realized_r, -1.0)

    def test_active_remains_when_price_in_range(self):
        from signals.lifecycle import transition_signal
        sig = FakeSignal(direction="LONG", entry=100, stop=95, target=110)
        with patch("signals.lifecycle._latest_price", return_value=102.0), \
             patch("signals.lifecycle._bar_extremes_since", return_value=(None, None)):
            new_status = transition_signal(sig)
        self.assertEqual(new_status, "ACTIVE")

    def test_expiry_after_ttl(self):
        from signals.lifecycle import transition_signal
        old = timezone.now() - timedelta(days=30)
        sig = FakeSignal(direction="LONG", created_at=old)
        with patch("signals.lifecycle._latest_price", return_value=100.0):
            new_status = transition_signal(sig)
        self.assertEqual(new_status, "EXPIRED")
