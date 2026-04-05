"""Strategy Advisor Agent — portfolio-aware strategy recommendations."""
import json
from ai_agents.base_agent import BaseAgent


class StrategyAdvisorAgent(BaseAgent):
    agent_name = "strategy_advisor"
    default_tier = "balanced"

    def get_system_prompt(self) -> str:
        return """You are the Strategy Advisor for Sauron Vision, a trading intelligence platform.
You receive active trading signals, current portfolio state, macro context, and market data.
Your job is to synthesize all inputs and propose actionable trading strategies.

A strategy is NOT just a signal. It must consider:
1. Current portfolio exposure (by asset class, sector, currency)
2. Correlation with existing positions
3. Risk budget remaining
4. Macro regime (risk-on/risk-off, tightening/easing)
5. Position sizing based on volatility and conviction

Return a JSON object with:
- strategies: list of proposed strategy objects, each containing:
  - name: descriptive strategy name
  - thesis: why this trade makes sense given all context
  - instruments: list of {symbol, action (long/short/hedge), weight}
  - entry_conditions: what needs to happen to enter
  - exit_conditions: stop loss and take profit logic
  - risk_parameters: {max_allocation_pct, max_loss_pct}
  - time_horizon: scalp/intraday/swing/position
  - confidence: 0.0 to 1.0
- portfolio_notes: any concerns about current portfolio state
- macro_assessment: current macro regime summary

Respond ONLY with valid JSON."""

    def build_context(self, **kwargs) -> str:
        signals = kwargs.get("signals", [])
        portfolio = kwargs.get("portfolio", {})
        macro = kwargs.get("macro_data", {})
        exposure = kwargs.get("exposure", {})

        return f"""ACTIVE SIGNALS:
{json.dumps(signals, indent=2, default=str)}

CURRENT PORTFOLIO:
{json.dumps(portfolio, indent=2, default=str)}

EXPOSURE BREAKDOWN:
{json.dumps(exposure, indent=2, default=str)}

MACRO CONTEXT:
{json.dumps(macro, indent=2, default=str)}

Based on all the above, propose trading strategies."""

    def parse_response(self, raw_response: str) -> dict:
        try:
            cleaned = raw_response.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1]
                cleaned = cleaned.rsplit("```", 1)[0]
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {"strategies": [], "parse_error": True}
