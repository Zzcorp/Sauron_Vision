"""News Analyst Agent — processes news articles into structured sentiment."""
import json
from ai_agents.base_agent import BaseAgent


class NewsAnalystAgent(BaseAgent):
    agent_name = "news_analyst"
    default_tier = "fast"

    def get_system_prompt(self) -> str:
        return """You are a financial news analyst for Sauron Vision, a trading intelligence platform.
Your job is to analyze news articles and extract structured trading intelligence.

For each article, you must return a JSON object with:
- sentiment_score: float from -1.0 (very bearish) to +1.0 (very bullish)
- urgency: one of "critical", "high", "normal", "low"
- affected_symbols: list of ticker symbols affected (e.g., ["AAPL", "EURUSD", "XAUUSD"])
- summary: 1-2 sentence summary of the trading relevance
- market_impact: brief description of expected market impact

Respond ONLY with valid JSON, no other text."""

    def build_context(self, **kwargs) -> str:
        article = kwargs.get("article", {})
        return f"""Analyze this financial news article:

Title: {article.get('title', '')}
Source: {article.get('source', '')}
Published: {article.get('published_at', '')}
Content: {article.get('content', '')}"""

    def parse_response(self, raw_response: str) -> dict:
        try:
            # Strip markdown code fences if present
            cleaned = raw_response.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1]
                cleaned = cleaned.rsplit("```", 1)[0]
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {
                "sentiment_score": 0.0,
                "urgency": "low",
                "affected_symbols": [],
                "summary": "Failed to parse AI response",
                "market_impact": "Unknown",
                "parse_error": True,
            }
