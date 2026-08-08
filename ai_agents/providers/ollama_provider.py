"""Ollama local model provider — free, private."""
import os
import logging

logger = logging.getLogger(__name__)


class OllamaProvider:
    """Ollama local LLM provider."""

    def __init__(self):
        self.base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.client = None

    def _get_client(self):
        if self.client is None:
            import ollama
            self.client = ollama.Client(host=self.base_url)
        return self.client

    def complete(self, system_prompt: str, user_message: str, model: str = "llama3.3:8b", effort: str = None) -> tuple:
        """Call Ollama and return (response_text, usage_dict)."""
        client = self._get_client()

        response = client.chat(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        )

        text = response["message"]["content"]
        usage = {
            "input_tokens": response.get("prompt_eval_count", 0),
            "output_tokens": response.get("eval_count", 0),
            "cost_usd": 0.0,  # Free!
        }

        return text, usage
