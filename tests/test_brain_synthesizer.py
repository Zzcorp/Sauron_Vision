"""Tests for Phase 37.2-37.4 — synthesizer, context, calibration, dashboard,
and downstream-agent context injection.

Covers:
  - _build_world_snapshot returns the expected shape with empty DB
  - _persist_report clamps invalid input + writes a row
  - _emit_predictions creates AgentPrediction rows
  - synthesize_now happy-path with a mocked AI provider
  - synthesize_now error-path produces an error-stamped report (no exception)
  - get_brain_context returns None when no fresh report
  - get_brain_context returns compact dict when fresh report exists
  - context_for_prompt produces a markdown block
  - PreTradeSanity / DecayInvestigator / StrategyMutator inject brain context
    when present, omit cleanly when not
  - calibration resolver: regime_persistence, rule_decay_continues, rule_recovers
  - Brain dashboard renders 200
  - brain_run_now (admin) runs synthesis + redirects
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _staff(username="staff_brain"):
    u = User.objects.create_user(username=username, password="x")
    u.is_staff = True
    u.save()
    return u


# ── Snapshot ──────────────────────────────────────────────────────────────

class WorldSnapshotTests(TestCase):
    def test_empty_db_returns_shape(self):
        from brain.synthesizer import _build_world_snapshot
        snap = _build_world_snapshot()
        for key in ("as_of", "observations", "observations_count_by_kind",
                    "open_positions", "rule_track_records",
                    "regime_probes", "unresolved_decay_alerts"):
            self.assertIn(key, snap)
        self.assertEqual(snap["observations"], [])

    def test_observations_listed(self):
        from brain.synthesizer import _build_world_snapshot
        from brain.observations import record_observation
        record_observation(kind="gate_reject", payload={"r": 1}, source="t")
        record_observation(kind="fill_closed", payload={"r": 2}, source="t")
        snap = _build_world_snapshot()
        self.assertEqual(len(snap["observations"]), 2)
        self.assertIn("gate_reject", snap["observations_count_by_kind"])


# ── Response parsing ──────────────────────────────────────────────────────

class ParseResponseTests(TestCase):
    """The prompt forbids prose around the JSON; the live model appends it
    anyway. A strict loads() threw a whole synthesis away over trailing
    commentary ("Extra data: char 1476", live, 2026-08-18) — the parser
    must take the first complete object and shrug at the tail."""

    def _agent(self):
        from brain.synthesizer import SauronMindAgent
        return SauronMindAgent.__new__(SauronMindAgent)

    def test_trailing_commentary_is_ignored(self):
        out = self._agent().parse_response(
            '{"regime_label": "trending", "regime_confidence": 0.7}\n'
            'Note: confidence is moderate because volume is thin.')
        self.assertEqual(out["regime_label"], "trending")

    def test_a_second_object_is_ignored(self):
        out = self._agent().parse_response(
            '{"regime_label": "risk_off"}{"regime_label": "risk_on"}')
        self.assertEqual(out["regime_label"], "risk_off")

    def test_leading_prose_and_fences_still_parse(self):
        out = self._agent().parse_response(
            '```json\nHere is the report: {"regime_label": "unknown"}\n```')
        self.assertEqual(out["regime_label"], "unknown")

    def test_no_object_still_raises(self):
        with self.assertRaises(ValueError):
            self._agent().parse_response("definitely not json")

    def test_non_dict_first_value_raises(self):
        # find("{") skips the array; the first OBJECT inside it parses,
        # which is a dict — so use a payload with no object at all after
        # a brace-less array to pin the non-dict path via a bare number
        # wrapped in an object-less response.
        with self.assertRaises(ValueError):
            self._agent().parse_response('[1, 2, 3]')


# ── Persistence + clamping ────────────────────────────────────────────────

class PersistReportTests(TestCase):
    def test_clamps_bad_regime_to_unknown(self):
        from brain.synthesizer import _persist_report
        report = _persist_report(
            parsed={"regime_label": "wibble", "regime_confidence": 1.5,
                    "portfolio_health_score": -2.0},
            snapshot={}, model="t", tokens_in=0, tokens_out=0,
            cost_usd=0.0, n_consumed=0,
        )
        self.assertEqual(report.regime_label, "unknown")
        self.assertEqual(report.regime_confidence, 1.0)  # clamped
        self.assertEqual(report.portfolio_health_score, 0.0)  # clamped

    def test_clamps_invalid_overlay_values(self):
        from brain.synthesizer import _persist_report
        report = _persist_report(
            parsed={"regime_label": "trending",
                    "rule_status_overlay": {"r1": "bogus", "r2": "watch"}},
            snapshot={}, model="t", tokens_in=0, tokens_out=0,
            cost_usd=0.0, n_consumed=0,
        )
        self.assertNotIn("r1", report.rule_status_overlay)
        self.assertEqual(report.rule_status_overlay.get("r2"), "watch")


class EmitPredictionsTests(TestCase):
    def test_creates_agent_prediction_rows(self):
        from brain.synthesizer import _emit_predictions, _persist_report
        from ai_agents.models import AgentPrediction
        report = _persist_report(parsed={"regime_label": "trending"},
                                  snapshot={}, model="t", tokens_in=0,
                                  tokens_out=0, cost_usd=0.0, n_consumed=0)
        n = _emit_predictions(report, {"predictions": [
            {"prediction_type": "regime_persistence", "predicted_value": "trending",
             "confidence": 0.7, "horizon_hours": 12, "rationale": "x"},
            {"prediction_type": "rule_decay_continues", "predicted_value": "rule_x",
             "confidence": 0.5, "horizon_hours": 48, "rationale": "y"},
        ]})
        self.assertEqual(n, 2)
        self.assertEqual(AgentPrediction.objects.filter(agent="sauron_mind").count(), 2)


# ── synthesize_now ────────────────────────────────────────────────────────

def _stub_provider(parsed_dict, raw_text=None, usage=None):
    """Build a context manager that stubs the agent's `provider.complete`."""
    import json
    raw = raw_text if raw_text is not None else json.dumps(parsed_dict)
    usage = usage or {"input_tokens": 100, "output_tokens": 50, "cost_usd": 0.001}

    def patched_init(self, *args, **kwargs):
        # Bypass real provider construction.
        self.agent_name = "sauron_mind"
        self.provider_name = "stub"
        self.model = "claude-stub"
        self.provider = MagicMock()
        self.provider.complete = MagicMock(return_value=(raw, usage))

    return patch("brain.synthesizer.SauronMindAgent.__init__", patched_init)


