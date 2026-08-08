"""Phase-3 SignalJournalAgent.

Auto-generates a journal entry when a Signal closes (hit_target / stopped_out /
expired / manual_close). Persists a TradeJournalEntry. Triggered by Phase-1's
`evaluate_signal_outcome` on close, gated by |realized_r| >= threshold so we
don't spend tokens on uninteresting outcomes.
"""
import json
import logging
from decimal import Decimal

from ai_agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)


# Don't journal trades smaller than this in absolute realized R — saves tokens.
DEFAULT_MIN_ABS_R = 0.5


class SignalJournalAgent(BaseAgent):
    agent_name = "signal_journal"
    default_tier = "fast"

    def get_system_prompt(self) -> str:
        return """You are the Sauron Vision signal-journal analyst.

A trading signal has just closed. Generate a tight journal entry capturing
process quality, not just P&L. Good process can lose; bad process can win —
the entry should grade *the decision*, not *the outcome*.

Return JSON ONLY:

{
  "summary": string,                  // 1–3 sentences
  "key_takeaway": string,             // single most important lesson
  "grade": "A"|"B"|"C"|"D"|"F"|"N/A", // process quality, not P&L
  "lessons": [string, ...],           // 1–4 bullets
  "tags": [string, ...],              // e.g. "momentum", "reversal", "decay-flagged"
  "emotional_state": "disciplined"|"fomo"|"fearful"|"greedy"|"neutral"
}
"""

    def build_context(self, **kwargs) -> str:
        return f"""Closed signal:

  Symbol:        {kwargs.get('symbol', '?')}
  Rule:          {kwargs.get('rule_name', '?')}
  Direction:     {kwargs.get('direction', '?')}
  Signal type:   {kwargs.get('signal_type', '?')}
  Urgency:       {kwargs.get('urgency', '?')}
  Title:         {kwargs.get('title', '')}

  Entry (suggested):  {kwargs.get('entry', '?')}
  Stop  (suggested):  {kwargs.get('stop', '?')}
  Target (suggested): {kwargs.get('target', '?')}
  Outcome:            {kwargs.get('outcome', '?')}
  Realized R:         {kwargs.get('realized_r', '?')}
  Time to outcome:    {kwargs.get('duration_h', '?')} hours
  MFE / MAE:          {kwargs.get('mfe', '?')} / {kwargs.get('mae', '?')}

Score at signal:      {kwargs.get('score', '?')}
Description:
{kwargs.get('description', '')}
"""

    def parse_response(self, raw_response: str) -> dict:
        try:
            cleaned = raw_response.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
            data = json.loads(cleaned)
            grade = data.get("grade", "N/A")
            if grade not in ("A", "B", "C", "D", "F", "N/A"):
                grade = "N/A"
            return {
                "summary": str(data.get("summary", ""))[:1000],
                "key_takeaway": str(data.get("key_takeaway", ""))[:400],
                "grade": grade,
                "lessons": [str(x)[:200] for x in data.get("lessons", [])][:8],
                "tags": [str(x)[:40] for x in data.get("tags", [])][:8],
                "emotional_state": str(data.get("emotional_state", "neutral"))[:20],
            }
        except (json.JSONDecodeError, ValueError, TypeError):
            logger.warning("SignalJournalAgent parse failed: %s", raw_response[:200])
            return {
                "summary": raw_response[:500], "key_takeaway": "",
                "grade": "N/A", "lessons": [], "tags": [],
                "emotional_state": "neutral", "parse_error": True,
            }


def journal_closed_signal(signal, *, min_abs_r: float = DEFAULT_MIN_ABS_R, force: bool = False):
    """Generate a TradeJournalEntry for a closed signal.

    Returns the created entry, or None if skipped (signal still active, no R,
    below threshold, or agent failed). `force=True` bypasses the |R| threshold.
    """
    from ai_agents.models import AgentTask, TradeJournalEntry

    if signal.is_active:
        return None
    if signal.realized_r is None:
        return None
    if not force and abs(float(signal.realized_r)) < min_abs_r:
        return None

    duration_h = (signal.time_to_outcome_seconds or 0) / 3600.0
    agent = SignalJournalAgent()
    try:
        result = agent.run(
            symbol=signal.instrument.symbol,
            rule_name=signal.rule_name,
            direction=signal.direction,
            signal_type=signal.signal_type,
            urgency=signal.urgency,
            title=signal.title,
            description=signal.description,
            score=signal.score,
            entry=str(signal.suggested_entry) if signal.suggested_entry else "?",
            stop=str(signal.suggested_stop) if signal.suggested_stop else "?",
            target=str(signal.suggested_target) if signal.suggested_target else "?",
            outcome=signal.outcome,
            realized_r=signal.realized_r,
            duration_h=round(duration_h, 2),
            mfe=str(signal.mfe) if signal.mfe is not None else "?",
            mae=str(signal.mae) if signal.mae is not None else "?",
        )
    except Exception as e:
        logger.warning("SignalJournalAgent.run failed for signal %s: %s", signal.pk, e)
        return None

    last_task = AgentTask.objects.filter(agent="signal_journal").order_by("-created_at").first()
    return TradeJournalEntry.objects.create(
        signal=signal,
        grade=result.get("grade", "N/A"),
        summary=result.get("summary", ""),
        key_takeaway=result.get("key_takeaway", ""),
        lessons=result.get("lessons", []),
        tags=result.get("tags", []),
        emotional_state=result.get("emotional_state", "neutral"),
        structured_output=result,
        agent_task=last_task,
    )
