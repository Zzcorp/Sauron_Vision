"""The anomaly scan reads only markets that are actually trading.

One weekend the scan alerted every hour, all weekend: "TSLA up 5.14% ...
no apparent catalyst" (Friday's close, frozen), "All FX pairs show
volume=0" (the feeds never report FX volume), "Rice up 3.77% ... data
timestamp is stale" (a rotation row nobody had touched since the CBOT
close). Every one of those is the scan describing its own stale input as
a market event — a closed market cannot have a market anomaly.

Three behaviours are pinned here:

  1. Quotes from closed markets and quotes older than
     ANOMALY_STALE_MINUTES never reach the agent, and when nothing
     survives the filter the task SKIPS — it does not invent a scan.
  2. The snapshot handed to the agent says what was excluded, so the
     model stops inferring meaning from absences and zero volumes.
  3. One severe finding notifies once per ANOMALY_REPEAT_COOLDOWN_S per
     (symbol, type) — the agent re-detecting a condition every hour is
     correct; re-ringing the bell every hour was the spam.

Run with:  python manage.py test tests.test_anomaly_market_hours
"""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

import pytz
from datetime import datetime

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase

# Fixed clocks, because these behaviours ARE clock behaviours. Saturday
# noon: every session in EXCHANGES is shut. Wednesday 15:00 UTC: New York
# (11:00), London (16:00), the FX week and Globex are all open.
SATURDAY = datetime(2026, 8, 22, 12, 0, tzinfo=pytz.UTC)
WEDNESDAY = datetime(2026, 8, 19, 15, 0, tzinfo=pytz.UTC)


def _enable(*keys):
    from core.platform_control import PlatformComponent, seed_components
    seed_components()
    PlatformComponent.objects.filter(
        key__in=("platform_master",) + keys).update(is_enabled=True)


def _instrument(symbol, asset_class="stock", exchange=""):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class,
                                 "exchange": exchange})
    return inst


def _quote(inst, volume=1000):
    from market_data.models import LiveQuote
    return LiveQuote.objects.create(
        instrument=inst, last=Decimal("100"), change_pct=Decimal("1.5"),
        volume=volume, source="test")


class _CapturingAgent:
    """Scripted answer, captured question."""

    anomalies: list = []
    seen_market_data: list = []

    def __init__(self, *args, **kwargs):
        pass

    def run(self, **kwargs):
        type(self).seen_market_data.append(kwargs.get("market_data", ""))
        return {"anomalies": list(type(self).anomalies),
                "market_stress_level": 5}


def _scan(anomalies):
    from ai_agents import tasks

    _CapturingAgent.anomalies = anomalies
    with mock.patch(
            "ai_agents.agents.anomaly_detector.AnomalyDetectorAgent",
            _CapturingAgent):
        return tasks.run_anomaly_detection()


def _severe(symbol, kind="volume_spike"):
    return {"symbol": symbol, "type": kind,
            "description": "40x the 30d average", "severity": 9}


class FreshOpenQuotesTests(TestCase):
    """The filter itself, on fixed clocks."""

    def _run(self, now):
        from ai_agents.tasks import _fresh_open_quotes
        from market_data.models import LiveQuote
        return _fresh_open_quotes(
            LiveQuote.objects.select_related("instrument").all(), now)

    def test_saturday_keeps_only_crypto(self):
        """The weekend that produced the complaint: a stock, an FX pair
        and a CBOT future all frozen since Friday, one crypto quote still
        breathing. Only the crypto row may reach the agent."""
        _quote(_instrument("TSLA", "stock", "NASDAQ"))
        _quote(_instrument("EURUSD", "forex", "FOREX"), volume=0)
        _quote(_instrument("RICE", "commodity", "CBOT"))
        _quote(_instrument("AAVEUSD", "crypto", "CRYPTO"))

        kept, dropped_closed, dropped_stale = self._run(SATURDAY)
        self.assertEqual([q.instrument.symbol for q in kept], ["AAVEUSD"])
        self.assertEqual(dropped_closed, 3)
        self.assertEqual(dropped_stale, 0)

    def test_sunday_daytime_drops_fresh_commodity_prints(self):
        """The review catch, one day over from Saturday: the commodity
        poller runs all weekend, so Friday's frozen prints wear a fresh
        updated_at — only the (fixed) Globex weekend boundary keeps them
        from the agent on Sunday daytime."""
        _quote(_instrument("RICE", "commodity", "CBOT"))
        _quote(_instrument("AAVEUSD", "crypto", "CRYPTO"))

        sunday = SATURDAY + timedelta(days=1)  # 2026-08-23 12:00 UTC
        kept, dropped_closed, _ = self._run(sunday)
        self.assertEqual([q.instrument.symbol for q in kept], ["AAVEUSD"])
        self.assertEqual(dropped_closed, 1)

    def test_weekday_session_keeps_the_open_markets(self):
        """Wednesday mid-session the same four rows all qualify."""
        _quote(_instrument("TSLA", "stock", "NASDAQ"))
        _quote(_instrument("EURUSD", "forex", "FOREX"), volume=0)
        _quote(_instrument("RICE", "commodity", "CBOT"))
        _quote(_instrument("AAVEUSD", "crypto", "CRYPTO"))

        kept, dropped_closed, dropped_stale = self._run(WEDNESDAY)
        self.assertEqual(
            sorted(q.instrument.symbol for q in kept),
            ["AAVEUSD", "EURUSD", "RICE", "TSLA"])
        self.assertEqual((dropped_closed, dropped_stale), (0, 0))

    def test_a_stale_row_in_an_open_market_is_dropped(self):
        """Open market, dead feed: the rice case on a weekday. The row is
        aged in the DATABASE and refetched — updated_at is auto_now, so
        the in-memory instance always looks freshly written."""
        from market_data.models import LiveQuote
        q = _quote(_instrument("RICE", "commodity", "CBOT"))
        LiveQuote.objects.filter(pk=q.pk).update(
            updated_at=WEDNESDAY - timedelta(hours=3))

        kept, dropped_closed, dropped_stale = self._run(WEDNESDAY)
        self.assertEqual(kept, [])
        self.assertEqual(dropped_stale, 1)


