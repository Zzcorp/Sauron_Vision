"""Phase-32 AI mutation generator tests:
  - parse_response handles bare JSON + ```json fenced blocks
  - parse_response rejects non-JSON / non-dict / missing-parameters payloads
  - generate_ai_mutant clamps AI-returned values to schema bounds
  - generate_ai_mutant falls back to heuristic on AI failure
  - use_ai_mutator reads RuleControl.parameters opt-in flag
  - propose_evolution uses AI mutator for rules opted in (one slot)

Run with:  python manage.py test tests.test_phase32_ai_mutator
"""
from unittest.mock import MagicMock, patch

from django.test import TestCase


def _register_test_schema():
    """A minimal schema registered for the duration of one test."""
    from signals.evolution import register_schema
    register_schema("test_rule", {
        "ma_period":    {"type": "int", "min": 5, "max": 100, "default": 20, "step": 1},
        "stop_pct":     {"type": "float", "min": 0.5, "max": 5.0, "default": 2.0, "step": 0.1},
        "target_rr":    {"type": "float", "min": 1.0, "max": 5.0, "default": 2.0, "step": 0.1},
    })


# ── parse_response ────────────────────────────────────────────────────────

class ParseResponseTests(TestCase):
    def test_bare_json(self):
        from ai_agents.agents.strategy_mutator import StrategyMutatorAgent
        a = StrategyMutatorAgent.__new__(StrategyMutatorAgent)  # bypass __init__
        out = a.parse_response('{"parameters": {"x": 1}, "rationale": "r"}')
        self.assertEqual(out["parameters"], {"x": 1})

    def test_fenced_json(self):
        from ai_agents.agents.strategy_mutator import StrategyMutatorAgent
        a = StrategyMutatorAgent.__new__(StrategyMutatorAgent)
        text = '```json\n{"parameters": {"x": 2}, "rationale": "r"}\n```'
        out = a.parse_response(text)
        self.assertEqual(out["parameters"], {"x": 2})

    def test_non_json_raises(self):
        from ai_agents.agents.strategy_mutator import StrategyMutatorAgent
        a = StrategyMutatorAgent.__new__(StrategyMutatorAgent)
        with self.assertRaises(ValueError):
            a.parse_response("definitely not json")

    def test_missing_parameters_raises(self):
        from ai_agents.agents.strategy_mutator import StrategyMutatorAgent
        a = StrategyMutatorAgent.__new__(StrategyMutatorAgent)
        with self.assertRaises(ValueError):
            a.parse_response('{"rationale": "no params here"}')


# ── generate_ai_mutant ───────────────────────────────────────────────────

