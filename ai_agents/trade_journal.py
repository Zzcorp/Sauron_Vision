"""AI-generated trade journal — auto-generate journal entries for closed positions."""
import logging
from ai_agents.base_agent import BaseAgent
import json

logger = logging.getLogger(__name__)


class TradeJournalAgent(BaseAgent):
    agent_name = "trade_journal"
    default_tier = "fast"

    def get_system_prompt(self) -> str:
        return """You are a trading journal analyst for Sauron Vision.
For each closed trade, you generate a concise journal entry that captures:

1. SETUP: What was the trade thesis/signal that led to entry?
2. EXECUTION: How was the entry/exit? Was it according to plan?
3. OUTCOME: What was the P&L? Did it hit target or stop?
4. LESSONS: What can be learned? What to repeat or avoid?
5. GRADE: A-F grade for the trade quality (good process can still lose)

Keep entries concise but insightful. Focus on process quality, not just results.

Return JSON:
{
    "setup_description": "...",
    "execution_notes": "...",
    "outcome_summary": "...",
    "lessons": ["lesson1", "lesson2"],
    "grade": "A" to "F",
    "emotional_state": "disciplined" | "fomo" | "fearful" | "greedy" | "neutral",
    "tags": ["momentum", "reversal", "breakout", etc.],
    "key_takeaway": "one-sentence main lesson"
}

Respond ONLY with valid JSON."""

    def build_context(self, **kwargs) -> str:
        return f"""Closed trade to journal:

Symbol: {kwargs.get('symbol', 'Unknown')}
Direction: {kwargs.get('direction', 'Unknown')}
Entry Price: {kwargs.get('entry_price', 'Unknown')}
Exit Price: {kwargs.get('exit_price', 'Unknown')}
P&L: {kwargs.get('pnl', 'Unknown')} ({kwargs.get('pnl_pct', 'Unknown')}%)
Duration: {kwargs.get('duration', 'Unknown')}
Strategy: {kwargs.get('strategy', 'None')}
Signal that triggered: {kwargs.get('signal_info', 'None')}
Stop Loss: {kwargs.get('stop_loss', 'None')}
Take Profit: {kwargs.get('take_profit', 'None')}
Market conditions at entry: {kwargs.get('market_context', 'Unknown')}"""

    def parse_response(self, raw_response: str) -> dict:
        try:
            cleaned = raw_response.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1]
                cleaned = cleaned.rsplit("```", 1)[0]
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {"grade": "N/A", "key_takeaway": raw_response[:200], "parse_error": True}


def generate_journal_entry(position):
    """Generate a journal entry for a closed position."""
    if not position.closed_at:
        return None

    pnl = float(position.current_price - position.entry_price) * float(position.quantity)
    if position.direction.lower() in ('short',):
        pnl = -pnl
    pnl_pct = float((position.current_price - position.entry_price) / position.entry_price * 100)
    if position.direction.lower() in ('short',):
        pnl_pct = -pnl_pct

    duration = position.closed_at - position.opened_at

    signal_info = "None"
    if position.strategy and position.strategy.source_signals.exists():
        sig = position.strategy.source_signals.first()
        signal_info = f"{sig.title} (score: {sig.score})"

    agent = TradeJournalAgent()
    result = agent.run(
        symbol=position.instrument.symbol,
        direction=position.direction,
        entry_price=str(position.entry_price),
        exit_price=str(position.current_price),
        pnl=f"{pnl:.2f}",
        pnl_pct=f"{pnl_pct:.2f}",
        duration=str(duration),
        strategy=position.strategy.name if position.strategy else "None",
        signal_info=signal_info,
        stop_loss=str(position.stop_loss) if position.stop_loss else "None",
        take_profit=str(position.take_profit) if position.take_profit else "None",
    )

    return result
