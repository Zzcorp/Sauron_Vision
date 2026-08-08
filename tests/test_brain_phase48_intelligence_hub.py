"""Tests for Phase 48 — /intelligence/ hub page.

Covers:
  - /intelligence/ renders 200 with empty DB
  - Hero strip shows regime / posture / brain trust / obs queued
  - Pending hypotheses + recent resolved sections render correctly
  - Pending generated proposals + open auto-demotions render
  - Knowledge graph counts shown
  - Sidebar nav link resolves
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone


class IntelligenceHubRenderTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="ih_user", password="x")
        self.client.force_login(self.user)

    def test_empty_db_renders_200(self):
        r = self.client.get("/intelligence/")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode("utf-8", errors="ignore")
        self.assertIn("Intelligence hub", body)

    def test_hero_strip_shows_regime_and_posture(self):
        from brain.models import BrainReport
        from brain.briefing_models import StrategistBriefing
        BrainReport.objects.create(
            regime_label="trending", regime_confidence=0.8,
            valid_until=timezone.now() + timedelta(minutes=30),
        )
        StrategistBriefing.objects.create(
            outlook_md="USD weakens.",
            posture="defensive", posture_rationale="risk-off",
        )
        r = self.client.get("/intelligence/")
        body = r.content.decode("utf-8", errors="ignore")
        self.assertIn("TRENDING", body)
        self.assertIn("DEFENSIVE", body)
        self.assertIn("USD weakens", body)

    def test_pending_hypotheses_listed(self):
        from brain.knowledge_models import Hypothesis
        Hypothesis.objects.create(
            claim_text="USD will weaken further",
            source_agent="sauron_mind",
            confidence=0.7,
            resolution_deadline=timezone.now() + timedelta(hours=24),
        )
        r = self.client.get("/intelligence/")
        body = r.content.decode("utf-8", errors="ignore")
        self.assertIn("USD will weaken further", body)
        self.assertIn("sauron_mind", body)

    def test_pending_generated_proposals_listed(self):
        from brain.generator_models import GeneratedSetupProposal
        from signals.models_opportunity import OpportunitySetup
        setup = OpportunitySetup.objects.create(
            name="generated_test", description="t", direction="bullish",
            asset_classes=["stock"], conditions=[],
            min_match_score=0.6, suggested_horizon_days=5, sizing={},
            is_active=False,
        )
        GeneratedSetupProposal.objects.create(
            proposed_name="generated_test_pending", direction="bullish",
            asset_classes=["stock"], conditions=[],
            confidence=0.65, setup=setup,
        )
        r = self.client.get("/intelligence/")
        body = r.content.decode("utf-8", errors="ignore")
        self.assertIn("generated_test_pending", body)

    def test_open_demotions_listed(self):
        from brain.demoter_models import RuleDemotion
        RuleDemotion.objects.create(
            rule_name="failing_rule_x", criterion="consecutive_losses",
            metrics={"avg_r": -0.8},
        )
        r = self.client.get("/intelligence/")
        body = r.content.decode("utf-8", errors="ignore")
        self.assertIn("failing_rule_x", body)
        self.assertIn("consecutive_losses", body)

    def test_knowledge_graph_counts(self):
        from brain.knowledge_models import KnowledgeNode
        KnowledgeNode.upsert(kind="regime", key="portfolio",
                              payload={"label": "trending"},
                              confidence=0.7, source="t")
        KnowledgeNode.upsert(kind="theme_state", key="USD",
                              payload={"pressure": 0.5},
                              confidence=0.5, source="t")
        r = self.client.get("/intelligence/")
        body = r.content.decode("utf-8", errors="ignore")
        self.assertIn("regime", body)
        self.assertIn("theme_state", body)


class IntelligenceHubURLTests(TestCase):
    def test_url_reverses(self):
        self.assertEqual(reverse("intelligence_hub"), "/intelligence/")

    def test_login_required(self):
        r = self.client.get("/intelligence/")
        # Anonymous users redirected to login.
        self.assertEqual(r.status_code, 302)
