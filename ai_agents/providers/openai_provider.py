"""OpenAI GPT API provider (fallback)."""
import os
import logging

logger = logging.getLogger(__name__)


class OpenAIProvider:
    """OpenAI API provider."""

    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY", "")
        self.client = None

    def _get_client(self):
        if self.client is None:
            import openai
            self.client = openai.OpenAI(api_key=self.api_key)
        return self.client

    def complete(self, system_prompt: str, user_message: str, model: str = "gpt-4o", effort: str = None,
                 agent_name: str = "unattributed", record: bool = True,
                 source_ref: str = "") -> tuple:
        # agent_name/record mirror ClaudeProvider so a provider swap can
        # never TypeError on the ledger kwargs BaseAgent now passes.
        # Ledger writes stay Claude-side only: this platform runs Claude,
        # and a second writer here would double-count a future migration
        # that moves the write into a shared base class instead.
        """Call OpenAI API and return (response_text, usage_dict)."""
        client = self._get_client()

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            max_tokens=4096,
        )

        text = response.choices[0].message.content
        input_tokens = response.usage.prompt_tokens
        output_tokens = response.usage.completion_tokens
        cost_usd = self._estimate_cost(model, input_tokens, output_tokens)
        usage = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost_usd,
        }

        return text, usage

    @staticmethod
    def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost in USD based on model pricing (per 1M tokens)."""
        pricing = {
            "gpt-4o":       {"input": 2.50, "output": 10.00},
            "gpt-4o-mini":  {"input": 0.15, "output": 0.60},
            "gpt-4-turbo":  {"input": 10.00, "output": 30.00},
            "gpt-4":        {"input": 30.00, "output": 60.00},
            "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
            "o1":           {"input": 15.00, "output": 60.00},
            "o1-mini":      {"input": 3.00, "output": 12.00},
            "o3-mini":      {"input": 1.10, "output": 4.40},
        }
        rates = pricing.get(model, {"input": 2.50, "output": 10.00})
        cost = (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000
        return round(cost, 6)
