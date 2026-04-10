"""Market Commentator Agent — generates daily market wrap-ups."""
from ai_agents.base_agent import BaseAgent


class MarketCommentatorAgent(BaseAgent):
    agent_name = "market_commentator"
    default_tier = "fast"

    def get_system_prompt(self) -> str:
        return """You are a financial market commentator for Sauron Vision.
You write professional daily market wrap-ups similar to Bloomberg or Reuters style.

Your commentary should cover:
1. Market overview (indices, key movers)
2. Sector highlights
3. Macro/economic context
4. Key technical levels
5. Forward outlook

Write in a professional but accessible tone. Use data points when available.
Keep it concise — max 500 words. Use markdown formatting."""

    def build_context(self, **kwargs) -> str:
        return f"""Generate a market commentary based on:

DATE: {kwargs.get('date', 'today')}
MARKET DATA: {kwargs.get('market_data', 'N/A')}
TOP MOVERS: {kwargs.get('top_movers', 'N/A')}
SIGNALS: {kwargs.get('signals_summary', 'N/A')}
NEWS HIGHLIGHTS: {kwargs.get('news_highlights', 'N/A')}
ECONOMIC EVENTS: {kwargs.get('events', 'N/A')}
SENTIMENT: {kwargs.get('sentiment', 'N/A')}"""

    def parse_response(self, raw_response: str) -> dict:
        return {"commentary": raw_response}