class SynthesizeNowTests(TestCase):
    def test_happy_path_writes_report_and_consumes_obs(self):
        from brain.synthesizer import synthesize_now
        from brain.observations import record_observation
        from brain.models import BrainReport, BrainObservation

        record_observation(kind="gate_reject", payload={}, source="t")
        record_observation(kind="fill_closed", payload={}, source="t")

        parsed = {
            "regime_label": "trending",
            "regime_confidence": 0.8,
            "portfolio_health_score": 0.7,
            "top_concerns": [{"kind": "decay", "severity": 0.6, "ref": "rule_x", "text": "watch this"}],
            "theme_pressures": {"USD_short": 0.5},
            "rule_status_overlay": {"rule_x": "watch"},
            "narrative_md": "Markets are trending.",
            "predictions": [{"prediction_type": "regime_persistence",
                              "predicted_value": "trending",
                              "confidence": 0.8, "horizon_hours": 6,
                              "rationale": "Hurst > 0.55 across the book"}],
        }
        with _stub_provider(parsed):
            result = synthesize_now()

        self.assertTrue(result["ok"])
        self.assertEqual(result["regime"], "trending")
        report = BrainReport.objects.first()
        self.assertEqual(report.regime_label, "trending")
        self.assertEqual(report.n_observations_consumed, 2)
        # Observations should be marked consumed.
        self.assertEqual(BrainObservation.objects.filter(consumed_by_brain_at__isnull=True).count(), 0)

    def test_error_path_persists_error_stamped_report(self):
        from brain.synthesizer import synthesize_now
        from brain.models import BrainReport

        def bad_init(self, *a, **kw):
            self.provider_name = "stub"
            self.model = "claude-stub"
            self.provider = MagicMock()
            self.provider.complete = MagicMock(side_effect=RuntimeError("api down"))

        with patch("brain.synthesizer.SauronMindAgent.__init__", bad_init):
            result = synthesize_now()

        self.assertFalse(result["ok"])
        self.assertIn("api down", result["error"])
        report = BrainReport.objects.first()
        self.assertIn("api down", report.error)
        self.assertEqual(report.regime_label, "unknown")


