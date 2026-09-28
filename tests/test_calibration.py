"""Tests for Phase-6 calibration loop.

Covers:
  - log_trade_prediction / log_decay_prediction: schema + linkage
  - resolve_pending_predictions: trade outcome resolution from Signal closure
  - resolve_pending_predictions: decay outcome from rule expectancy
  - brier_score: math sanity
  - trust_adjustment_for: bucket transitions
  - risk_gate AI scale dampening when trust < 1
  - Idempotent resolution (already-resolved predictions are skipped)
  - /calibration/ pending counts leave ungraded calls out, as DUE SOON does
  - Direction-call grace window runs on the instrument's market clock

Run with:  python manage.py test tests.test_calibration
"""
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytz
from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _instrument(symbol, asset_class="forex"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class},
    )
    return inst


def _signal(rule="rule_a", **overrides):
    from signals.models import Signal
    inst = _instrument(overrides.pop("symbol", "CAL_TEST"))
    defaults = dict(
        instrument=inst, signal_type="composite",
        direction="bullish", urgency="medium",
        title="t", description="t", rule_name=rule,
        score=0.7, sub_scores={},
        price_at_signal=Decimal("100"), suggested_entry=Decimal("100"),
        suggested_stop=Decimal("95"), suggested_target=Decimal("110"),
        risk_reward_ratio=2.0,
    )
    defaults.update(overrides)
    return Signal.objects.create(**defaults)


def _close_signal(sig, outcome, r):
    sig.is_active = False
    sig.outcome = outcome
    sig.realized_r = r
    sig.expired_at = timezone.now()
    sig.save()


# ── Logging entry points ────────────────────────────────────────────────────

class LoggingTests(TestCase):
    def test_log_trade_prediction_links_signal(self):
        from ai_agents.calibration import log_trade_prediction
        from ai_agents.models import AgentPrediction
        sig = _signal()
        pred = log_trade_prediction("test_agent", sig, predicted_outcome="hit_target",
                                     confidence=0.7)
        self.assertEqual(pred.linked_signal_id, sig.id)
        self.assertEqual(pred.prediction_type, "trade_outcome")
        self.assertEqual(pred.confidence, 0.7)
        self.assertIsNotNone(pred.expected_resolution_at)
        self.assertIsNone(pred.was_correct)

    def test_log_decay_prediction_links_rule_action(self):
        from ai_agents.calibration import log_decay_prediction
        from signals.models import RuleAction
        ra = RuleAction.objects.create(rule_name="r1", action="pause_rule",
                                        state=RuleAction.STATE_PROPOSED)
        pred = log_decay_prediction("decay_investigator", ra,
                                     predicted_continues=True, confidence=0.6)
        self.assertEqual(pred.linked_rule_action_id, ra.id)
        self.assertEqual(pred.prediction_type, "decay_continues")
        # Resolves ~30 days later
        self.assertGreater(pred.expected_resolution_at,
                            timezone.now() + timedelta(days=29))


# ── Auto-resolver: trade outcomes ──────────────────────────────────────────

