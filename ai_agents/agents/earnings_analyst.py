"""Earnings Analyst Agent — rapid post-earnings assessment."""
from ai_agents.base_agent import BaseAgent


class EarningsAnalystAgent(BaseAgent):
    agent_name = "earnings_analyst"
    default_tier = "balanced"

    def get_system_prompt(self) -> str:
        return """You are the Earnings Analyst for Sauron Vision.
When a company reports earnings, you analyze the release and provide trading intelligence.

Focus on:
- Beat/miss vs consensus on revenue, EPS, and guidance
- Management tone and forward guidance
- Key metric changes (margins, growth rates, customer counts)
- Market reaction context (was this expected? is the move justified?)
- Trading implications: is this a buy-the-dip, sell-the-news, or hold situation?

Return structured JSON with your analysis."""

    def build_context(self, **kwargs) -> str:
        return f"""Earnings data:
Symbol: {kwargs.get('symbol', '')}
Report: {kwargs.get('report', '')}
Estimates: {kwargs.get('estimates', '')}
Price reaction: {kwargs.get('price_reaction', '')}"""

    def parse_response(self, raw_response: str) -> dict:
        return {"analysis": raw_response}
