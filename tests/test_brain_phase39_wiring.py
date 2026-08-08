"""Tests for Phase 39 — wiring brain into orchestrator + agents posting hypotheses.

Covers:
  - brain_rule_advisory: KnowledgeNode rule_state + BrainReport overlay precedence
  - brain_theme_pressure_multiplier: clamps + scaling
  - sidebar nav links resolve (urls reverse)
  - synthesizer _emit_predictions posts hypotheses for resolvable types
  - StrategyMutator emits hypothesis on AI mutation
  - DecayInvestigator emits hypothesis branching on recommended_action
"""
from datetime import timedelta
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone


# ── Brain advisory helpers ────────────────────────────────────────────────

class BrainRuleAdvisoryTests(TestCase):
    def test_no_brain_no_rule_returns_allow(self):
        from brain.context import brain_rule_advisory
        self.assertEqual(brain_rule_advisory(""), ("allow", ""))
        self.assertEqual(brain_rule_advisory("nonexistent")[0], "allow")

    def test_knowledge_graph_takes_precedence(self):
        from brain.context import brain_rule_advisory
        from brain.knowledge_models import KnowledgeNode
        from brain.models import BrainReport
        # Graph says pause, report says active.
        KnowledgeNode.upsert(
            kind="rule_state", key="rule_x",
            payload={"status": "pause_recommended"},
            confidence=0.8, source="consolidation",
        )
        BrainReport.objects.create(
            regime_label="trending", regime_confidence=0.7,
            rule_status_overlay={"rule_x": "active"},
            valid_until=timezone.now() + timedelta(minutes=30),
        )
        status, why = brain_rule_advisory("rule_x")
        self.assertEqual(status, "pause_recommended")
        self.assertIn("knowledge_graph", why)

    def test_falls_back_to_brain_report(self):
        from brain.context import brain_rule_advisory
        from brain.models import BrainReport
        BrainReport.objects.create(
            regime_label="risk_off", regime_confidence=0.7,
            rule_status_overlay={"momentum": "watch"},
            valid_until=timezone.now() + timedelta(minutes=30),
        )
        status, why = brain_rule_advisory("momentum")
        self.assertEqual(status, "watch")
        self.assertIn("brain_report", why)


class BrainThemePressureMultiplierTests(TestCase):
    def test_no_brain_returns_one(self):
        from brain.context import brain_theme_pressure_multiplier
        self.assertEqual(brain_theme_pressure_multiplier("usd"), 1.0)

    def test_full_pressure_squeezes_to_half(self):
        from brain.context import brain_theme_pressure_multiplier
        from brain.models import BrainReport
        BrainReport.objects.create(
            regime_label="trending", regime_confidence=0.7,
            theme_pressures={"usd": 1.0},
            valid_until=timezone.now() + timedelta(minutes=30),
        )
        # Default max_squeeze=0.5 → mult = 0.5
        self.assertEqual(brain_theme_pressure_multiplier("usd"), 0.5)

    def test_partial_pressure_partial_squeeze(self):
        from brain.context import brain_theme_pressure_multiplier
        from brain.models import BrainReport
        BrainReport.objects.create(
            regime_label="trending", regime_confidence=0.7,
            theme_pressures={"equity": 0.4},
            valid_until=timezone.now() + timedelta(minutes=30),
        )
        # 1 - 0.4*0.5 = 0.8
        self.assertAlmostEqual(brain_theme_pressure_multiplier("equity"), 0.8)


# ── Sidebar nav link resolution ───────────────────────────────────────────

class SidebarNavTests(TestCase):
    def test_brain_urls_resolve(self):
        for name in ("brain_dashboard", "knowledge_dashboard",
                      "hypotheses_dashboard", "consolidation_dashboard"):
            self.assertTrue(reverse(name).startswith("/"))


# ── Synthesizer emits Hypotheses too ─────────────────────────────────────

