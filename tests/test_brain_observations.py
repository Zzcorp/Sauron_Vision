"""Tests for Phase 37.1 — brain observation queue + audit/decay/mutator hooks.

Covers:
  - record_observation writes typed rows + handles unknown kinds
  - record_observation never raises on bad inputs
  - unconsumed_count filters by kind correctly
  - audit hooks (trade_open / trade_close / gate_reject) emit observations
  - decay alert hook emits a rule_decayed observation
  - mutator hook emits a mutation_proposed observation
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _user(name="brain_u"):
    return User.objects.create_user(username=name, password="x")


def _instrument(symbol="BRN1"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": "stock"},
    )
    return inst


# ── Direct API ──────────────────────────────────────────────────────────

class RecordObservationTests(TestCase):
    def test_creates_row(self):
        from brain.observations import record_observation
        from brain.models import BrainObservation
        oid = record_observation(
            kind=BrainObservation.KIND_GATE_REJECT,
            payload={"reason": "theme_cap"},
            source="orchestrator",
        )
        self.assertIsNotNone(oid)
        obs = BrainObservation.objects.get(id=oid)
        self.assertEqual(obs.kind, "gate_reject")
        self.assertEqual(obs.payload["reason"], "theme_cap")
        self.assertEqual(obs.source_agent, "orchestrator")
        self.assertIsNone(obs.consumed_by_brain_at)

    def test_with_instrument_fk(self):
        from brain.observations import record_observation
        from brain.models import BrainObservation
        inst = _instrument()
        oid = record_observation(kind="anomaly_detected", payload={"x": 1},
                                   source="test", instrument=inst)
        obs = BrainObservation.objects.get(id=oid)
        self.assertEqual(obs.instrument_id, inst.id)

    def test_unknown_kind_accepted(self):
        from brain.observations import record_observation
        from brain.models import BrainObservation
        oid = record_observation(kind="some_new_kind", payload={}, source="test")
        self.assertIsNotNone(oid)
        self.assertEqual(BrainObservation.objects.get(id=oid).kind, "some_new_kind")

    def test_never_raises_on_failure(self):
        """If the DB blows up, record_observation returns None — never raises."""
        from brain.observations import record_observation
        with patch("brain.models.BrainObservation.objects.create",
                   side_effect=RuntimeError("db down")):
            # Should NOT raise.
            result = record_observation(kind="x", payload={}, source="t")
        self.assertIsNone(result)


class UnconsumedCountTests(TestCase):
    def test_counts_only_unconsumed(self):
        from brain.observations import record_observation, unconsumed_count
        from brain.models import BrainObservation
        record_observation(kind="gate_reject", source="t")
        record_observation(kind="fill_closed", source="t")
        oid = record_observation(kind="gate_reject", source="t")
        # Mark one consumed.
        BrainObservation.objects.filter(id=oid).update(
            consumed_by_brain_at=timezone.now())
        self.assertEqual(unconsumed_count(), 2)
        self.assertEqual(unconsumed_count(kind="gate_reject"), 1)
        self.assertEqual(unconsumed_count(kind="fill_closed"), 1)


# ── Audit hook integration ───────────────────────────────────────────────

class AuditHookIntegrationTests(TestCase):
    def setUp(self):
        self.user = _user()
        self.inst = _instrument()

    def _trade(self, **kw):
        from bot_program.models import AssetBotConfig, AssetBotTrade
        cfg = AssetBotConfig.objects.create(
            user=self.user, asset_class="stock", name="hook_t",
            enabled=True, mode="paper", symbols=["BRN1"],
            capital=Decimal("10000"), base_currency="USD",
            position_size_pct=2.0, max_concurrent_positions=5,
            max_daily_loss_pct=2.0, stop_loss_pct=1.5, take_profit_pct=3.0,
            entry_score_min=0.6, min_signals_for_entry=1,
        )
        defaults = dict(
            config=cfg, asset_class="stock", symbol="BRN1", side="BUY",
            qty=Decimal("10"), entry_price=Decimal("100"),
            stop_loss=Decimal("99"), take_profit=Decimal("103"),
            rule_name="hook_rule", paper=True, status="OPEN",
            broker_order_id="ord-x",
        )
        defaults.update(kw)
        return AssetBotTrade.objects.create(**defaults)

    def test_trade_open_emits_observation(self):
        from bot_program.audit import record_trade_open
        from brain.models import BrainObservation
        trade = self._trade()
        record_trade_open(self.user, trade=trade)
        # Audit hooks emit an "audit_event" wrapper.
        self.assertTrue(BrainObservation.objects.filter(kind="audit_event").exists())
        obs = BrainObservation.objects.filter(kind="audit_event").first()
        self.assertEqual(obs.payload.get("audit_kind"), "trade_open")
        self.assertEqual(obs.payload.get("symbol"), "BRN1")

    def test_trade_close_emits_fill_closed(self):
        from bot_program.audit import record_trade_close
        from brain.models import BrainObservation
        trade = self._trade(status="CLOSED",
                              exit_price=Decimal("103"),
                              pnl=Decimal("30"),
                              outcome="hit_target",
                              realized_r=2.0, duration_minutes=120)
        record_trade_close(self.user, trade=trade)
        self.assertTrue(BrainObservation.objects.filter(kind="fill_closed").exists())
        obs = BrainObservation.objects.filter(kind="fill_closed").first()
        self.assertEqual(obs.payload.get("outcome"), "hit_target")

    def test_gate_reject_emits_observation(self):
        from bot_program.audit import record_gate_reject
        from brain.models import BrainObservation
        record_gate_reject(
            self.user, asset_class="stock", symbol="BRN1", side="BUY",
            right="long", reason="theme_cap_exceeded",
            exposure_before={"USD_short": 0.7},
            exposure_after={"USD_short": 0.85},
            caps={"USD_short": 0.8},
        )
        self.assertTrue(BrainObservation.objects.filter(kind="gate_reject").exists())
        obs = BrainObservation.objects.filter(kind="gate_reject").first()
        self.assertEqual(obs.payload.get("reason"), "theme_cap_exceeded")
        self.assertEqual(obs.source_agent, "orchestrator")


# ── Decay alert hook ──────────────────────────────────────────────────────

class DecayHookTests(TestCase):
    def test_decay_alert_emits_observation(self):
        """When the decay scanner creates a RuleTrackRecordAlert, a brain
        observation should fire. We simulate by inserting trades and
        running the scanner."""
        from bot_program.models import AssetBotConfig, AssetBotTrade
        from bot_program.track_record_decay import check_user_decay
        from brain.models import BrainObservation

        user = _user("decay_u")
        cfg = AssetBotConfig.objects.create(
            user=user, asset_class="stock", name="decay_cfg",
            enabled=True, mode="paper", symbols=["X"],
            capital=Decimal("10000"), base_currency="USD",
            position_size_pct=2.0, max_concurrent_positions=5,
            max_daily_loss_pct=2.0, stop_loss_pct=1.5, take_profit_pct=3.0,
            entry_score_min=0.6, min_signals_for_entry=1,
        )
        # Baseline (30d ago) good trades.
        baseline_open = timezone.now() - timedelta(days=20)
        baseline_close = timezone.now() - timedelta(days=15)
        for i in range(10):
            AssetBotTrade.objects.create(
                config=cfg, asset_class="stock", symbol="X", side="BUY",
                qty=Decimal("1"), entry_price=Decimal("100"),
                exit_price=Decimal("105"), pnl=Decimal("5"),
                rule_name="decay_rule", paper=True, status="CLOSED",
                outcome="hit_target", realized_r=1.0, duration_minutes=60,
                opened_at=baseline_open, closed_at=baseline_close,
            )
        # Recent (last 7d) bad trades.
        recent_open = timezone.now() - timedelta(days=3)
        recent_close = timezone.now() - timedelta(days=2)
        for i in range(8):
            AssetBotTrade.objects.create(
                config=cfg, asset_class="stock", symbol="X", side="BUY",
                qty=Decimal("1"), entry_price=Decimal("100"),
                exit_price=Decimal("95"), pnl=Decimal("-5"),
                rule_name="decay_rule", paper=True, status="CLOSED",
                outcome="stopped_out", realized_r=-1.0, duration_minutes=60,
                opened_at=recent_open, closed_at=recent_close,
            )
        check_user_decay(user)
        self.assertTrue(BrainObservation.objects.filter(kind="rule_decayed").exists(),
                        "decay alert should produce a brain observation")


# ── Mutator hook ──────────────────────────────────────────────────────────

class MutatorHookTests(TestCase):
    def test_mutator_emits_observation_on_success(self):
        """When generate_ai_mutant produces parameters, it should fire a
        mutation_proposed observation. We mock the AI agent so it returns
        valid params without external API calls."""
        from brain.models import BrainObservation
        from signals.evolution import register_schema

        # Register a tiny schema.
        register_schema("mutator_test_rule", {
            "lookback": {"type": "int", "min": 5, "max": 50, "default": 20},
        })

        with patch("ai_agents.agents.strategy_mutator.StrategyMutatorAgent") as agent_cls:
            agent = agent_cls.return_value
            agent.run.return_value = {"parameters": {"lookback": 30}}
            from ai_agents.agents.strategy_mutator import generate_ai_mutant
            out = generate_ai_mutant("mutator_test_rule")
        self.assertEqual(out.get("lookback"), 30)
        self.assertTrue(BrainObservation.objects.filter(kind="mutation_proposed").exists())
        obs = BrainObservation.objects.filter(kind="mutation_proposed").first()
        self.assertEqual(obs.payload.get("rule_name"), "mutator_test_rule")
        self.assertEqual(obs.payload["mutated"]["lookback"], 30)
