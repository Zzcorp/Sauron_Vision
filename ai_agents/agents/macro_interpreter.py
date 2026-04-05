"""Macro Interpreter Agent — connects macro events to trade impact."""
from ai_agents.base_agent import BaseAgent


class MacroInterpreterAgent(BaseAgent):
    agent_name = "macro_interpreter"
    default_tier = "balanced"

    def get_system_prompt(self) -> str:
        return """You are the Macro Interpreter for Sauron Vision.
When new macro data arrives (FRED updates, economic events), you assess the impact
on the current portfolio and each asset class.

Consider:
- What does this data point mean for monetary policy?
- How does it affect stocks, bonds, forex, and commodities differently?
- Is this data point surprising vs market expectations?
- What are the second-order effects?
- How should the portfolio be adjusted?

Return structured JSON with impact assessment per asset class."""

    def build_context(self, **kwargs) -> str:
        return f"""New macro data:
Indicator: {kwargs.get('indicator', '')}
Value: {kwargs.get('value', '')}
Previous: {kwargs.get('previous', '')}
Expected: {kwargs.get('expected', '')}
Current portfolio: {kwargs.get('portfolio', '')}"""

    def parse_response(self, raw_response: str) -> dict:
        return {"interpretation": raw_response}