class SynthesizerEmitsHypothesesTests(TestCase):
    def test_regime_persistence_creates_hypothesis(self):
        from brain.synthesizer import _emit_predictions, _persist_report
        from brain.knowledge_models import Hypothesis
        report = _persist_report(
            parsed={"regime_label": "trending"}, snapshot={},
            model="t", tokens_in=0, tokens_out=0, cost_usd=0.0, n_consumed=0,
        )
        n = _emit_predictions(report, {"predictions": [{
            "prediction_type": "regime_persistence",
            "predicted_value": "trending", "confidence": 0.8,
            "horizon_hours": 12, "rationale": "x",
        }]})
        self.assertEqual(n, 1)
        h = Hypothesis.objects.filter(source_agent="sauron_mind").first()
        self.assertIsNotNone(h)
        self.assertEqual(h.resolution_criteria.get("kind"), "regime_holds")
        self.assertEqual(h.resolution_criteria.get("regime"), "trending")
        # Linked back to the brain report + agent prediction.
        self.assertEqual(h.brain_report_id, report.id)
        self.assertIsNotNone(h.agent_prediction_id)

    def test_rule_decay_continues_creates_hypothesis(self):
        from brain.synthesizer import _emit_predictions, _persist_report
        from brain.knowledge_models import Hypothesis
        report = _persist_report(parsed={"regime_label": "unknown"},
                                  snapshot={}, model="t", tokens_in=0,
                                  tokens_out=0, cost_usd=0.0, n_consumed=0)
        _emit_predictions(report, {"predictions": [{
            "prediction_type": "rule_decay_continues",
            "predicted_value": "rule_x", "confidence": 0.7,
            "horizon_hours": 48, "rationale": "y",
        }]})
        h = Hypothesis.objects.filter(source_agent="sauron_mind").first()
        self.assertIsNotNone(h)
        self.assertEqual(h.resolution_criteria.get("kind"), "rule_avg_r")
        self.assertEqual(h.resolution_criteria.get("comparator"), "<")
        self.assertEqual(h.resolution_criteria.get("rule_name"), "rule_x")

    def test_unmappable_prediction_no_hypothesis_but_agent_prediction_kept(self):
        from brain.synthesizer import _emit_predictions, _persist_report
        from brain.knowledge_models import Hypothesis
        from ai_agents.models import AgentPrediction
        report = _persist_report(parsed={"regime_label": "unknown"},
                                  snapshot={}, model="t", tokens_in=0,
                                  tokens_out=0, cost_usd=0.0, n_consumed=0)
        _emit_predictions(report, {"predictions": [{
            "prediction_type": "narrative_holds",
            "predicted_value": "AI bubble inflates", "confidence": 0.6,
            "horizon_hours": 168, "rationale": "z",
        }]})
        # AgentPrediction made; Hypothesis NOT made (no resolver mapping).
        self.assertEqual(AgentPrediction.objects.count(), 1)
        self.assertEqual(Hypothesis.objects.count(), 0)


# ── Mutator emits hypothesis ─────────────────────────────────────────────

class MutatorHypothesisTests(TestCase):
    def test_ai_mutation_posts_hypothesis(self):
        from signals.evolution import register_schema
        from brain.knowledge_models import Hypothesis
        register_schema("mut_h_test", {
            "lookback": {"type": "int", "min": 5, "max": 50, "default": 20},
        })
        with patch("ai_agents.agents.strategy_mutator.StrategyMutatorAgent") as agent_cls:
            agent = agent_cls.return_value
            agent.run.return_value = {"parameters": {"lookback": 30}}
            from ai_agents.agents.strategy_mutator import generate_ai_mutant
            generate_ai_mutant("mut_h_test")

        h = Hypothesis.objects.filter(source_agent="strategy_mutator").first()
        self.assertIsNotNone(h)
        self.assertEqual(h.resolution_criteria.get("rule_name"), "mut_h_test")
        self.assertEqual(h.resolution_criteria.get("comparator"), ">=")


# ── DecayInvestigator emits hypothesis ───────────────────────────────────

class DecayInvestigatorHypothesisTests(TestCase):
    def _stub_agent_run(self, action: str):
        """Stub the agent run to return a parsed dict with the given action."""
        def patched_run(*args, **kwargs):
            return {"hypothesis": "x", "contributing_factors": [],
                    "recommended_action": action}
        return patched_run

    def _fake_decay_flag(self):
        return {
            "is_decaying": True,
            "recent_expectancy": -0.5, "baseline_expectancy": 0.4,
            "recent_n": 8, "baseline_n": 30,
        }

    def test_pause_action_posts_continued_decay_hypothesis(self):
        from brain.knowledge_models import Hypothesis
        with patch("ai_agents.agents.decay_investigator.DecayInvestigatorAgent") as agent_cls:
            agent_cls.return_value.run = self._stub_agent_run("pause_rule")
            with patch("signals.performance.decay_flag",
                       return_value=self._fake_decay_flag()):
                from ai_agents.agents.decay_investigator import investigate_decaying_rule
                investigate_decaying_rule("decay_h_rule")

        h = Hypothesis.objects.filter(source_agent="decay_investigator").first()
        self.assertIsNotNone(h)
        self.assertEqual(h.resolution_criteria.get("comparator"), "<")
        self.assertIn("continues decaying", h.claim_text)

    def test_monitor_action_posts_recovery_hypothesis(self):
        from brain.knowledge_models import Hypothesis
        with patch("ai_agents.agents.decay_investigator.DecayInvestigatorAgent") as agent_cls:
            agent_cls.return_value.run = self._stub_agent_run("monitor")
            with patch("signals.performance.decay_flag",
                       return_value=self._fake_decay_flag()):
                from ai_agents.agents.decay_investigator import investigate_decaying_rule
                investigate_decaying_rule("decay_h_rule_monitor")

        h = Hypothesis.objects.filter(source_agent="decay_investigator").first()
        self.assertIsNotNone(h)
        self.assertEqual(h.resolution_criteria.get("comparator"), ">=")
        self.assertIn("recovers", h.claim_text)
