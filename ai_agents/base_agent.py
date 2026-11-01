"""Base agent class — all AI agents inherit from this."""
import time
import json
import logging
from abc import ABC, abstractmethod
from django.conf import settings
from .models import AgentTask

logger = logging.getLogger(__name__)


def _tokens(value) -> int:
    """A usage counter as an int; 0 when absent or not an int."""
    return value if isinstance(value, int) and not isinstance(value, bool) \
        else 0


class BaseAgent(ABC):
    """Abstract base class for Sauron Vision AI agents."""

    agent_name: str = "base"
    default_tier: str = "balanced"  # "fast", "balanced", or "deep"
    # run() refuses once the day's TOTAL AI budget is spent (PR O0a). An
    # agent whose caller turns a raised error into a different decision
    # on an order path opts out: see PreTradeSanityAgent.
    total_budget_gate: bool = True
    # The longest answer the agent is expected to write, in tokens, when
    # it is longer than the provider's ANSWER_TOKENS (8,192): the provider
    # then sizes max_tokens as that plus the thinking room
    # (claude_provider.max_tokens_for). None, every agent but the weekly
    # reviewer: the provider's default bound.
    answer_tokens: int = None

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

    def _total_budget_refusal(self) -> str:
        """Why the day's total refuses this call — "" when it does not.

        The TOTAL alone (spec §7.1, revised 2026-10-15): run() never asked
        the budget, so the news analyst and the anomaly detector spent
        outside every line and AI_DAILY_BUDGET_USD was not a real ceiling.
        It refuses only once the whole ledger has reached the total — no
        deep share, no estimate — so the analyst's tags never go blind on
        an ordinary day. A budget that cannot be read refuses nothing."""
        try:
            from .spend import can_spend
            allowed, reason = can_spend(tier=self.default_tier, line="core",
                                        total_only=True)
        except Exception as e:  # noqa: BLE001 — a read error refuses nothing
            logger.warning("Agent %s: the AI budget could not be read (%s) "
                           "— running unguarded", self.agent_name, e)
            return ""
        return "" if allowed else reason

    def run(self, *, source_ref: str = "", **kwargs) -> dict:
        """Execute the agent: build context → call AI → parse response.

        `source_ref` (PR O0a) is written on this call's AgentTask row and
        handed to the provider — the key the budget lines read (a row whose
        source_ref starts with "Orc:" is billed to the Orcs). It never
        reaches build_context, so every agent's context is unchanged.

        Raises spend.BudgetRefused, before anything is sent or booked, when
        the day's total AI budget is spent (see total_budget_gate)."""
        if self.total_budget_gate:
            refused = self._total_budget_refusal()
            if refused:
                from .spend import BudgetRefused
                logger.warning("Agent %s refused: %s", self.agent_name,
                               refused)
                raise BudgetRefused(refused)

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
            #
            # agent_name even so (2026-11-01): the provider still writes
            # ONE row itself, for a declined call its refusal re-run
            # replaces (no caller writes that one), and it books it under
            # this name. Without it that row read "unattributed", and the
            # agent's decline was missing from its own failures and cost
            # on /ai/.
            call = dict(
                system_prompt=system_prompt,
                user_message=context,
                model=self.model,
                effort=getattr(self, "effort", None),
                agent_name=self.agent_name,
                record=False,
            )
            # Only when there is one: a default run hands the provider
            # the keywords above and nothing else.
            if source_ref:
                call["source_ref"] = source_ref
            if self.answer_tokens:
                call["answer_tokens"] = self.answer_tokens
            raw_response, usage = self.provider.complete(**call)

            result = self.parse_response(raw_response)
            duration = time.time() - start_time

            # Log the task — under the model that ANSWERED: after a
            # refusal re-run that is the provider's fallback, not
            # self.model, and the row must say whose rate it was billed at.
            AgentTask.objects.create(
                agent=self.agent_name,
                provider=self.provider_name,
                model=usage.get("model") or self.model,
                prompt_summary=context[:500],
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                cache_read_tokens=_tokens(
                    usage.get("cache_read_input_tokens", 0)),
                cache_write_tokens=_tokens(
                    usage.get("cache_creation_input_tokens", 0)),
                cost_usd=usage.get("cost_usd", 0),
                response_summary=raw_response[:500],
                structured_output=self._with_source_ref(result, source_ref),
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
            failure = dict(
                agent=self.agent_name,
                provider=self.provider_name,
                model=billed.get("model") or self.model,
                prompt_summary=str(kwargs)[:500],
                input_tokens=billed.get("input_tokens", 0),
                output_tokens=billed.get("output_tokens", 0),
                cache_read_tokens=_tokens(
                    billed.get("cache_read_input_tokens", 0)),
                cache_write_tokens=_tokens(
                    billed.get("cache_creation_input_tokens", 0)),
                cost_usd=billed.get("cost_usd", 0),
                response_summary=raw_response[:500],
                success=False,
                error=str(e),
                duration_seconds=round(duration, 2),
            )
            if source_ref:
                failure["structured_output"] = {"source_ref": source_ref}
            AgentTask.objects.create(**failure)
            logger.error(f"Agent {self.agent_name} failed: {e}")
            raise

    @staticmethod
    def _with_source_ref(result, source_ref: str):
        """The success row's structured_output: the parsed result as it
        always was, plus the source_ref when the caller gave one.

        The source_ref on a row is the CALLER's alone: it decides the
        budget line (spend.orc_line_q), and a parsed result is the model's
        text — the news analyst's is shaped by untrusted articles. With no
        caller source_ref, a top-level "source_ref" the model wrote is left
        off the ledger copy, so it cannot bill a core call to the Orcs.
        No parse_response of today returns that key, so default rows are
        unchanged; run() still returns the result untouched."""
        if not source_ref:
            if isinstance(result, dict) and "source_ref" in result:
                return {k: v for k, v in result.items() if k != "source_ref"}
            return result
        if isinstance(result, dict):
            return {**result, "source_ref": source_ref}
        return {"result": result, "source_ref": source_ref}
