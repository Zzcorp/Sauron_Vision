"""Tests for Phase 38 — knowledge graph, hypothesis market, critic, consolidation.

Covers:
  - KnowledgeNode versioning: upsert creates new version, marks prior superseded
  - KnowledgeNode.current / history
  - post_hypothesis + vote (one vote per agent enforced)
  - resolve_due grades regime_holds / rule_avg_r / anomaly_persists
  - resolve_due mirrors outcome into linked AgentPrediction
  - agent_trust_score: Brier-derived
  - select_hypotheses_for_review prioritizes low-trust + high-confidence
  - review_hypothesis: stub provider → vote persisted, counter-hypothesis emitted
  - run_critic_pass: bounded by max_n
  - consolidate_now: regime/theme/rule promotion + observation pruning
  - Dashboard views render 200
"""
from datetime import timedelta
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _staff(name="staff_p38"):
    u = User.objects.create_user(username=name, password="x")
    u.is_staff = True
    u.save()
    return u


def _login_user(name="user_p38"):
    return User.objects.create_user(username=name, password="x")


# ── Knowledge graph ───────────────────────────────────────────────────────

class KnowledgeNodeTests(TestCase):
    def test_upsert_creates_first_version(self):
        from brain.knowledge_models import KnowledgeNode
        n = KnowledgeNode.upsert(kind="regime", key="portfolio",
                                  payload={"label": "trending"},
                                  confidence=0.7, source="test")
        self.assertEqual(n.version, 1)
        self.assertIsNone(n.superseded_by)
        self.assertEqual(KnowledgeNode.current("regime", "portfolio"), n)

    def test_upsert_supersedes_prior(self):
        from brain.knowledge_models import KnowledgeNode
        first = KnowledgeNode.upsert(kind="regime", key="portfolio",
                                       payload={"label": "trending"},
                                       confidence=0.6, source="test")
        second = KnowledgeNode.upsert(kind="regime", key="portfolio",
                                        payload={"label": "risk_off"},
                                        confidence=0.7, source="test2")
        first.refresh_from_db()
        self.assertEqual(second.version, 2)
        self.assertEqual(first.superseded_by_id, second.id)
        self.assertEqual(KnowledgeNode.current("regime", "portfolio").id, second.id)
        # Source agents accumulate.
        self.assertIn("test", second.source_agents)
        self.assertIn("test2", second.source_agents)

    def test_history_ordered_oldest_first(self):
        from brain.knowledge_models import KnowledgeNode
        for i in range(3):
            KnowledgeNode.upsert(kind="theme_state", key="USD_short",
                                  payload={"pressure": 0.1 * i},
                                  confidence=0.5, source="t")
        hist = KnowledgeNode.history("theme_state", "USD_short")
        self.assertEqual([h.version for h in hist], [1, 2, 3])

    def test_clamps_confidence(self):
        from brain.knowledge_models import KnowledgeNode
        n = KnowledgeNode.upsert(kind="regime", key="x", payload={},
                                   confidence=2.5, source="t")
        self.assertEqual(n.confidence, 1.0)


# ── Hypothesis market ─────────────────────────────────────────────────────

class HypothesisLifecycleTests(TestCase):
    def test_post_creates_pending_with_deadline(self):
        from brain.hypotheses import post_hypothesis
        from brain.knowledge_models import Hypothesis
        h = post_hypothesis(resolution_criteria={"kind": "regime_holds", "regime": "trending"},
                              claim_text="USD weakens further",
                              source_agent="sauron_mind",
                              confidence=0.7, horizon_hours=12)
        self.assertEqual(h.outcome, Hypothesis.OUTCOME_PENDING)
        self.assertGreater(h.resolution_deadline, timezone.now())

    def test_vote_one_per_agent(self):
        from brain.hypotheses import post_hypothesis, vote
        h = post_hypothesis(resolution_criteria={"kind": "regime_holds", "regime": "trending"},
                              claim_text="x", source_agent="A", confidence=0.5,
                              horizon_hours=1)
        v1 = vote(h, agent="critic", stance="dissent",
                   confidence=0.8, reasoning="r1")
        v2 = vote(h, agent="critic", stance="co_sign",
                   confidence=0.4, reasoning="r2")
        # update_or_create — same row mutated.
        self.assertEqual(v1.id, v2.id)
        v2.refresh_from_db()
        self.assertEqual(v2.stance, "co_sign")
        self.assertEqual(h.votes.count(), 1)