# ── Context helper ────────────────────────────────────────────────────────

class GetBrainContextTests(TestCase):
    def test_returns_none_when_empty(self):
        from brain.context import get_brain_context
        self.assertIsNone(get_brain_context())

    def test_returns_compact_dict_when_fresh(self):
        from brain.models import BrainReport
        from brain.context import get_brain_context
        BrainReport.objects.create(
            regime_label="trending", regime_confidence=0.8,
            portfolio_health_score=0.7,
            top_concerns=[
                {"kind": "decay", "severity": 0.9, "text": "x"},
                {"kind": "exposure", "severity": 0.5, "text": "y"},
            ],
            theme_pressures={"USD_short": 0.6, "vol_long": 0.3},
            rule_status_overlay={"r1": "watch", "r2": "active",
                                  "r3": "pause_recommended"},
            narrative_md="ok",
            valid_until=timezone.now() + timedelta(minutes=30),
        )
        ctx = get_brain_context()
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx["regime_label"], "trending")
        # Concerns sorted by severity desc, top 3.
        self.assertEqual(ctx["top_concerns"][0]["kind"], "decay")
        # Active rules dropped from overlay (only watch / pause_recommended remain).
        self.assertNotIn("r2", ctx["rule_status_overlay"])
        self.assertIn("r3", ctx["rule_status_overlay"])

    def test_stale_report_returns_none(self):
        from brain.models import BrainReport
        from brain.context import get_brain_context
        old = timezone.now() - timedelta(hours=2)
        report = BrainReport.objects.create(
            regime_label="trending", regime_confidence=0.5,
        )
        # Force it stale.
        BrainReport.objects.filter(id=report.id).update(created_at=old)
        self.assertIsNone(get_brain_context())

    def test_context_for_prompt_renders_markdown(self):
        from brain.models import BrainReport
        from brain.context import context_for_prompt
        BrainReport.objects.create(
            regime_label="risk_off", regime_confidence=0.7,
            portfolio_health_score=0.4,
            theme_pressures={"USD_short": 0.6},
            rule_status_overlay={"momentum_trend": "pause_recommended"},
            top_concerns=[{"kind": "decay", "severity": 0.7, "text": "rule_x decaying"}],
        )
        block = context_for_prompt()
        self.assertIn("Sauron's Mind", block)
        self.assertIn("risk_off", block)
        self.assertIn("USD_short", block)
        self.assertIn("pause_recommended", block)


# ── Agent injection ───────────────────────────────────────────────────────

class AgentInjectionTests(TestCase):
    def setUp(self):
        from brain.models import BrainReport
        BrainReport.objects.create(
            regime_label="risk_off", regime_confidence=0.7,
            portfolio_health_score=0.4,
            theme_pressures={"USD_short": 0.6},
            rule_status_overlay={"momentum_trend": "pause_recommended"},
            top_concerns=[{"kind": "decay", "severity": 0.7, "text": "rule_x decaying"}],
        )

    def _stub_init(self, agent_cls):
        """Stub agent __init__ so we don't hit real providers."""
        def patched(self, *a, **kw):
            self.agent_name = agent_cls.agent_name
            self.provider_name = "stub"
            self.model = "stub"
            self.provider = MagicMock()
        return patch.object(agent_cls, "__init__", patched)

    def test_pretrade_sanity_includes_brain_block(self):
        from ai_agents.agents.pretrade_sanity import PreTradeSanityAgent
        with self._stub_init(PreTradeSanityAgent):
            agent = PreTradeSanityAgent()
            ctx = agent.build_context(symbol="X", direction="long",
                                       entry=100, stop=99, target=103,
                                       rule_name="rule_x")
        self.assertIn("Sauron's Mind", ctx)
        self.assertIn("risk_off", ctx)

    def test_decay_investigator_includes_brain_block(self):
        from ai_agents.agents.decay_investigator import DecayInvestigatorAgent
        with self._stub_init(DecayInvestigatorAgent):
            agent = DecayInvestigatorAgent()
            ctx = agent.build_context(rule_name="rule_x")
        self.assertIn("Sauron's Mind", ctx)

    def test_strategy_mutator_includes_brain_block(self):
        from ai_agents.agents.strategy_mutator import StrategyMutatorAgent
        with self._stub_init(StrategyMutatorAgent):
            agent = StrategyMutatorAgent()
            ctx = agent.build_context(rule_name="rule_x", schema={},
                                        current_params={}, track_record={})
        self.assertIn("Sauron's Mind", ctx)

    def test_no_brain_no_block(self):
        """Without a fresh BrainReport, agents work cleanly."""
        from brain.models import BrainReport
        BrainReport.objects.all().delete()
        from ai_agents.agents.pretrade_sanity import PreTradeSanityAgent
        with self._stub_init(PreTradeSanityAgent):
            agent = PreTradeSanityAgent()
            ctx = agent.build_context(symbol="X", direction="long",
                                       entry=100, stop=99, target=103,
                                       rule_name="rule_x")
        self.assertNotIn("Sauron's Mind", ctx)
        self.assertIn("Proposed trade", ctx)