class TradeResolverTests(TestCase):
    def test_resolve_after_signal_closes_with_correct_prediction(self):
        from ai_agents.calibration import (
            log_trade_prediction, resolve_pending_predictions
        )
        sig = _signal()
        pred = log_trade_prediction("test_agent", sig, predicted_outcome="hit_target",
                                     confidence=0.8)
        # Backdate the resolution deadline so the resolver picks it up.
        from ai_agents.models import AgentPrediction
        AgentPrediction.objects.filter(id=pred.id).update(
            expected_resolution_at=timezone.now() - timedelta(hours=1)
        )

        # Signal closes hitting target.
        _close_signal(sig, "hit_target", 2.0)

        result = resolve_pending_predictions()
        self.assertEqual(result["resolved"], 1)
        pred.refresh_from_db()
        self.assertTrue(pred.was_correct)
        self.assertEqual(pred.actual_value, "hit_target")
        self.assertEqual(pred.score, 2.0)

    def test_resolve_when_outcome_wrong(self):
        from ai_agents.calibration import (
            log_trade_prediction, resolve_pending_predictions
        )
        from ai_agents.models import AgentPrediction
        sig = _signal()
        pred = log_trade_prediction("test_agent", sig, predicted_outcome="hit_target",
                                     confidence=0.9)
        AgentPrediction.objects.filter(id=pred.id).update(
            expected_resolution_at=timezone.now() - timedelta(hours=1)
        )
        _close_signal(sig, "stopped_out", -1.0)
        resolve_pending_predictions()
        pred.refresh_from_db()
        self.assertFalse(pred.was_correct)
        self.assertEqual(pred.score, -1.0)

    def test_idempotent_resolution(self):
        """Already-resolved predictions are not re-processed."""
        from ai_agents.calibration import (
            log_trade_prediction, resolve_pending_predictions
        )
        from ai_agents.models import AgentPrediction
        sig = _signal()
        pred = log_trade_prediction("test_agent", sig)
        AgentPrediction.objects.filter(id=pred.id).update(
            expected_resolution_at=timezone.now() - timedelta(hours=1)
        )
        _close_signal(sig, "hit_target", 2.0)
        result1 = resolve_pending_predictions()
        result2 = resolve_pending_predictions()
        self.assertEqual(result1["resolved"], 1)
        self.assertEqual(result2["resolved"], 0)


# ── Auto-resolver: decay outcomes ──────────────────────────────────────────

class DecayResolverTests(TestCase):
    def test_resolves_when_rule_continues_to_decay(self):
        from ai_agents.calibration import (
            log_decay_prediction, resolve_pending_predictions
        )
        from ai_agents.models import AgentPrediction
        from signals.models import RuleAction
        ra = RuleAction.objects.create(rule_name="rule_decay", action="pause_rule",
                                        state=RuleAction.STATE_PROPOSED)
        pred = log_decay_prediction("decay_investigator", ra, predicted_continues=True)
        # Backdate prediction created_at to 30+ days ago and resolve deadline past.
        AgentPrediction.objects.filter(id=pred.id).update(
            expected_resolution_at=timezone.now() - timedelta(hours=1),
            created_at=timezone.now() - timedelta(days=31),
        )
        # Seed signals for that rule with very negative expectancy.
        for i in range(3):
            sig = _signal(rule="rule_decay", symbol=f"DEC{i}")
            _close_signal(sig, "stopped_out", -1.0)

        result = resolve_pending_predictions()
        self.assertEqual(result["resolved"], 1)
        pred.refresh_from_db()
        # Expectancy is -1.0R, well below the -0.5R threshold → "continues" was right
        self.assertTrue(pred.was_correct)

    def test_pushes_deadline_when_insufficient_data(self):
        """If only 1 closed signal exists, resolver retries later."""
        from ai_agents.calibration import (
            log_decay_prediction, resolve_pending_predictions
        )
        from ai_agents.models import AgentPrediction
        from signals.models import RuleAction
        ra = RuleAction.objects.create(rule_name="rule_thin", action="pause_rule",
                                        state=RuleAction.STATE_PROPOSED)
        pred = log_decay_prediction("decay_investigator", ra)
        AgentPrediction.objects.filter(id=pred.id).update(
            expected_resolution_at=timezone.now() - timedelta(hours=1),
            created_at=timezone.now() - timedelta(days=31),
        )
        # Only 1 closed signal — below the n=3 threshold
        sig = _signal(rule="rule_thin", symbol="THIN0")
        _close_signal(sig, "hit_target", 1.0)

        result = resolve_pending_predictions()
        self.assertEqual(result["resolved"], 0)  # not enough data
        pred.refresh_from_db()
        self.assertIsNone(pred.was_correct)
        # Deadline should have been pushed forward
        self.assertGreater(pred.expected_resolution_at, timezone.now())


# ── Brier score + trust adjustment ─────────────────────────────────────────