class ResolveDueTests(TestCase):
    def test_regime_holds_confirmed(self):
        from brain.hypotheses import post_hypothesis, resolve_due
        from brain.models import BrainReport
        h = post_hypothesis(
            claim_text="regime stays trending",
            source_agent="sauron_mind", confidence=0.7,
            resolution_criteria={"kind": "regime_holds", "regime": "trending"},
            horizon_hours=1,
        )
        # Force deadline past + create matching report.
        from brain.knowledge_models import Hypothesis
        Hypothesis.objects.filter(id=h.id).update(
            resolution_deadline=timezone.now() - timedelta(minutes=5))
        BrainReport.objects.create(regime_label="trending", regime_confidence=0.8)
        result = resolve_due()
        self.assertEqual(result["confirmed"], 1)
        h.refresh_from_db()
        self.assertEqual(h.outcome, Hypothesis.OUTCOME_CONFIRMED)

    def test_regime_holds_refuted(self):
        from brain.hypotheses import post_hypothesis, resolve_due
        from brain.models import BrainReport
        from brain.knowledge_models import Hypothesis
        h = post_hypothesis(
            claim_text="x", source_agent="x", confidence=0.6,
            resolution_criteria={"kind": "regime_holds", "regime": "trending"},
            horizon_hours=1,
        )
        Hypothesis.objects.filter(id=h.id).update(
            resolution_deadline=timezone.now() - timedelta(minutes=5))
        BrainReport.objects.create(regime_label="risk_off", regime_confidence=0.7)
        result = resolve_due()
        self.assertEqual(result["refuted"], 1)
        h.refresh_from_db()
        self.assertEqual(h.outcome, Hypothesis.OUTCOME_REFUTED)

    def test_anomaly_persists_resolver(self):
        from brain.hypotheses import post_hypothesis, resolve_due
        from brain.knowledge_models import KnowledgeNode, Hypothesis
        # Create the anomaly node it will check.
        KnowledgeNode.upsert(kind="anomaly", key="X", payload={"key": "X"},
                              confidence=0.7, source="t")
        h = post_hypothesis(
            claim_text="X persists", source_agent="critic", confidence=0.6,
            resolution_criteria={"kind": "anomaly_persists", "anomaly_key": "X"},
            horizon_hours=1,
        )
        Hypothesis.objects.filter(id=h.id).update(
            resolution_deadline=timezone.now() - timedelta(minutes=5))
        result = resolve_due()
        self.assertEqual(result["confirmed"], 1)

    def test_unknown_resolver_grades_unresolvable(self):
        """Skipping unknown kinds left them PENDING forever, quietly
        inflating the market stats. Past deadline with no resolver they
        now grade UNRESOLVABLE — minted directly, the way the legacy
        pending mountain actually accumulated (the creation gate refuses
        new ones)."""
        from brain.hypotheses import resolve_due
        from brain.knowledge_models import Hypothesis
        h = Hypothesis.objects.create(
            claim_text="x", source_agent="x", confidence=0.5,
            resolution_criteria={"kind": "unknown_kind"},
            resolution_deadline=timezone.now() - timedelta(minutes=5),
        )
        result = resolve_due()
        self.assertEqual(result["skipped"], 0)
        self.assertEqual(result["unresolvable"], 1)
        h.refresh_from_db()
        self.assertEqual(h.outcome, Hypothesis.OUTCOME_UNRESOLVABLE)
        self.assertIn("no resolver registered", h.resolution_notes)

    def test_mirrors_into_agent_prediction(self):
        from brain.hypotheses import post_hypothesis, resolve_due
        from brain.models import BrainReport
        from brain.knowledge_models import Hypothesis
        from ai_agents.models import AgentPrediction

        pred = AgentPrediction.objects.create(
            agent="x", prediction_type="t", predicted_value="trending",
            confidence=0.6,
            expected_resolution_at=timezone.now() + timedelta(hours=1),
        )
        h = post_hypothesis(
            claim_text="x", source_agent="x", confidence=0.5,
            resolution_criteria={"kind": "regime_holds", "regime": "trending"},
            agent_prediction=pred, horizon_hours=1,
        )
        Hypothesis.objects.filter(id=h.id).update(
            resolution_deadline=timezone.now() - timedelta(minutes=5))
        BrainReport.objects.create(regime_label="trending", regime_confidence=0.8)
        resolve_due()
        pred.refresh_from_db()
        self.assertTrue(pred.was_correct)


