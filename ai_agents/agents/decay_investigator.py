"""Phase-3 DecayInvestigatorAgent.

When `signals.performance.decay_flag` reports a rule as decaying, this agent
hypothesizes WHY — pulling the recent failures and the baseline winners into
context so Claude can spot the pattern.

Persists a `DecayInvestigation` row.
"""
import json
import logging
from datetime import timedelta

from django.utils import timezone

from ai_agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)


def _signal_brief(sig) -> str:
    return (
        f"  - {sig.created_at.date()} {sig.instrument.symbol} {sig.direction[:1].upper()} "
        f"score={sig.score:.2f} → {sig.outcome} "
        f"(R={sig.realized_r if sig.realized_r is not None else '?'})"
    )


class DecayInvestigatorAgent(BaseAgent):
    agent_name = "decay_investigator"
    default_tier = "balanced"

    def get_system_prompt(self) -> str:
        return """You are a decay investigator for Sauron Vision.

A trading rule that previously worked has stopped working. You are given
its baseline winners and its recent failures. Hypothesize the cause.

Return JSON ONLY:

{
  "hypothesis": string,                // 2–4 sentences, the most likely cause
  "contributing_factors": [string, ...], // 2–5 specific bullets
  "recommended_action":  string         // one of:
                                        //   "pause_rule"   — clear regime shift
                                        //   "reduce_size"  — partial loss of edge
                                        //   "monitor"      — too early to act
                                        //   "investigate_data" — data quality suspected
                                        //   "retune_params" — parameters drifted
}
"""

    def build_context(self, **kwargs) -> str:
        try:
            from brain.context import context_for_prompt
            brain_block = context_for_prompt()
        except Exception:
            brain_block = ""
        prefix = (brain_block + "\n\n") if brain_block else ""
        return prefix + f"""Rule decaying: {kwargs.get('rule_name', '?')}

Recent expectancy:   {kwargs.get('recent_expectancy', '?')}R  (n={kwargs.get('recent_n', 0)})
Baseline expectancy: {kwargs.get('baseline_expectancy', '?')}R  (n={kwargs.get('baseline_n', 0)})

Baseline winners (sample):
{kwargs.get('baseline_briefs', '(none)')}

Recent failures:
{kwargs.get('recent_briefs', '(none)')}
"""

    def parse_response(self, raw_response: str) -> dict:
        try:
            cleaned = raw_response.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
            data = json.loads(cleaned)
            valid_actions = {"pause_rule", "reduce_size", "monitor",
                             "investigate_data", "retune_params"}
            action = data.get("recommended_action", "monitor")
            if action not in valid_actions:
                action = "monitor"
            return {
                "hypothesis": str(data.get("hypothesis", ""))[:1500],
                "contributing_factors": [str(x)[:200] for x in data.get("contributing_factors", [])][:6],
                "recommended_action": action,
            }
        except (json.JSONDecodeError, ValueError, TypeError):
            logger.warning("DecayInvestigatorAgent parse failed: %s", raw_response[:200])
            return {
                "hypothesis": raw_response[:1000],
                "contributing_factors": [],
                "recommended_action": "monitor",
                "parse_error": True,
            }


def investigate_decaying_rule(rule_name: str, *, recent_days: int = 14,
                              baseline_days: int = 90, baseline_sample: int = 8,
                              recent_sample: int = 8):
    """Run the decay investigator for one rule and persist a DecayInvestigation.

    Returns the persisted DecayInvestigation, or None if the rule isn't actually
    decaying (per Phase-1's decay_flag) or the agent fails.
    """
    from signals.models import Signal
    from signals.performance import decay_flag
    from ai_agents.models import AgentTask, DecayInvestigation

    flag = decay_flag(rule_name, recent_days=recent_days, baseline_days=baseline_days)
    if not flag["is_decaying"]:
        return None

    now = timezone.now()
    base_qs = (
        Signal.objects
        .filter(rule_name=rule_name, is_active=False,
                expired_at__gte=now - timedelta(days=baseline_days),
                expired_at__lt=now - timedelta(days=recent_days))
        .exclude(outcome="").select_related("instrument").order_by("-realized_r")
    )
    recent_qs = (
        Signal.objects
        .filter(rule_name=rule_name, is_active=False,
                expired_at__gte=now - timedelta(days=recent_days))
        .exclude(outcome="").select_related("instrument").order_by("realized_r")
    )

    baseline_briefs = "\n".join(_signal_brief(s) for s in base_qs[:baseline_sample]) or "(none)"
    recent_briefs = "\n".join(_signal_brief(s) for s in recent_qs[:recent_sample]) or "(none)"

    agent = DecayInvestigatorAgent()
    try:
        result = agent.run(
            rule_name=rule_name,
            recent_expectancy=flag["recent_expectancy"],
            baseline_expectancy=flag["baseline_expectancy"],
            recent_n=flag["recent_n"],
            baseline_n=flag["baseline_n"],
            baseline_briefs=baseline_briefs,
            recent_briefs=recent_briefs,
        )
    except Exception as e:
        logger.warning("DecayInvestigatorAgent.run failed for %s: %s", rule_name, e)
        return None

    last_task = AgentTask.objects.filter(agent="decay_investigator").order_by("-created_at").first()
    investigation = DecayInvestigation.objects.create(
        rule_name=rule_name,
        recent_expectancy=flag["recent_expectancy"],
        baseline_expectancy=flag["baseline_expectancy"],
        recent_n=flag["recent_n"],
        baseline_n=flag["baseline_n"],
        hypothesis=result.get("hypothesis", ""),
        contributing_factors=result.get("contributing_factors", []),
        recommended_action=result.get("recommended_action", "monitor"),
        structured_output=result,
        agent_task=last_task,
    )

    # Phase-39 — post the investigator's call as a falsifiable hypothesis.
    # Different actions imply different predicted trajectories:
    #   pause_rule / reduce_size  → predicts continued decay (avg_r < 0)
    #   monitor / retune_params   → predicts recovery (avg_r ≥ 0)
    try:
        from brain.hypotheses import post_hypothesis
        action = result.get("recommended_action", "monitor")
        if action in ("pause_rule", "reduce_size"):
            post_hypothesis(
                claim_text=f"'{rule_name}' continues decaying (avg_r < 0 over 14d)",
                source_agent="decay_investigator",
                claim_payload={"rule_name": rule_name,
                                "recommended_action": action,
                                "investigation_id": investigation.id},
                resolution_criteria={
                    "kind": "rule_avg_r", "rule_name": rule_name,
                    "comparator": "<", "threshold": 0.0, "window_days": 14,
                },
                confidence=0.65, horizon_hours=14 * 24,
            )
        elif action in ("monitor", "retune_params"):
            post_hypothesis(
                claim_text=f"'{rule_name}' recovers (avg_r ≥ 0 over 14d)",
                source_agent="decay_investigator",
                claim_payload={"rule_name": rule_name,
                                "recommended_action": action,
                                "investigation_id": investigation.id},
                resolution_criteria={
                    "kind": "rule_avg_r", "rule_name": rule_name,
                    "comparator": ">=", "threshold": 0.0, "window_days": 14,
                },
                confidence=0.5, horizon_hours=14 * 24,
            )
    except Exception:
        pass

    return investigation
