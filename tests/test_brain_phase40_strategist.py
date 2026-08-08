"""Tests for Phase 40 — Strategist Briefing.

Covers:
  - _build_strategist_snapshot returns expected shape
  - _persist_briefing clamps invalid input + writes a row
  - run_strategist_now happy path with mocked provider
  - run_strategist_now error path persists error-stamped briefing
  - _emit_idea_hypotheses creates Hypotheses for gradeable ideas only
  - /briefing/ dashboard renders 200
  - admin briefing_run_now triggers + redirects
"""
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.test import TestCase


def _staff(name="staff_p40"):
    u = User.objects.create_user(username=name, password="x")
    u.is_staff = True
    u.save()
    return u


def _stub_strategist_provider(parsed_dict, raw_text=None):
    import json
    raw = raw_text if raw_text is not None else json.dumps(parsed_dict)
    usage = {"input_tokens": 8000, "output_tokens": 1500, "cost_usd": 0.30}

    def patched_init(self, *a, **kw):
        self.agent_name = "strategist"
        self.provider_name = "stub"
        self.model = "claude-stub"
        self.provider = MagicMock()
        self.provider.complete = MagicMock(return_value=(raw, usage))
    return patch("brain.strategist.StrategistAgent.__init__", patched_init)


class StrategistSnapshotTests(TestCase):
    def test_empty_db_returns_shape(self):
        from brain.strategist import _build_strategist_snapshot
        snap = _build_strategist_snapshot()
        for key in ("as_of", "recent_brain_reports", "knowledge_graph",
                    "recent_resolved_hypotheses", "agent_trust_scores",
                    "pending_hypotheses"):
            self.assertIn(key, snap)


class PersistBriefingTests(TestCase):
    def test_clamps_bad_posture(self):
        from brain.strategist import _persist_briefing
        b = _persist_briefing(parsed={"posture": "wibble", "outlook_md": "ok"},
                                model="t", tokens_in=10, tokens_out=5,
                                cost_usd=0.001)
        self.assertEqual(b.posture, "balanced")
        self.assertEqual(b.outlook_md, "ok")

    def test_caps_lists(self):
        from brain.strategist import _persist_briefing
        b = _persist_briefing(parsed={
            "posture": "defensive",
            "watchlist": [{"x": i} for i in range(20)],
            "ideas": [{"summary": str(i)} for i in range(10)],
        }, model="t", tokens_in=0, tokens_out=0, cost_usd=0.0)
        self.assertEqual(len(b.watchlist), 5)
        self.assertEqual(len(b.ideas), 5)


class RunStrategistTests(TestCase):
    def test_happy_path(self):
        from brain.strategist import run_strategist_now
        from brain.briefing_models import StrategistBriefing
        parsed = {
            "outlook_md": "USD weakens; equities firm.",
            "posture": "balanced",
            "posture_rationale": "neutral signals across timeframes",
            "watchlist": [{"kind": "macro", "ref": "DXY",
                            "what_to_watch": "drop below 102"}],
            "ideas": [{"summary": "regime stays trending",
                        "horizon_hours": 24, "confidence": 0.7,
                        "hypothesis_kind": "regime_holds",
                        "hypothesis_payload": {"regime": "trending"}}],
        }
        with _stub_strategist_provider(parsed):
            r = run_strategist_now()
        self.assertTrue(r["ok"])
        self.assertEqual(r["posture"], "balanced")
        self.assertEqual(r["n_ideas_posted_as_hypotheses"], 1)
        self.assertEqual(StrategistBriefing.objects.count(), 1)

    def test_error_path_persists_briefing(self):
        from brain.strategist import run_strategist_now
        from brain.briefing_models import StrategistBriefing
        def bad_init(self, *a, **kw):
            self.agent_name = "strategist"
            self.provider_name = "stub"; self.model = "stub"
            self.provider = MagicMock()
            self.provider.complete = MagicMock(side_effect=RuntimeError("api 500"))
        with patch("brain.strategist.StrategistAgent.__init__", bad_init):
            r = run_strategist_now()
        self.assertFalse(r["ok"])
        self.assertIn("api 500", r["error"])
        b = StrategistBriefing.objects.first()
        self.assertIn("api 500", b.error)


class EmitIdeaHypothesesTests(TestCase):
    def test_only_gradeable_ideas_become_hypotheses(self):
        from brain.strategist import _persist_briefing, _emit_idea_hypotheses
        from brain.knowledge_models import Hypothesis
        b = _persist_briefing(parsed={"posture": "balanced", "outlook_md": ""},
                                model="t", tokens_in=0, tokens_out=0,
                                cost_usd=0.0)
        ideas = [
            {"summary": "yes", "horizon_hours": 24, "confidence": 0.7,
             "hypothesis_kind": "regime_holds",
             "hypothesis_payload": {"regime": "trending"}},
            {"summary": "no kind", "confidence": 0.5,
             "hypothesis_kind": None},
            {"summary": "bad kind", "confidence": 0.5,
             "hypothesis_kind": "made_up_kind",
             "hypothesis_payload": {"x": 1}},
            {"summary": "missing payload", "confidence": 0.5,
             "hypothesis_kind": "rule_avg_r"},
        ]
        n = _emit_idea_hypotheses(b, ideas)
        self.assertEqual(n, 1)
        self.assertEqual(Hypothesis.objects.filter(source_agent="strategist").count(), 1)


class BriefingDashboardTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="b_view", password="x")
        self.client.force_login(self.user)

    def test_renders_empty(self):
        r = self.client.get("/briefing/")
        self.assertEqual(r.status_code, 200)

    def test_shows_latest(self):
        from brain.briefing_models import StrategistBriefing
        StrategistBriefing.objects.create(
            outlook_md="USD trending lower.",
            posture="defensive",
            posture_rationale="risk-off pulse across the book",
            watchlist=[{"kind": "macro", "ref": "DXY",
                         "what_to_watch": "break of 102"}],
            ideas=[],
        )
        r = self.client.get("/briefing/")
        body = r.content.decode("utf-8", errors="ignore")
        self.assertIn("DEFENSIVE", body)
        self.assertIn("USD trending lower", body)


class BriefingAdminTests(TestCase):
    def test_admin_can_run_now(self):
        u = _staff()
        self.client.force_login(u)
        with _stub_strategist_provider({
            "outlook_md": "ok", "posture": "balanced",
            "watchlist": [], "ideas": [],
        }):
            r = self.client.post("/briefing/run/")
        self.assertEqual(r.status_code, 302)

    def test_non_staff_blocked(self):
        u = User.objects.create_user(username="non_staff_b", password="x")
        self.client.force_login(u)
        r = self.client.post("/briefing/run/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/admin/login/", r.url)
