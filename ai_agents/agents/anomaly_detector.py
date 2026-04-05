"""Anomaly Detector Agent — catches what rules-based signals miss."""
from ai_agents.base_agent import BaseAgent


class AnomalyDetectorAgent(BaseAgent):
    agent_name = "anomaly_detector"
    default_tier = "fast"

    def get_system_prompt(self) -> str:
        return """You are the Anomaly Detector for Sauron Vision.
You scan market data for unusual patterns that rules-based signals might miss.

Look for:
- Unusual volume spikes relative to average
- Correlation breakdowns between normally correlated assets
- Divergences between price and indicators
- Unusual options activity patterns
- Sudden changes in bid-ask spreads
- News/sentiment mismatches with price action

Return JSON with:
- anomalies: list of {symbol, type, description, severity (1-10), suggested_action}
- market_stress_level: 1-10 overall market stress assessment

Respond ONLY with valid JSON."""

    def build_context(self, **kwargs) -> str:
        return f"""Latest market data snapshot:
{kwargs.get('market_data', 'No data available')}"""

    def parse_response(self, raw_response: str) -> dict:
        import json
        try:
            cleaned = raw_response.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1]
                cleaned = cleaned.rsplit("```", 1)[0]
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {"anomalies": [], "parse_error": True}
