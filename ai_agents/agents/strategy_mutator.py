"""Phase-32 — AI-driven strategy mutation generator.

Phase 9 mutates rule parameters by drawing Gaussian noise around current
values clamped to schema bounds. That's a fine baseline but it's blind: it
can't reason about *why* a parameter combination might work.

This agent asks Claude (or any configured provider) for a mutation given:
  - the rule's parameter schema (bounds, types, semantic names)
  - the rule's recent track record
  - the rule's current parameters (the parent)
  - parent expectancy + last-30d win rate

The agent returns a JSON proposal: {parameters, rationale, expected_effect}.
The proposal is then validated against the schema (clamped to bounds, type-
coerced) before being returned to the caller — same shape as the existing
heuristic `generate_mutant`.

Defaults to OFF — enabled per-rule via `RuleControl.parameters['use_ai_mutator']
= True`. When AI fails (network, API key missing, malformed JSON), falls back
to the heuristic Gaussian mutator so the evolution loop never blocks.
"""
import json
import logging

from ai_agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)


class StrategyMutatorAgent(BaseAgent):
    agent_name = "strategy_mutator"
    default_tier = "balanced"

    def get_system_prompt(self) -> str:
        return (
            "You are the Strategy Mutator for Sauron Vision, an autonomous "
            "trading platform. Given a rule's parameter schema, current values, "
            "and recent performance, you propose ONE mutation that's likely to "
            "improve performance.\n\n"
            "Rules:\n"
            "1. Mutate 1-3 parameters; don't propose changes to all of them.\n"
            "2. Stay within each parameter's [min, max] bounds.\n"
            "3. Coerce types (ints stay ints, floats stay floats).\n"
            "4. If the rule is winning (avg_r>0, win_rate>0.55) propose a small "
            "tweak (5-10% deltas) — don't break what works.\n"
            "5. If the rule is losing or neutral, propose a more aggressive "
            "change (15-30% deltas) — explore the space.\n"
            "6. Provide a one-sentence rationale tying the change to the trade "
            "outcome data — generic reasoning is wasted output.\n\n"
            "Respond ONLY with valid JSON in this shape:\n"
            "{\n"
            '  "parameters": {<param_name>: <new_value>, ...},\n'
            '  "rationale": "one sentence",\n'
            '  "expected_effect": "win_rate_up | avg_r_up | drawdown_down | exploration"\n'
            "}\n\n"
            "Output the full parameters dict with both mutated and unchanged values "
            "so the platform can use the response directly."
        )

    def build_context(self, **kwargs) -> str:
        rule_name = kwargs.get("rule_name", "unknown")
        schema = kwargs.get("schema", {})
        current_params = kwargs.get("current_params", {})
        track_record = kwargs.get("track_record", {})

        try:
            from brain.context import context_for_prompt
            brain_block = context_for_prompt()
        except Exception:
            brain_block = ""
        prefix = (brain_block + "\n\n") if brain_block else ""

        return prefix + (
            f"Rule: {rule_name}\n\n"
            f"Parameter schema (bounds + types):\n{json.dumps(schema, indent=2, default=str)}\n\n"
            f"Current parameters (parent):\n{json.dumps(current_params, indent=2, default=str)}\n\n"
            f"Recent performance (last 30d, lower is worse):\n"
            f"  trades:     {track_record.get('n', 0)}\n"
            f"  win_rate:   {track_record.get('win_rate', 0)}\n"
            f"  avg_r:      {track_record.get('avg_r', 0)}\n"
            f"  expectancy: {track_record.get('expectancy', 0)}\n"
            f"  max_dd_r:   {track_record.get('max_dd_r', 0)}\n\n"
            "If the Sauron's Mind context above lists this rule as "
            "'pause_recommended' or 'watch', factor that in: a regime-driven "
            "decay calls for a SMALL conservative tweak (or no mutation), not "
            "an aggressive rewrite of parameters that worked in the prior regime.\n\n"
            "Propose one mutation."
        )

    def parse_response(self, raw_response: str) -> dict:
        """Extract a JSON object from the response, tolerant of fenced blocks."""
        text = (raw_response or "").strip()
        # Strip ```json ... ``` fences if present.
        if text.startswith("```"):
            lines = text.splitlines()
            if lines:
                lines = lines[1:]  # drop ``` opener
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                text = "\n".join(lines)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(f"AI returned non-JSON: {e}: {text[:200]}")
        if not isinstance(data, dict):
            raise ValueError(f"AI returned non-dict: {type(data).__name__}")
        if "parameters" not in data:
            raise ValueError("AI response missing 'parameters' key")
        return data