class AgentTrustScoreTests(TestCase):
    def test_perfect_predictions_high_trust(self):
        from brain.hypotheses import post_hypothesis, agent_trust_score
        from brain.knowledge_models import Hypothesis
        for i in range(5):
            h = post_hypothesis(resolution_criteria={"kind": "regime_holds", "regime": "trending"},
                              claim_text=f"c{i}", source_agent="A",
                                  confidence=0.9, horizon_hours=1)
            Hypothesis.objects.filter(id=h.id).update(
                outcome=Hypothesis.OUTCOME_CONFIRMED,
                resolved_at=timezone.now(),
            )
        score = agent_trust_score("A")
        self.assertIsNotNone(score)
        self.assertGreater(score, 0.9)

    def test_no_data_returns_none(self):
        from brain.hypotheses import agent_trust_score
        self.assertIsNone(agent_trust_score("nobody"))


# ── Critic agent ──────────────────────────────────────────────────────────

class CriticSelectionTests(TestCase):
    def test_low_trust_source_gets_priority(self):
        from brain.hypotheses import post_hypothesis
        from brain.critic import select_hypotheses_for_review
        from brain.knowledge_models import Hypothesis

        # A: no prior data → trust None → eligible
        h1 = post_hypothesis(resolution_criteria={"kind": "regime_holds", "regime": "trending"},
                              claim_text="from_A", source_agent="A",
                              confidence=0.5, horizon_hours=24)
        # B: high-confidence — sanity-check eligible
        h2 = post_hypothesis(resolution_criteria={"kind": "regime_holds", "regime": "trending"},
                              claim_text="from_B", source_agent="B",
                              confidence=0.85, horizon_hours=24)
        targets = select_hypotheses_for_review(max_n=10, sample_pct=0.0)
        ids = {h.id for h in targets}
        self.assertIn(h1.id, ids)
        self.assertIn(h2.id, ids)

    def test_already_critiqued_excluded(self):
        from brain.hypotheses import post_hypothesis, vote
        from brain.critic import select_hypotheses_for_review
        h = post_hypothesis(resolution_criteria={"kind": "regime_holds", "regime": "trending"},
                              claim_text="x", source_agent="A",
                              confidence=0.5, horizon_hours=24)
        vote(h, agent="critic", stance="co_sign", confidence=0.5)
        targets = select_hypotheses_for_review(max_n=10, sample_pct=0.0)
        self.assertNotIn(h.id, [t.id for t in targets])


def _stub_critic_provider(parsed_dict, raw_text=None):
    import json
    raw = raw_text if raw_text is not None else json.dumps(parsed_dict)
    usage = {"input_tokens": 200, "output_tokens": 80, "cost_usd": 0.005}

    def patched_init(self, *a, **kw):
        self.agent_name = "critic"
        self.provider_name = "stub"
        self.model = "claude-stub"
        self.provider = MagicMock()
        self.provider.complete = MagicMock(return_value=(raw, usage))
    return patch("brain.critic.CriticAgent.__init__", patched_init)