# ── Calibration resolver ──────────────────────────────────────────────────

class CalibrationResolverTests(TestCase):
    def test_regime_persistence_correct(self):
        from brain.calibration import resolve_due_brain_predictions
        from brain.models import BrainReport
        from ai_agents.models import AgentPrediction

        past_deadline = timezone.now() - timedelta(minutes=10)
        AgentPrediction.objects.create(
            agent="sauron_mind", prediction_type="regime_persistence",
            predicted_value="trending", confidence=0.8,
            expected_resolution_at=past_deadline,
        )
        # Create a report AFTER the deadline.
        BrainReport.objects.create(regime_label="trending", regime_confidence=0.9)

        result = resolve_due_brain_predictions()
        self.assertEqual(result["resolved"], 1)
        pred = AgentPrediction.objects.first()
        self.assertTrue(pred.was_correct)

    def test_regime_persistence_wrong(self):
        from brain.calibration import resolve_due_brain_predictions
        from brain.models import BrainReport
        from ai_agents.models import AgentPrediction
        AgentPrediction.objects.create(
            agent="sauron_mind", prediction_type="regime_persistence",
            predicted_value="trending", confidence=0.8,
            expected_resolution_at=timezone.now() - timedelta(minutes=5),
        )
        BrainReport.objects.create(regime_label="risk_off", regime_confidence=0.7)
        resolve_due_brain_predictions()
        pred = AgentPrediction.objects.first()
        self.assertFalse(pred.was_correct)

    def test_unknown_resolver_skipped(self):
        from brain.calibration import resolve_due_brain_predictions
        from ai_agents.models import AgentPrediction
        AgentPrediction.objects.create(
            agent="sauron_mind", prediction_type="totally_made_up",
            predicted_value="x", confidence=0.5,
            expected_resolution_at=timezone.now() - timedelta(minutes=5),
        )
        result = resolve_due_brain_predictions()
        self.assertEqual(result["resolved"], 0)
        self.assertEqual(result["skipped"], 1)


# ── Dashboard ─────────────────────────────────────────────────────────────

class BrainDashboardTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="brain_dash_u", password="x")
        self.client.force_login(self.user)

    def test_dashboard_renders_200_empty(self):
        r = self.client.get("/brain/")
        self.assertEqual(r.status_code, 200)

    def test_dashboard_shows_latest_report(self):
        from brain.models import BrainReport
        BrainReport.objects.create(
            regime_label="trending", regime_confidence=0.7,
            portfolio_health_score=0.6,
            narrative_md="markets trending up",
        )
        r = self.client.get("/brain/")
        body = r.content.decode("utf-8", errors="ignore")
        self.assertIn("TRENDING", body)
        self.assertIn("markets trending up", body)


class BrainRunNowTests(TestCase):
    def test_admin_can_trigger_run(self):
        u = _staff()
        self.client.force_login(u)
        from brain.models import BrainReport
        with _stub_provider({"regime_label": "trending",
                              "regime_confidence": 0.7,
                              "portfolio_health_score": 0.6,
                              "narrative_md": "ok",
                              "predictions": []}):
            r = self.client.post("/brain/run/")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(BrainReport.objects.count(), 1)

    def test_non_staff_redirected(self):
        from brain.models import BrainReport
        u = User.objects.create_user(username="not_staff", password="x")
        self.client.force_login(u)
        r = self.client.post("/brain/run/")
        # staff_member_required redirects non-staff to admin login.
        self.assertEqual(r.status_code, 302)
        self.assertIn("/admin/login/", r.url)
        # And no synthesis ran.
        self.assertEqual(BrainReport.objects.count(), 0)