# ── Public entry point used by Phase 9 evolution ─────────────────────────

def generate_ai_mutant(rule_name: str, *, n_params_to_mutate=None,
                        rng=None) -> dict:
    """Drop-in replacement for `signals.evolution.generate_mutant`.

    Falls back to the heuristic mutator when:
      - the AI provider is unavailable / unconfigured
      - the AI response can't be parsed as valid JSON
      - the AI returns parameters outside schema bounds
      - any unhandled exception
    """
    from signals.evolution import (
        generate_mutant, current_params, has_schema, SCHEMA_REGISTRY, _coerce,
    )
    from bot_program.bot_grading import bot_performance_summary

    if not has_schema(rule_name):
        # No schema — nothing to mutate.
        raise ValueError(f"No schema registered for rule '{rule_name}'")

    schema = SCHEMA_REGISTRY[rule_name]
    parent = current_params(rule_name)

    # Pull recent track record for context (best-effort).
    try:
        rows = bot_performance_summary(rule_name=rule_name, days=30, min_n=1)
        track_record = rows[0] if rows else {}
    except Exception:
        track_record = {}

    try:
        agent = StrategyMutatorAgent()
        result = agent.run(
            rule_name=rule_name,
            schema=schema,
            current_params=parent,
            track_record=track_record,
        )
        ai_params = result.get("parameters") or {}
        if not isinstance(ai_params, dict) or not ai_params:
            raise ValueError("AI parameters missing or empty")

        # Validate + coerce against schema bounds. Unknown keys dropped;
        # missing keys filled from parent.
        out = dict(parent)
        for name, spec in schema.items():
            if name in ai_params:
                try:
                    out[name] = _coerce(ai_params[name], spec)
                except Exception:
                    out[name] = parent.get(name, spec.get("default"))
        try:
            from brain.observations import record_observation
            record_observation(
                kind="mutation_proposed",
                payload={"rule_name": rule_name, "parent": parent,
                          "mutated": out, "track_record": track_record,
                          "source": "ai_mutator"},
                source="strategy_mutator",
            )
        except Exception:
            pass

        # Phase-39 — post a falsifiable hypothesis: the mutated rule will
        # have non-negative avg_r over the next 14 days. The market's
        # existing rule_avg_r resolver grades it; trust score adjusts the
        # mutator's weight in downstream context-injection automatically.
        try:
            from brain.hypotheses import post_hypothesis
            post_hypothesis(
                claim_text=f"mutated '{rule_name}' will produce avg_r ≥ 0 over 14d",
                source_agent="strategy_mutator",
                claim_payload={"rule_name": rule_name,
                                "parent_params": parent,
                                "mutated_params": out},
                resolution_criteria={
                    "kind": "rule_avg_r", "rule_name": rule_name,
                    "comparator": ">=", "threshold": 0.0, "window_days": 14,
                },
                confidence=0.55,
                horizon_hours=14 * 24,
            )
        except Exception:
            pass

        return out

    except Exception as e:
        logger.warning(
            "AI mutator failed for %s (%s); falling back to heuristic.",
            rule_name, e,
        )
        return generate_mutant(rule_name, n_params_to_mutate=n_params_to_mutate,
                                rng=rng)


def use_ai_mutator(rule_name: str) -> bool:
    """Per-rule opt-in flag from RuleControl.parameters['use_ai_mutator']."""
    try:
        from signals.models_control import RuleControl
        rc = RuleControl.objects.filter(rule_name=rule_name).first()
        if rc is None:
            return False
        return bool((rc.parameters or {}).get("use_ai_mutator", False))
    except Exception:
        return False