class GenerateAIMutantTests(TestCase):
    def setUp(self):
        _register_test_schema()

    def test_clamps_oob_values_to_bounds(self):
        """If AI returns ma_period=999 (way over max=100), it gets clamped."""
        from ai_agents.agents.strategy_mutator import generate_ai_mutant
        with patch("ai_agents.agents.strategy_mutator.StrategyMutatorAgent") as M:
            agent = M.return_value
            agent.run = MagicMock(return_value={
                "parameters": {"ma_period": 999, "stop_pct": 1.5, "target_rr": 2.0},
                "rationale": "mock",
            })
            mutant = generate_ai_mutant("test_rule")
        # ma_period clamped to 100; floats untouched.
        self.assertEqual(mutant["ma_period"], 100)
        self.assertEqual(mutant["stop_pct"], 1.5)

    def test_int_coercion(self):
        from ai_agents.agents.strategy_mutator import generate_ai_mutant
        with patch("ai_agents.agents.strategy_mutator.StrategyMutatorAgent") as M:
            M.return_value.run = MagicMock(return_value={
                "parameters": {"ma_period": 30.7},  # float for int param
                "rationale": "mock",
            })
            mutant = generate_ai_mutant("test_rule")
        self.assertIsInstance(mutant["ma_period"], int)
        # _coerce rounds (30.7 → 31), not truncates.
        self.assertEqual(mutant["ma_period"], 31)

    def test_falls_back_to_heuristic_on_ai_failure(self):
        """When the agent raises, generate_ai_mutant calls generate_mutant."""
        from ai_agents.agents.strategy_mutator import generate_ai_mutant
        with patch("ai_agents.agents.strategy_mutator.StrategyMutatorAgent",
                    side_effect=RuntimeError("API down")), \
             patch("signals.evolution.generate_mutant",
                    return_value={"ma_period": 25, "stop_pct": 2.5, "target_rr": 2.5}) as h:
            mutant = generate_ai_mutant("test_rule")
        h.assert_called_once()
        self.assertEqual(mutant["ma_period"], 25)

    def test_falls_back_when_response_invalid(self):
        from ai_agents.agents.strategy_mutator import generate_ai_mutant
        with patch("ai_agents.agents.strategy_mutator.StrategyMutatorAgent") as M:
            M.return_value.run = MagicMock(return_value={"no_parameters_key": True})
            with patch("signals.evolution.generate_mutant",
                        return_value={"ma_period": 22, "stop_pct": 1.8, "target_rr": 2.0}) as h:
                mutant = generate_ai_mutant("test_rule")
        h.assert_called_once()
        self.assertEqual(mutant["ma_period"], 22)


# ── use_ai_mutator opt-in flag ───────────────────────────────────────────

class UseAIMutatorFlagTests(TestCase):
    def test_no_rule_returns_false(self):
        from ai_agents.agents.strategy_mutator import use_ai_mutator
        self.assertFalse(use_ai_mutator("nonexistent_rule"))

    def test_flag_off_returns_false(self):
        from ai_agents.agents.strategy_mutator import use_ai_mutator
        from signals.models_control import RuleControl
        RuleControl.objects.create(rule_name="off_rule", parameters={})
        self.assertFalse(use_ai_mutator("off_rule"))

    def test_flag_on_returns_true(self):
        from ai_agents.agents.strategy_mutator import use_ai_mutator
        from signals.models_control import RuleControl
        RuleControl.objects.create(
            rule_name="on_rule",
            parameters={"use_ai_mutator": True},
        )
        self.assertTrue(use_ai_mutator("on_rule"))


# ── propose_evolution AI integration ─────────────────────────────────────

class ProposeEvolutionAIIntegrationTests(TestCase):
    def test_ai_mutator_used_when_flag_on(self):
        """propose_evolution should call generate_ai_mutant for the first
        candidate when the rule opts in."""
        _register_test_schema()
        from signals.models_control import RuleControl
        from signals.evolution import propose_evolution
        RuleControl.objects.create(
            rule_name="test_rule",
            parameters={"use_ai_mutator": True},
        )

        with patch("ai_agents.agents.strategy_mutator.generate_ai_mutant",
                    return_value={"ma_period": 35, "stop_pct": 1.5, "target_rr": 2.5}) as ai_mock, \
             patch("signals.evolution.score_mutant",
                    return_value={"score": 0.5, "method": "heuristic", "details": {}}):
            propose_evolution("test_rule", n_mutants=3, top_k=1, seed=42)
        # generate_ai_mutant called for the first iteration.
        self.assertGreaterEqual(ai_mock.call_count, 1)

    def test_ai_mutator_skipped_when_flag_off(self):
        _register_test_schema()
        from signals.evolution import propose_evolution
        # No RuleControl row → use_ai_mutator returns False.
        with patch("ai_agents.agents.strategy_mutator.generate_ai_mutant") as ai_mock, \
             patch("signals.evolution.score_mutant",
                    return_value={"score": 0.5, "method": "heuristic", "details": {}}):
            propose_evolution("test_rule", n_mutants=3, top_k=1, seed=42)
        ai_mock.assert_not_called()
