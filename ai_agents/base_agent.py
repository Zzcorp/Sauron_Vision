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
        ai_config = settings.AI_CONFIG
        self.provider_name = provider or ai_config["default_provider"]
        self.model = model or ai_config["models"].get(self.default_tier, "claude-sonnet-4-20250514")
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

        try:
            system_prompt = self.get_system_prompt()
            context = self.build_context(**kwargs)

            raw_response, usage = self.provider.complete(
                system_prompt=system_prompt,
                user_message=context,
                model=self.model,
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
            AgentTask.objects.create(
                agent=self.agent_name,
                provider=self.provider_name,
                model=self.model,
                prompt_summary=str(kwargs)[:500],
                success=False,
                error=str(e),
                duration_seconds=round(duration, 2),
            )
            logger.error(f"Agent {self.agent_name} failed: {e}")
            raise
