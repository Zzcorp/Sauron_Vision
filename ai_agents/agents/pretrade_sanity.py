"""Phase-3 PreTradeSanityAgent.

Reviews a proposed trade before it opens. Looks for contradictions between the
trade thesis and:
  - the current macro regime
  - recent news sentiment for the symbol
  - the rule's recent realized performance (decay-flagged?)

Returns a verdict the risk gate can act on:

    {
      "verdict":  "go" | "scale_down" | "abort",
      "scale":    0..1,
      "concerns": [str, ...],
      "rationale": "...",
    }

Cheap-fast tier by default — this can be in the trade-decision hot path, so
latency matters.
"""
import json
import logging

from ai_agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)


class PreTradeSanityAgent(BaseAgent):
    agent_name = "pretrade_sanity"
    default_tier = "fast"

    def get_system_prompt(self) -> str:
        return """You are a pre-trade sanity reviewer for Sauron Vision.

A trade is about to open. Your job is to check whether the proposed direction
contradicts the current macro regime, recent news sentiment, or the recent
realized performance of the signal rule.

Return JSON ONLY (no prose). Schema:

{
  "verdict": "go" | "scale_down" | "abort",
  "scale": 0.0 to 1.0,         // size multiplier (1.0 = full, 0.5 = half, 0.0 = abort)
  "concerns": [string, ...],   // brief bullets — leave empty if none
  "rationale": string          // one-sentence summary of the call
}

Bias toward "go" when concerns are weak. Use "scale_down" (with scale ≈ 0.5)
for one moderate contradiction. Reserve "abort" for direct, severe macro/news
contradictions, or when the rule is decisively decaying.
"""

    def build_context(self, **kwargs) -> str:
        try:
            from brain.context import context_for_prompt
            brain_block = context_for_prompt()
        except Exception:
            brain_block = ""
        prefix = (brain_block + "\n\n") if brain_block else ""
        return prefix + f"""Proposed trade:

  Symbol:    {kwargs.get('symbol', '?')}
  Direction: {kwargs.get('direction', '?')}
  Entry:     {kwargs.get('entry', '?')}
  Stop:      {kwargs.get('stop', '?')}
  Target:    {kwargs.get('target', '?')}
  Rule:      {kwargs.get('rule_name', '?')}

Current macro regime:
{kwargs.get('regime_summary', '(unknown)')}

Recent news sentiment ({kwargs.get('symbol', '?')}, last 7d):
{kwargs.get('news_summary', '(none)')}

Rule recent performance (Phase-1 self-grading):
{kwargs.get('rule_perf_summary', '(no history)')}
"""

    def parse_response(self, raw_response: str) -> dict:
        try:
            cleaned = raw_response.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
            data = json.loads(cleaned)
            verdict = data.get("verdict", "go")
            scale = float(data.get("scale", 1.0))
            scale = max(0.0, min(1.0, scale))
            return {
                "verdict": verdict if verdict in ("go", "scale_down", "abort") else "go",
                "scale": round(scale, 4),
                "concerns": list(data.get("concerns", []))[:6],
                "rationale": str(data.get("rationale", ""))[:400],
            }
        except (json.JSONDecodeError, ValueError, TypeError):
            logger.warning("PreTradeSanityAgent parse failed: %s", raw_response[:200])
            # Fail CLOSED: a sanity reviewer that produced unparseable output has
            # given us no assurance the trade is sound. Abort + scale 0.0 so the
            # risk gate sizes the trade to zero rather than waving it through.
            # (This path only affects callers that explicitly opted into the AI
            # check via use_ai_check=True; it is off by default.)
            return {
                "verdict": "abort", "scale": 0.0,
                "concerns": ["agent parse failed — failing closed (abort)"],
                "rationale": raw_response[:200],
            }


def check_proposed_trade(*, symbol, direction, entry, stop, target,
                        rule_name=None, regime_summary="", news_summary="",
                        rule_perf_summary=""):
    """Convenience entrypoint. Returns the parsed verdict dict."""
    agent = PreTradeSanityAgent()
    return agent.run(
        symbol=symbol, direction=direction,
        entry=entry, stop=stop, target=target,
        rule_name=rule_name or "(unknown)",
        regime_summary=regime_summary,
        news_summary=news_summary,
        rule_perf_summary=rule_perf_summary,
    )