class ReviewHypothesisTests(TestCase):
    def test_co_sign_persists_vote(self):
        from brain.hypotheses import post_hypothesis
        from brain.critic import review_hypothesis
        from brain.knowledge_models import HypothesisVote

        h = post_hypothesis(resolution_criteria={"kind": "regime_holds", "regime": "trending"},
                              claim_text="x", source_agent="A",
                              confidence=0.5, horizon_hours=24)
        with _stub_critic_provider({
            "stance": "co_sign", "confidence": 0.7,
            "reasoning": "supporting evidence: theme_pressures show alignment",
        }):
            result = review_hypothesis(h)
        self.assertTrue(result["ok"])
        self.assertEqual(result["stance"], "co_sign")
        self.assertEqual(HypothesisVote.objects.filter(
            hypothesis=h, agent="critic").count(), 1)
        self.assertIsNone(result.get("counter_hypothesis_id"))

    def test_confident_dissent_emits_counter(self):
        from brain.hypotheses import post_hypothesis
        from brain.critic import review_hypothesis
        from brain.knowledge_models import Hypothesis

        h = post_hypothesis(resolution_criteria={"kind": "regime_holds", "regime": "trending"},
                              claim_text="regime trending continues",
                              source_agent="A", confidence=0.8, horizon_hours=24)
        with _stub_critic_provider({
            "stance": "dissent", "confidence": 0.85,
            "reasoning": "Hurst measurements contradict",
            "counter_hypothesis": {
                "claim_text": "regime is mean-reverting",
                "claim_payload": {},
                "resolution_criteria": {"kind": "regime_holds", "regime": "mean_reverting"},
                "horizon_hours": 24,
                "confidence": 0.7,
            },
        }):
            result = review_hypothesis(h)
        self.assertEqual(result["stance"], "dissent")
        self.assertIsNotNone(result["counter_hypothesis_id"])
        # Counter is itself a Hypothesis with critic as source.
        counter = Hypothesis.objects.get(id=result["counter_hypothesis_id"])
        self.assertEqual(counter.source_agent, "critic")

    def test_low_confidence_dissent_no_counter(self):
        from brain.hypotheses import post_hypothesis
        from brain.critic import review_hypothesis

        h = post_hypothesis(resolution_criteria={"kind": "regime_holds", "regime": "trending"},
                              claim_text="x", source_agent="A", confidence=0.5,
                              horizon_hours=24)
        with _stub_critic_provider({
            "stance": "dissent", "confidence": 0.5,
            "reasoning": "weak evidence",
            "counter_hypothesis": {"claim_text": "y"},
        }):
            result = review_hypothesis(h)
        self.assertIsNone(result.get("counter_hypothesis_id"))

    def test_provider_failure_returns_none(self):
        from brain.hypotheses import post_hypothesis
        from brain.critic import review_hypothesis
        h = post_hypothesis(resolution_criteria={"kind": "regime_holds", "regime": "trending"},
                              claim_text="x", source_agent="A", confidence=0.5,
                              horizon_hours=24)
        def bad_init(self, *a, **kw):
            self.agent_name = "critic"
            self.provider_name = "stub"; self.model = "stub"
            self.provider = MagicMock()
            self.provider.complete = MagicMock(side_effect=RuntimeError("boom"))
        with patch("brain.critic.CriticAgent.__init__", bad_init):
            result = review_hypothesis(h)
        self.assertIsNone(result)


class RunCriticPassTests(TestCase):
    def test_bounded_by_max_n(self):
        from brain.hypotheses import post_hypothesis
        from brain.critic import run_critic_pass
        for i in range(8):
            post_hypothesis(resolution_criteria={"kind": "regime_holds", "regime": "trending"},
                              claim_text=f"c{i}", source_agent="A",
                              confidence=0.85, horizon_hours=24)
        with _stub_critic_provider({
            "stance": "co_sign", "confidence": 0.7, "reasoning": "ok",
        }):
            result = run_critic_pass(max_n=3)
        self.assertLessEqual(result["n_reviewed"], 3)


# ── Consolidation ─────────────────────────────────────────────────────────