class BrierAndTrustTests(TestCase):
    def _add_resolved(self, agent, confidence, was_correct, n=1):
        from ai_agents.models import AgentPrediction
        for _ in range(n):
            AgentPrediction.objects.create(
                agent=agent, prediction_type="trade_outcome",
                predicted_value="hit_target",
                actual_value="hit_target" if was_correct else "stopped_out",
                confidence=confidence,
                was_correct=was_correct,
                evaluated_at=timezone.now(),
            )

    def test_brier_score_perfect_well_calibrated(self):
        """Confident predictions that are correct → very low Brier."""
        from ai_agents.calibration import brier_score
        # 20 predictions at confidence 0.95, all correct → bs = 0.05^2 = 0.0025
        self._add_resolved("perfect_agent", confidence=0.95, was_correct=True, n=20)
        bs = brier_score("perfect_agent")
        self.assertAlmostEqual(bs, 0.0025, places=4)

    def test_brier_score_random_guesses(self):
        """Confidence 0.5 always → bs = 0.25 always."""
        from ai_agents.calibration import brier_score
        self._add_resolved("random_agent", confidence=0.5, was_correct=True, n=10)
        self._add_resolved("random_agent", confidence=0.5, was_correct=False, n=10)
        bs = brier_score("random_agent")
        self.assertAlmostEqual(bs, 0.25, places=4)

    def test_trust_low_for_overconfident_wrong_agent(self):
        """High confidence but consistently wrong → low trust."""
        from ai_agents.calibration import trust_adjustment_for
        # 20 predictions @ 0.9 confidence, all wrong → bs = 0.81 → very damped
        self._add_resolved("overconf_wrong", confidence=0.9, was_correct=False, n=20)
        trust = trust_adjustment_for("overconf_wrong")
        self.assertEqual(trust, 0.50)

    def test_trust_high_for_well_calibrated_agent(self):
        from ai_agents.calibration import trust_adjustment_for
        self._add_resolved("good_agent", confidence=0.95, was_correct=True, n=20)
        trust = trust_adjustment_for("good_agent")
        self.assertEqual(trust, 1.30)

    def test_trust_returns_unit_when_sample_too_small(self):
        from ai_agents.calibration import trust_adjustment_for, MIN_SAMPLE_FOR_TRUST
        self._add_resolved("new_agent", confidence=0.9, was_correct=False,
                           n=MIN_SAMPLE_FOR_TRUST - 1)
        trust = trust_adjustment_for("new_agent")
        self.assertEqual(trust, 1.0)


# ── Risk-gate trust dampening ──────────────────────────────────────────────

class RiskGateTrustDampingTests(TestCase):
    JOURNAL_RESPONSE = {
        "verdict": "scale_down", "scale": 0.4,
        "concerns": ["macro contradiction"],
        "rationale": "Hawkish Fed contradicts long",
    }

    @patch("ai_agents.providers.claude_provider.ClaudeProvider.complete")
    def test_low_trust_dampens_ai_scale_toward_one(self, mock_complete):
        import json
        from ai_agents.calibration import trust_adjustment_for
        from portfolio.risk_gate import evaluate_proposed_trade
        from portfolio.services import get_or_create_default_portfolio
        from ai_agents.models import AgentPrediction

        # Pre-seed the agent with a poor track record so trust → 0.5
        for _ in range(20):
            AgentPrediction.objects.create(
                agent="pretrade_sanity", prediction_type="trade_outcome",
                predicted_value="hit_target", actual_value="stopped_out",
                confidence=0.9, was_correct=False, evaluated_at=timezone.now(),
            )
        self.assertEqual(trust_adjustment_for("pretrade_sanity"), 0.50)

        mock_complete.return_value = (json.dumps(self.JOURNAL_RESPONSE),
                                       {"input_tokens": 10, "output_tokens": 5,
                                        "cost_usd": 0})
        portfolio = get_or_create_default_portfolio()
        inst = _instrument("DAMP_TEST")
        result = evaluate_proposed_trade(
            portfolio, inst, intended_size_usd=500, use_ai_check=True,
        )
        ai = result["checks"]["ai_sanity"]
        self.assertEqual(ai["raw_scale"], 0.4)
        self.assertEqual(ai["trust_adjustment"], 0.5)
        # adjusted = 1 - (1 - 0.4) * 0.5 = 0.7
        self.assertAlmostEqual(ai["adjusted_scale"], 0.7, places=4)


