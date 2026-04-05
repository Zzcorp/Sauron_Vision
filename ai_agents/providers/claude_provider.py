"""Anthropic Claude API provider."""
import os
import logging

logger = logging.getLogger(__name__)


class ClaudeProvider:
    """Claude API provider for Sauron Vision agents."""

    # Pricing per million tokens (USD)
    PRICING = {
        "claude-haiku-4-5-20251001": {"input": 1.0, "output": 5.0},
        "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
        "claude-opus-4-6": {"input": 5.0, "output": 25.0},
    }

    def __init__(self):
        self.api_key = os.getenv("ANTHROPIC_API_KEY", "")
        self.client = None

    def _get_client(self):
        if self.client is None:
            import anthropic
            self.client = anthropic.Anthropic(api_key=self.api_key)
        return self.client

    def complete(self, system_prompt: str, user_message: str, model: str = "claude-sonnet-4-20250514") -> tuple:
        """
        Call Claude API and return (response_text, usage_dict).
        """
        client = self._get_client()

        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=system_prompt,
            messages=[
                {"role": "user", "content": user_message}
            ],
        )

        text = response.content[0].text
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens

        # Calculate cost
        pricing = self.PRICING.get(model, {"input": 3.0, "output": 15.0})
        cost = (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000

        usage = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": round(cost, 6),
        }

        return text, usage
