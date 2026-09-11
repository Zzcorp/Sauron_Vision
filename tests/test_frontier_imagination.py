"""The weekly imagination pass: the frontier model, grounded in evidence.

The strategy generator already existed — weekly, proposals landing as
draft setups the admin must click on — on the deep tier. Three things
change here. The catalog learns a frontier tier (Claude Fable 5.1, twice
the Opus price, thinking always on, effort low..max) and the generator
alone runs on it: one call a week where imagination is the product. The
provider survives that model's safety refusal by re-running once on
Opus. And the generator reads the evidence ledger — what each rule has
proven, in paper and live — and can arm its own proposals in RESEARCH
stage when the operator allows it: graded by the scanner, traded by no
bot, still rejectable.

Run with:  python manage.py test tests.test_frontier_imagination
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase


class TheCatalogTests(SimpleTestCase):

    def test_fable_is_known_priced_and_frontier(self):
        from ai_agents.catalog import MODELS, known_model, pricing_for
        self.assertTrue(known_model("claude-fable-5-1"))
        m = MODELS["claude-fable-5-1"]
        self.assertEqual(m["tier_hint"], "frontier")
        self.assertEqual(pricing_for("claude-fable-5-1"),
                         {"input": 10.0, "output": 50.0})
        self.assertTrue(m["thinking"])
        self.assertTrue(m["effort"])

    def test_the_frontier_tier_resolves_to_fable_by_default(self):
        from ai_agents.catalog import (TIER_DEFAULTS, TIER_EFFORT_DEFAULTS,
                                       TIERS, resolve_tier)
        self.assertIn("frontier", TIERS)
        self.assertEqual(TIER_DEFAULTS["frontier"], "claude-fable-5-1")
        self.assertEqual(TIER_EFFORT_DEFAULTS["frontier"], "high")
        self.assertEqual(resolve_tier("frontier"), "claude-fable-5-1")

    def test_only_the_generator_lives_on_the_frontier(self):
        from ai_agents.tasks import MondayPlanAgent
        from brain.strategy_generator import StrategyGeneratorAgent
        self.assertEqual(StrategyGeneratorAgent.default_tier, "frontier")
        self.assertEqual(MondayPlanAgent.default_tier, "balanced")

    def test_the_frontier_shares_the_deep_reserve(self):
        from ai_agents import spend
        with patch.object(spend, "daily_budget", return_value=15.0), \
                patch.object(spend, "spent_today",
                             return_value=15.0 * spend.DEEP_TIER_SHARE + 0.01):
            allowed, reason = spend.can_spend(tier="frontier",
                                              estimated_usd=0.01)
        self.assertFalse(allowed)
        self.assertIn("reserve", reason)


def _response(text="", stop_reason="end_turn", category=None):
    block = SimpleNamespace(type="text", text=text)
    details = SimpleNamespace(category=category) if category else None
    return SimpleNamespace(
        content=[block] if text else [],
        stop_reason=stop_reason, stop_details=details,
        usage=SimpleNamespace(input_tokens=100, output_tokens=20),
        model="x", id="msg")


class _Stream:
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.response


class TheProviderSurvivesARefusalTests(TestCase):

    def _provider(self, answers):
        """`answers` maps model id -> response the fake stream returns."""
        from ai_agents.providers.claude_provider import ClaudeProvider
        provider = ClaudeProvider()
        client = MagicMock()
        calls = []

        def _stream(**kw):
            calls.append(kw)
            return _Stream(answers[kw["model"]])

        client.messages.stream.side_effect = _stream
        provider._get_client = lambda: client
        return provider, calls

    def test_a_declined_request_re_runs_once_on_opus(self):
        provider, calls = self._provider({
            "claude-fable-5-1": _response(stop_reason="refusal",
                                          category="frontier_llm"),
            "claude-opus-5": _response(text='{"ok": true}')})
        text, usage = provider.complete(system_prompt="s", user_message="u",
                                        model="claude-fable-5-1",
                                        agent_name="test")
        self.assertEqual(text, '{"ok": true}')
        self.assertEqual([c["model"] for c in calls],
                         ["claude-fable-5-1", "claude-opus-5"])

    def test_a_decline_on_the_fallback_is_raised_not_chained(self):
        """The provider already raised on a refusal before the fallback
        existed; a decline ON the fallback keeps that behaviour and never
        re-runs a third time."""
        provider, calls = self._provider({
            "claude-opus-5": _response(stop_reason="refusal")})
        with self.assertRaises(RuntimeError):
            provider.complete(system_prompt="s", user_message="u",
                              model="claude-opus-5", agent_name="test")
        self.assertEqual(len(calls), 1)

    def test_an_answer_never_triggers_the_fallback(self):
        provider, calls = self._provider({
            "claude-fable-5-1": _response(text="fine")})
        provider.complete(system_prompt="s", user_message="u",
                          model="claude-fable-5-1", agent_name="test")
        self.assertEqual(len(calls), 1)


def _stub_generator(parsed):
    import json
    raw = json.dumps(parsed)
    usage = {"input_tokens": 10000, "output_tokens": 2000, "cost_usd": 0.5}

    def patched_init(self, *a, **kw):
        self.agent_name = "strategy_generator"
        self.provider_name = "stub"
        self.model = "claude-stub"
        self.provider = MagicMock()
        self.provider.complete = MagicMock(return_value=(raw, usage))
    return patch("brain.strategy_generator.StrategyGeneratorAgent.__init__",
                 patched_init)


def _proposal(slug="ledger_child"):
    return {
        "name_slug": slug, "rationale_md": "cites evidence_ledger",
        "inspiration": "ledger", "direction": "bullish",
        "asset_classes": ["stock"],
        "conditions": [{"kind": "price_pattern",
                        "params": {"pattern": "above_ma"}, "weight": 1.0}],
        "min_match_score": 0.6, "suggested_horizon_days": 5,
        "confidence": 0.6,
    }


def _component(key, enabled):
    from core.platform_control import PlatformComponent
    for k in ("platform_master", key):
        row, _ = PlatformComponent.objects.get_or_create(
            key=k, defaults={"name": k, "description": k, "category": "agent"})
        row.is_enabled = enabled if k == key else True
        row.save()


class TheGeneratorTests(TestCase):

    def test_the_snapshot_carries_the_evidence_ledger(self):
        from brain.strategy_generator import (StrategyGeneratorAgent,
                                              _build_generation_snapshot)
        snap = _build_generation_snapshot()
        self.assertIn("evidence_ledger", snap)
        # The prompt names the ledger; the agent is built without its
        # provider so no client is constructed.
        prompt = StrategyGeneratorAgent.get_system_prompt(
            StrategyGeneratorAgent.__new__(StrategyGeneratorAgent))
        self.assertIn("evidence_ledger", prompt)
        self.assertIn("regret_r", prompt)

    def test_the_registry_knows_the_switch(self):
        from core.platform_control import DEFAULT_COMPONENTS
        entry = next(c for c in DEFAULT_COMPONENTS
                     if c["key"] == "generator_auto_research")
        self.assertIn("RESEARCH", entry["description"])
        self.assertIn("no bot trades", entry["description"])

    def test_off_means_proposals_wait_for_a_click(self):
        from brain.generator_models import GeneratedSetupProposal
        from brain.strategy_generator import generate_strategies_now
        _component("generator_auto_research", False)
        with _stub_generator({"proposals": [_proposal()]}):
            out = generate_strategies_now()
        self.assertEqual(out["n_persisted"], 1)
        self.assertEqual(out["n_armed_research"], 0)
        row = GeneratedSetupProposal.objects.get()
        self.assertEqual(row.status, GeneratedSetupProposal.STATUS_PENDING)
        self.assertFalse(row.setup.is_active)

    def test_on_means_armed_in_research_graded_never_traded(self):
        from brain.generator_models import GeneratedSetupProposal
        from brain.strategy_generator import generate_strategies_now
        _component("generator_auto_research", True)
        with _stub_generator({"proposals": [_proposal("armed_child")]}):
            out = generate_strategies_now()
        self.assertEqual(out["n_armed_research"], 1)
        row = GeneratedSetupProposal.objects.get()
        self.assertEqual(row.status, GeneratedSetupProposal.STATUS_APPROVED)
        self.assertEqual(row.reviewed_by, "auto:research")
        self.assertTrue(row.setup.is_active)
        # The stage gate is what keeps every bot off it.
        self.assertEqual(row.rule_control.promotion_stage, "research")

    def test_the_weekly_task_budgets_on_the_frontier_tier(self):
        from pathlib import Path

        from django.conf import settings
        src = (Path(settings.BASE_DIR) / "brain" / "tasks.py"
               ).read_text(encoding="utf-8")
        self.assertIn('@spend_guard(tier="frontier", estimated_usd=1.0)\n'
                      'def run_strategy_generator', src)
