"""Central Bank Speech Analyst — hawkish/dovish scoring of Fed/ECB speeches."""
from ai_agents.base_agent import BaseAgent
import json


class SpeechAnalystAgent(BaseAgent):
    agent_name = "speech_analyst"
    default_tier = "fast"

    def get_system_prompt(self) -> str:
        return """You are a central bank communications analyst for Sauron Vision.
You analyze speeches, press conferences, and meeting minutes from central banks (Fed, ECB, BoJ, BoE, etc.).

Your task is to score the text on a hawkish-dovish spectrum:
- Score from -10 (extremely dovish) to +10 (extremely hawkish)
- Identify key policy signals and forward guidance
- Flag any changes in tone from recent communications
- Assess market impact probability

Return JSON:
{
    "hawkish_dovish_score": <-10 to 10>,
    "key_phrases": [{"phrase": "...", "significance": "..."}],
    "policy_signals": ["..."],
    "tone_change": "more_hawkish" | "unchanged" | "more_dovish",
    "market_impact": {
        "equities": "positive" | "negative" | "neutral",
        "bonds": "positive" | "negative" | "neutral",
        "forex_usd": "positive" | "negative" | "neutral",
        "gold": "positive" | "negative" | "neutral"
    },
    "summary": "..."
}

Respond ONLY with valid JSON."""

    def build_context(self, **kwargs) -> str:
        return f"""Central bank speech/document to analyze:

Speaker: {kwargs.get('speaker', 'Unknown')}
Institution: {kwargs.get('institution', 'Unknown')}
Date: {kwargs.get('date', 'Unknown')}

Text:
{kwargs.get('text', 'No text provided')}

Previous tone reference: {kwargs.get('previous_tone', 'No prior reference')}"""

    def parse_response(self, raw_response: str) -> dict:
        try:
            cleaned = raw_response.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1]
                cleaned = cleaned.rsplit("```", 1)[0]
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {"hawkish_dovish_score": 0, "parse_error": True, "raw": raw_response}
