"""Weekly Reviewer Agent — deep analysis of the past week."""
from ai_agents.base_agent import BaseAgent


class WeeklyReviewerAgent(BaseAgent):
    agent_name = "weekly_reviewer"
    default_tier = "deep"

    def get_system_prompt(self) -> str:
        return """You are the Weekly Reviewer for Sauron Vision.
Every Saturday, you perform a deep analysis of the trading week.

Your review must cover:
1. PERFORMANCE: How did each active strategy perform? What was the P&L?
2. SIGNAL QUALITY: Which signals led to good trades? Which were false positives?
3. MACRO REGIME: Has the macro environment shifted? Risk-on vs risk-off assessment.
4. STRATEGY GRADES: Grade each strategy A-F with reasoning.
5. PARAMETER ADJUSTMENTS: Should any signal thresholds be adjusted?
6. NEXT WEEK OUTLOOK: Key events, levels to watch, potential setups.
7. RISK ASSESSMENT: Portfolio health, concentration risks, correlation concerns.

Be thorough, analytical, and specific. Reference actual numbers and events."""

    def build_context(self, **kwargs) -> str:
        return f"""Weekly data for review:

PORTFOLIO SNAPSHOTS: {kwargs.get('snapshots', 'N/A')}
ACTIVE STRATEGIES: {kwargs.get('strategies', 'N/A')}
SIGNALS GENERATED: {kwargs.get('signals', 'N/A')}
MACRO DATA: {kwargs.get('macro', 'N/A')}
KEY NEWS: {kwargs.get('news_digest', 'N/A')}
ECONOMIC EVENTS: {kwargs.get('economic_events', 'N/A')}"""

    def parse_response(self, raw_response: str) -> dict:
        return {"review": raw_response}
