"""A proposal the platform refuses leaves a trace the operator can read.

The first frontier-model run on the VPS returned three ideas; the
validator refused one and the run reported `n_validation_rejected: 1` —
and nothing else. The reason went to one INFO line on the `brain`
logger, which production silenced (root at WARNING, `brain` absent from
the INFO list). The operator had paid for three ideas and could see two.

Now a refused idea is written as a REJECTED row — reviewed by
"validator", the reason in the notes, no setup, no rule, no hypothesis —
and the brain page's history says why. The `brain` logger keeps its INFO
lines in production, like every other Sauron app.

Run with:  python manage.py test tests.test_rejected_proposals_leave_a_trace
"""
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

User = get_user_model()


def _good(slug="trace_ok"):
    return {
        "name_slug": slug, "rationale_md": "cites the ledger",
        "inspiration": "ledger", "direction": "bullish",
        "asset_classes": ["stock"],
        "conditions": [{"kind": "price_pattern",
                        "params": {"pattern": "above_ma"}, "weight": 1.0}],
        "min_match_score": 0.6, "suggested_horizon_days": 5,
        "confidence": 0.6,
    }


class TheLogsKeepTheReasonTests(SimpleTestCase):

    def test_the_brain_logs_at_info_in_production(self):
        from core.logging_config import SAURON_APPS, build_logging_config
        cfg = build_logging_config(debug=False)
        for app in ("brain", "instruments", "indicators", "backtester"):
            self.assertIn(app, SAURON_APPS)
            self.assertEqual(cfg["loggers"][app]["level"], "INFO", app)
        self.assertEqual(cfg["root"]["level"], "WARNING")


class TheTraceTests(TestCase):

    def test_a_validator_refusal_is_a_rejected_row_with_the_reason(self):
        from brain.generator_models import GeneratedSetupProposal
        from brain.strategy_generator import _persist_proposal
        bad = _good("bad_kind")
        bad["conditions"] = [{"kind": "fake_evaluator", "weight": 1.0}]
        row = _persist_proposal(bad, model="claude-fable-5-1",
                                tokens_in=0, tokens_out=0, cost_usd=1.0)
        self.assertIsNone(row)
        trace = GeneratedSetupProposal.objects.get()
        self.assertEqual(trace.status, GeneratedSetupProposal.STATUS_REJECTED)
        self.assertEqual(trace.proposed_name, "bad_kind")
        self.assertEqual(trace.reviewed_by, "validator")
        self.assertIsNotNone(trace.reviewed_at)
        self.assertIn("fake_evaluator", trace.review_notes)
        self.assertEqual(trace.error, trace.review_notes)
        self.assertEqual(trace.model_used, "claude-fable-5-1")
        # The run's cost sits on the rows that were persisted, not here.
        self.assertEqual(float(trace.cost_usd), 0.0)
        self.assertIsNone(trace.setup)
        self.assertIsNone(trace.rule_control)
        self.assertIsNone(trace.hypothesis)

    def test_garbage_fields_still_leave_a_trace(self):
        """The validator refuses shapes, so the trace must survive them:
        a non-string name, a direction longer than the column, lists that
        are not lists."""
        from brain.generator_models import GeneratedSetupProposal
        from brain.strategy_generator import _persist_proposal
        bad = {"name_slug": 42, "direction": "sideways_forever_and_ever",
               "asset_classes": "stock", "conditions": {"kind": "x"}}
        self.assertIsNone(_persist_proposal(bad, model="m", tokens_in=0,
                                            tokens_out=0, cost_usd=0.0))
        trace = GeneratedSetupProposal.objects.get()
        self.assertEqual(trace.proposed_name, "42")
        self.assertEqual(len(trace.direction), 10)
        self.assertEqual(trace.asset_classes, [])
        self.assertEqual(trace.conditions, [])
        self.assertIn("name_slug", trace.review_notes)

    def test_a_name_collision_leaves_a_trace_too(self):
        from brain.generator_models import GeneratedSetupProposal
        from brain.strategy_generator import (_final_setup_name,
                                              _persist_proposal)
        from signals.models_opportunity import OpportunitySetup
        OpportunitySetup.objects.create(
            name=_final_setup_name("twin"), description="pre-existing",
            direction="bullish", asset_classes=["stock"], conditions=[],
            min_match_score=0.6, suggested_horizon_days=5, sizing={})
        self.assertIsNone(_persist_proposal(_good("twin"), model="m",
                                            tokens_in=0, tokens_out=0,
                                            cost_usd=0.0))
        trace = GeneratedSetupProposal.objects.get()
        self.assertEqual(trace.status, GeneratedSetupProposal.STATUS_REJECTED)
        self.assertIn("collision", trace.review_notes)
        # Nothing but the pre-existing setup: the trace created no draft.
        self.assertEqual(OpportunitySetup.objects.count(), 1)

    def test_a_good_proposal_leaves_no_rejected_row(self):
        from brain.generator_models import GeneratedSetupProposal
        from brain.strategy_generator import _persist_proposal
        row = _persist_proposal(_good(), model="m", tokens_in=0,
                                tokens_out=0, cost_usd=0.0)
        self.assertIsNotNone(row)
        self.assertEqual(GeneratedSetupProposal.objects.filter(
            status=GeneratedSetupProposal.STATUS_REJECTED).count(), 0)

    def test_the_run_counts_the_trace_as_rejected_not_persisted(self):
        from unittest.mock import MagicMock, patch
        import json
        from brain.generator_models import GeneratedSetupProposal
        from brain.strategy_generator import generate_strategies_now
        bad = _good("bad_run")
        bad["direction"] = "wibble"
        raw = json.dumps({"proposals": [_good("good_run"), bad]})
        usage = {"input_tokens": 10, "output_tokens": 5, "cost_usd": 0.5}

        def patched_init(self, *a, **kw):
            self.agent_name = "strategy_generator"
            self.provider_name = "stub"
            self.model = "claude-stub"
            self.provider = MagicMock()
            self.provider.complete = MagicMock(return_value=(raw, usage))

        with patch("brain.strategy_generator.StrategyGeneratorAgent.__init__",
                   patched_init):
            out = generate_strategies_now()
        self.assertEqual(out["n_persisted"], 1)
        self.assertEqual(out["n_validation_rejected"], 1)
        self.assertEqual(out["proposal_ids"], [GeneratedSetupProposal.objects.get(
            status=GeneratedSetupProposal.STATUS_PENDING).pk])
        trace = GeneratedSetupProposal.objects.get(
            status=GeneratedSetupProposal.STATUS_REJECTED)
        self.assertIn("wibble", trace.review_notes)
        self.assertEqual(trace.model_used, "claude-stub")


class ThePageSaysWhyTests(TestCase):

    def test_the_history_shows_the_reason(self):
        from brain.strategy_generator import _persist_proposal
        bad = _good("shown_on_page")
        bad["conditions"] = [{"kind": "invented_kind", "weight": 1.0}]
        _persist_proposal(bad, model="m", tokens_in=0, tokens_out=0,
                          cost_usd=0.0)
        user = User.objects.create_user("gen_u", password="x", is_staff=True)
        self.client.force_login(user)
        resp = self.client.get("/generated/")
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("shown_on_page", body)
        self.assertIn("validator", body)
        self.assertIn("invented_kind", body)
