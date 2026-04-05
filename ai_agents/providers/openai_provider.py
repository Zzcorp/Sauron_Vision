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

    def complete(self, system_prompt: str, user_message: str, model: str = "gpt-4o") -> tuple:
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
        usage = {
            "input_tokens": response.usage.prompt_tokens,
            "output_tokens": response.usage.completion_tokens,
            "cost_usd": 0,  # TODO: Calculate based on model
        }

        return text, usage