# ── Ungraded calls are neither pending nor resolved ────────────────────────

class UngradedCallsAreNotPendingTests(TestCase):
    """A call the market never answered is stamped evaluated with
    was_correct left NULL — ungraded, not wrong, and not pending either.
    The PENDING tile and the per-agent Pending column must leave it out,
    or they grow for ever and disagree with the DUE SOON list beneath
    them, which already leaves it out."""

    def _row(self, agent, **kw):
        from ai_agents.models import AgentPrediction
        fields = dict(agent=agent, prediction_type="direction",
                      predicted_value="up", instrument_symbol="AAPL",
                      confidence=0.6, reference_price=Decimal("100"),
                      horizon_hours=24.0)
        fields.update(kw)
        return AgentPrediction.objects.create(**fields)

    def test_the_page_counts_an_ungraded_call_as_neither_pending_nor_resolved(self):
        from django.test import Client
        _instrument("AAPL", asset_class="stock")
        now = timezone.now()
        # One agent with a grade already: one live call, one the market
        # never answered, one graded.
        self._row("anomaly_detector",
                  expected_resolution_at=now + timedelta(hours=24))
        self._row("anomaly_detector",
                  expected_resolution_at=now - timedelta(days=3),
                  evaluated_at=now, actual_value="ungradeable_no_bar")
        self._row("anomaly_detector",
                  expected_resolution_at=now - timedelta(days=2),
                  evaluated_at=now, actual_value="up", was_correct=True)
        # One agent with nothing graded yet (the page's "pure pending"
        # row): one live call, one ungraded.
        self._row("daily_briefing",
                  expected_resolution_at=now + timedelta(hours=24))
        self._row("daily_briefing",
                  expected_resolution_at=now - timedelta(days=3),
                  evaluated_at=now, actual_value="ungradeable_no_bar")

        user = User.objects.create_user("cal_pending", password="x")
        client = Client()
        client.force_login(user)
        ctx = client.get("/calibration/").context

        self.assertEqual(ctx["pending_total"], 2)
        self.assertEqual(ctx["pending_total"], len(ctx["recent_pending"]),
                         "the PENDING tile and DUE SOON must agree")
        self.assertEqual(ctx["resolved_total"], 1)
        self.assertEqual(ctx["ungraded_total"], 2)
        self.assertEqual({r["agent"]: r["pending"] for r in ctx["rows"]},
                         {"anomaly_detector": 1, "daily_briefing": 1})


# ── The grace window runs on the instrument's market clock ─────────────────

# A summer Friday: New York closes 20:00 UTC, so a 21:00 UTC deadline
# falls after Friday's last bar, and Monday's first bar is at 13:30 UTC.
FRIDAY_DEADLINE = datetime(2026, 8, 21, 21, 0, tzinfo=pytz.UTC)
MONDAY_BEAT = datetime(2026, 8, 24, 3, 30, tzinfo=pytz.UTC)      # 54.5h later
MONDAYS_FIRST_BAR = datetime(2026, 8, 24, 13, 30, tzinfo=pytz.UTC)
WEDNESDAY_BEAT = datetime(2026, 8, 26, 3, 30, tzinfo=pytz.UTC)   # 102.5h later
NINE_SESSIONS_LATER = datetime(2026, 9, 4, 3, 30, tzinfo=pytz.UTC)


def _bar(inst, when, close, timeframe="1h"):
    from market_data.models import PriceData
    return PriceData.objects.create(
        instrument=inst, timeframe=timeframe, timestamp=when,
        open=close, high=close, low=close, close=Decimal(str(close)),
        volume=1, source="test")


