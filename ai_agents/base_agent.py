"""Base agent class — all AI agents inherit from this."""
import time
import json
import logging
from abc import ABC, abstractmethod
from django.conf import settings
from .models import AgentTask

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Abstract base class for Sauron Vision AI agents."""

    agent_name: str = "base"
    default_tier: str = "balanced"  # "fast", "balanced", or "deep"

    def __init__(self, provider: str = None, model: str = None):
        from .catalog import resolve_agent, resolve_effort

        ai_config = settings.AI_CONFIG
        self.provider_name = provider or ai_config["default_provider"]
        # Explicit model arg > per-agent override > tier setting > env > default.
        self.model = model or resolve_agent(self.agent_name, self.default_tier)
        self.effort = resolve_effort(self.model, self.default_tier,
                                      self.agent_name)
        self.provider = self._get_provider()

    def _get_provider(self):
        """Instantiate the appropriate AI provider."""
        if self.provider_name == "claude":
            from .providers.claude_provider import ClaudeProvider
            return ClaudeProvider()
        elif self.provider_name == "openai":
            from .providers.openai_provider import OpenAIProvider
            return OpenAIProvider()
        elif self.provider_name == "ollama":
            from .providers.ollama_provider import OllamaProvider
            return OllamaProvider()
        else:
            raise ValueError(f"Unknown AI provider: {self.provider_name}")

    @abstractmethod
    def get_system_prompt(self) -> str:
        """Define the agent's role and instructions."""
        pass

    @abstractmethod
    def build_context(self, **kwargs) -> str:
        """Build the input context from database data."""
        pass

    @abstractmethod
    def parse_response(self, raw_response: str) -> dict:
        """Extract structured data from the AI response."""
        pass

    def run(self, **kwargs) -> dict:
        """Execute the agent: build context → call AI → parse response."""
        start_time = time.time()

        # Pre-initialised so the failure row below can carry whatever WAS
        # obtained before things went wrong. A parse_response crash happens
        # AFTER Anthropic billed the generation — a $0 failure row for a
        # paid call is the invisible-spend bug at one remove.
        raw_response, usage = "", {}
        try:
            system_prompt = self.get_system_prompt()
            context = self.build_context(**kwargs)

            # record=False: run() writes its own, richer AgentTask row
            # below (structured_output, duration, the failure branch) —
            # the provider's built-in ledger write would double-count
            # every BaseAgent call. This is the ONE sanctioned opt-out;
            # tests/test_llm_ledger_truth.py pins that nothing else uses it.
            raw_response, usage = self.provider.complete(
                system_prompt=system_prompt,
                user_message=context,
                model=self.model,
                effort=getattr(self, "effort", None),
                record=False,
            )

            result = self.parse_response(raw_response)
            duration = time.time() - start_time

            # Log the task
            AgentTask.objects.create(
                agent=self.agent_name,
                provider=self.provider_name,
                model=self.model,
                prompt_summary=context[:500],
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                cost_usd=usage.get("cost_usd", 0),
                response_summary=raw_response[:500],
                structured_output=result,
                success=True,
                duration_seconds=round(duration, 2),
            )

            logger.info(f"Agent {self.agent_name} completed in {duration:.1f}s")
            return result

        except Exception as e:
            duration = time.time() - start_time
            # A refused/empty generation raises INSIDE complete() but was
            # still billed — the provider hangs the usage on the exception
            # for exactly this row (record=False means nobody else wrote it).
            billed = getattr(e, "usage", None) or usage
            AgentTask.objects.create(
                agent=self.agent_name,
                provider=self.provider_name,
                model=self.model,
                prompt_summary=str(kwargs)[:500],
                input_tokens=billed.get("input_tokens", 0),
                output_tokens=billed.get("output_tokens", 0),
                cost_usd=billed.get("cost_usd", 0),
                response_summary=raw_response[:500],
                success=False,
                error=str(e),
                duration_seconds=round(duration, 2),
            )
            logger.error(f"Agent {self.agent_name} failed: {e}")
            raise
