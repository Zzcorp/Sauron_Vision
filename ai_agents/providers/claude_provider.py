"""Anthropic Claude API provider."""
import os
import logging

logger = logging.getLogger(__name__)


class ClaudeProvider:
    """Claude API provider for Sauron Vision agents."""

    def __init__(self):
        self.api_key = os.getenv("ANTHROPIC_API_KEY", "")
        self.client = None

    def _get_client(self):
        if self.client is None:
            import anthropic
            self.client = anthropic.Anthropic(api_key=self.api_key)
        return self.client

    def complete(self, system_prompt: str, user_message: str,
                 model: str = "claude-sonnet-5", effort: str = None) -> tuple:
        """
        Call Claude API and return (response_text, usage_dict).

        `effort` (low|medium|high|xhigh|max) controls thinking depth and
        token spend on models that support it; it is dropped for models
        that don't, so a tier swap can never send an invalid parameter.
        """
        from ai_agents.catalog import pricing_for, supports_effort, supports_thinking

        client = self._get_client()

        kwargs = {}
        if effort and supports_effort(model):
            kwargs["output_config"] = {"effort": effort}

        # max_tokens caps thinking AND response text together, and adaptive
        # thinking is on by default on the current models — a budget sized
        # for the answer alone truncates it. Thinking models get headroom.
        max_tokens = 32000 if supports_thinking(model) else 8192

        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[
                {"role": "user", "content": user_message}
            ],
            **kwargs,
        )

        # Adaptive-thinking models may put a thinking block before the text
        # block, and a safety refusal can return no text at all — never index
        # content[0] blindly.
        text = next((b.text for b in response.content if b.type == "text"), "")

        # A truncated or refused response is a FAILED call, not an empty
        # success: without this every caller's parse_response would swallow
        # it and log success=True with no output.
        stop_reason = getattr(response, "stop_reason", None)
        if stop_reason == "max_tokens":
            logger.warning("Claude response truncated at max_tokens (%s, %s)",
                           model, max_tokens)
        elif stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            raise RuntimeError(
                f"Claude declined the request (model={model}, "
                f"category={getattr(details, 'category', None)})")
        if not text:
            raise RuntimeError(
                f"Claude returned no text (model={model}, "
                f"stop_reason={stop_reason})")
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens

        # Cost from the shared catalog, so a model added there is priced
        # correctly everywhere instead of silently billing at a stale rate.
        pricing = pricing_for(model)
        cost = (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000

        usage = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": round(cost, 6),
        }

        return text, usage