class AnomalyScanGateTests(TestCase):
    """The task around the filter: skip honestly, say what was excluded."""

    def setUp(self):
        _enable("agent_anomaly")
        self.user = User.objects.create_user("mkt_hours_op")
        cache.clear()  # cooldown stamps are process-wide, tests are not

    def test_nothing_open_means_skipped_not_scanned(self):
        """No agent call, no notification, and a reason that carries the
        counts — a silent empty scan would report success while measuring
        nothing, which is the exact green-while-dead failure the task
        gate exists to catch."""
        from ai_agents import tasks
        from alerts.models import Notification

        _quote(_instrument("TSLA", "stock", "NASDAQ"))
        agent_cls = mock.MagicMock()
        with mock.patch(
                "ai_agents.agents.anomaly_detector.AnomalyDetectorAgent",
                agent_cls), \
            mock.patch.object(tasks, "_fresh_open_quotes",
                              lambda quotes, now: ([], 3, 2)):
            out = tasks.run_anomaly_detection()

        agent_cls.assert_not_called()
        self.assertFalse(Notification.objects.exists())
        self.assertEqual(out["status"], "skipped")
        self.assertIn("3 closed-market", out["reason"])
        self.assertIn("2 stale", out["reason"])

    def test_snapshot_names_its_own_exclusions(self):
        """The agent must be told the tape was pre-filtered, or it infers
        stories from absences — crypto is always open, so a crypto quote
        rides the real filter at any wall clock."""
        _CapturingAgent.seen_market_data = []
        _quote(_instrument("AAVEUSD", "crypto", "CRYPTO"))
        out = _scan([])

        self.assertEqual(out["status"], "success")
        self.assertEqual(out["quotes_scanned"], 1)
        [market_data] = _CapturingAgent.seen_market_data
        self.assertIn("AAVEUSD", market_data)
        self.assertIn("OPEN right now", market_data)
        self.assertIn("already excluded", market_data)

    def test_prompt_states_the_volume_facts(self):
        """"All FX pairs show volume=0" was a finding once. The system
        prompt now carries the feed's own facts so absent volume on FX
        and commodities stops being reportable."""
        from ai_agents.agents.anomaly_detector import AnomalyDetectorAgent
        prompt = AnomalyDetectorAgent.get_system_prompt(
            object.__new__(AnomalyDetectorAgent))
        self.assertIn("volume=0", prompt)
        self.assertIn("never report these as anomalies", prompt)

    def test_same_finding_notifies_once_per_window(self):
        """Hour one: alert. Hour two, same (symbol, type): the agent may
        keep saying it, the bell must not. The suppressed count is
        published so the quiet second run is visibly a suppression, not
        a scan that found nothing."""
        from alerts.models import Notification

        _quote(_instrument("AAVEUSD", "crypto", "CRYPTO"))

        first = _scan([_severe("AAVEUSD")])
        self.assertTrue(first["notifications_sent"])
        self.assertEqual(Notification.objects.filter(user=self.user).count(), 1)

        second = _scan([_severe("AAVEUSD")])
        self.assertFalse(second["notifications_sent"])
        self.assertEqual(second["suppressed_repeats"], 1)
        self.assertEqual(second["severe_anomalies"], 0)
        self.assertEqual(Notification.objects.filter(user=self.user).count(), 1,
                         "no second bell for the same standing condition")

    def test_an_anomaly_with_no_identity_always_rings(self):
        """The agent's answer is model output; symbol or type can come
        back blank. Every blank used to share ONE cache key, so the
        first symbol-less anomaly muted every DIFFERENT symbol-less
        anomaly for six hours. No identity means no cooldown."""
        from alerts.models import Notification

        _quote(_instrument("AAVEUSD", "crypto", "CRYPTO"))
        nameless = {"symbol": "", "type": "",
                    "description": "correlation regime shift", "severity": 9}
        _scan([dict(nameless)])
        _scan([dict(nameless, description="a different nameless finding")])
        self.assertEqual(Notification.objects.filter(user=self.user).count(), 2,
                         "blank identity must never suppress")

    def test_a_different_anomaly_type_still_rings(self):
        """The cooldown keys on (symbol, type) — a NEW kind of trouble on
        the same asset is a new alert, not a repeat."""
        from alerts.models import Notification

        _quote(_instrument("AAVEUSD", "crypto", "CRYPTO"))
        _scan([_severe("AAVEUSD", kind="volume_spike")])
        _scan([_severe("AAVEUSD", kind="correlation_break")])
        self.assertEqual(Notification.objects.filter(user=self.user).count(), 2)