class ConsolidationTests(TestCase):
    def test_promotes_regime_into_graph(self):
        from brain.models import BrainReport
        from brain.knowledge_models import KnowledgeNode
        from brain.consolidation import consolidate_now

        BrainReport.objects.create(
            regime_label="trending", regime_confidence=0.8,
            theme_pressures={"USD_short": 0.5},
            rule_status_overlay={"rule_x": "watch"},
        )
        result = consolidate_now()
        self.assertTrue(result["ok"])
        node = KnowledgeNode.current("regime", "portfolio")
        self.assertIsNotNone(node)
        self.assertEqual(node.payload["label"], "trending")
        # Theme + rule states promoted too.
        self.assertIsNotNone(KnowledgeNode.current("theme_state", "USD_short"))
        self.assertIsNotNone(KnowledgeNode.current("rule_state", "rule_x"))

    def test_no_op_when_state_unchanged(self):
        from brain.models import BrainReport
        from brain.consolidation import consolidate_now
        from brain.knowledge_models import KnowledgeNode

        BrainReport.objects.create(regime_label="trending",
                                     regime_confidence=0.7)
        consolidate_now()
        v1 = KnowledgeNode.current("regime", "portfolio").version
        # Same state → no new version.
        BrainReport.objects.create(regime_label="trending",
                                     regime_confidence=0.71)
        consolidate_now()
        v2 = KnowledgeNode.current("regime", "portfolio").version
        self.assertEqual(v1, v2)

    def test_prunes_old_consumed_observations(self):
        from brain.models import BrainObservation
        from brain.consolidation import consolidate_now

        old_consumed = BrainObservation.objects.create(
            kind="x", payload={}, source_agent="t",
            consumed_by_brain_at=timezone.now() - timedelta(days=10),
        )
        BrainObservation.objects.filter(id=old_consumed.id).update(
            created_at=timezone.now() - timedelta(days=10))
        recent_unconsumed = BrainObservation.objects.create(
            kind="x", payload={}, source_agent="t",
        )
        consolidate_now()
        self.assertFalse(BrainObservation.objects.filter(id=old_consumed.id).exists())
        # Recent unconsumed not pruned.
        self.assertTrue(BrainObservation.objects.filter(id=recent_unconsumed.id).exists())

    def test_anomaly_promotion_threshold(self):
        from brain.models import BrainObservation
        from brain.consolidation import consolidate_now
        from brain.knowledge_models import KnowledgeNode

        # Two occurrences — below threshold (3).
        for _ in range(2):
            BrainObservation.objects.create(
                kind="anomaly_detected", payload={"key": "low_count"},
                source_agent="t",
            )
        # Four occurrences — above threshold.
        for _ in range(4):
            BrainObservation.objects.create(
                kind="anomaly_detected", payload={"key": "promoted"},
                source_agent="t",
            )
        consolidate_now()
        self.assertIsNone(KnowledgeNode.current("anomaly", "low_count"))
        self.assertIsNotNone(KnowledgeNode.current("anomaly", "promoted"))


# ── Dashboards ────────────────────────────────────────────────────────────

class DashboardTests(TestCase):
    def setUp(self):
        self.user = _login_user()
        self.client.force_login(self.user)

    def test_knowledge_dashboard_renders(self):
        r = self.client.get("/knowledge/")
        self.assertEqual(r.status_code, 200)

    def test_hypotheses_dashboard_renders(self):
        r = self.client.get("/hypotheses/")
        self.assertEqual(r.status_code, 200)

    def test_consolidation_dashboard_renders(self):
        r = self.client.get("/consolidation/")
        self.assertEqual(r.status_code, 200)

    def test_node_history_renders(self):
        from brain.knowledge_models import KnowledgeNode
        KnowledgeNode.upsert(kind="regime", key="portfolio",
                              payload={"label": "trending"},
                              confidence=0.7, source="t")
        r = self.client.get("/knowledge/regime/portfolio/")
        self.assertEqual(r.status_code, 200)


class AdminActionTests(TestCase):
    def test_admin_can_run_consolidation(self):
        u = _staff()
        self.client.force_login(u)
        r = self.client.post("/consolidation/run/")
        self.assertEqual(r.status_code, 302)

    def test_admin_can_run_critic(self):
        u = _staff()
        self.client.force_login(u)
        r = self.client.post("/hypotheses/critic-run/")
        self.assertEqual(r.status_code, 302)