class DirectionGraceOnTheMarketClockTests(TestCase):
    """The 48h a call waits for its bar are 48 hours of ITS market being
    open, on core.exchange_status.market_clock's calendar. Counted on the
    wall clock, a deadline after Friday's last bar on a weekday-only
    market was 54.5h old at Monday's 03:30 beat and thrown away as
    ungradeable ten hours before the bar that would have graded it."""

    def setUp(self):
        self.inst = _instrument("AAPL", asset_class="stock")

    def _call(self, symbol="AAPL", deadline=FRIDAY_DEADLINE):
        from ai_agents.models import AgentPrediction
        return AgentPrediction.objects.create(
            agent="anomaly_detector", prediction_type="direction",
            predicted_value="up", instrument_symbol=symbol, confidence=0.6,
            expected_resolution_at=deadline,
            reference_price=Decimal("100"), horizon_hours=4.0)

    def _resolve(self, now):
        from ai_agents.calibration import resolve_pending_predictions
        return resolve_pending_predictions(now=now)

    def test_a_friday_deadline_on_a_weekday_market_waits_for_mondays_bar(self):
        pred = self._call()
        self._resolve(MONDAY_BEAT)
        pred.refresh_from_db()
        self.assertIsNone(pred.evaluated_at,
                          "no market hours have passed: the bar may still come")
        self.assertIsNone(pred.was_correct)
        _bar(self.inst, MONDAYS_FIRST_BAR, 103.0)
        self._resolve(MONDAY_BEAT + timedelta(days=1))
        pred.refresh_from_db()
        self.assertTrue(pred.was_correct)
        self.assertEqual(pred.actual_value, "up")

    def test_the_window_is_market_hours_not_wall_clock_hours(self):
        pred = self._call()
        # Wednesday's beat: 102 wall-clock hours, two 6.5h sessions.
        self._resolve(WEDNESDAY_BEAT)
        pred.refresh_from_db()
        self.assertIsNone(pred.evaluated_at)
        # Nine sessions on: the market has had its 48 hours to answer.
        self._resolve(NINE_SESSIONS_LATER)
        pred.refresh_from_db()
        self.assertEqual(pred.actual_value, "ungradeable_no_bar")
        self.assertIsNone(pred.was_correct)
        self.assertIsNotNone(pred.evaluated_at)
        self.assertIn("market hours", pred.evaluation_notes)

    def test_crypto_keeps_the_wall_clock_window(self):
        from ai_agents.calibration import DIRECTION_GRACE_HOURS
        _instrument("BTCUSD", asset_class="crypto")
        pred = self._call("BTCUSD")
        self._resolve(FRIDAY_DEADLINE
                      + timedelta(hours=DIRECTION_GRACE_HOURS - 1))
        pred.refresh_from_db()
        self.assertIsNone(pred.evaluated_at)
        self._resolve(FRIDAY_DEADLINE
                      + timedelta(hours=DIRECTION_GRACE_HOURS + 1))
        pred.refresh_from_db()
        self.assertEqual(pred.actual_value, "ungradeable_no_bar")

    def test_market_hours_between_counts_only_open_time(self):
        from ai_agents.calibration import (DIRECTION_GRACE_HOURS,
                                           market_hours_between)
        _instrument("BTCUSD", asset_class="crypto")
        self.assertEqual(
            market_hours_between("AAPL", FRIDAY_DEADLINE, MONDAY_BEAT), 0.0)
        by_wednesday = market_hours_between("AAPL", FRIDAY_DEADLINE,
                                            WEDNESDAY_BEAT)
        self.assertGreaterEqual(by_wednesday, 13.0)   # Monday + Tuesday,
        self.assertLess(by_wednesday, 15.0)           # counted to the hour
        # Crypto never shuts: the wall clock, stopping at the cap.
        self.assertAlmostEqual(
            market_hours_between("BTCUSD", FRIDAY_DEADLINE, MONDAY_BEAT,
                                 cap=1000.0), 54.5, places=2)
        self.assertEqual(
            market_hours_between("BTCUSD", FRIDAY_DEADLINE, MONDAY_BEAT),
            DIRECTION_GRACE_HOURS)
        self.assertEqual(
            market_hours_between("AAPL", MONDAY_BEAT, FRIDAY_DEADLINE), 0.0)
