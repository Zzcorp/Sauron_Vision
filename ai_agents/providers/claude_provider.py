"""Anthropic Claude API provider."""
import os
import logging
import time

logger = logging.getLogger(__name__)

# Transient API failures worth retrying. Matched on the error TEXT because
# the SDK surfaces mid-stream errors (which it does NOT retry itself) as a
# raw error payload in the exception message — a live "Generate now" click
# showed the operator {'type': 'overloaded_error', ...} verbatim.
# rate_limit is deliberately NOT here: a fixed 2s wait cannot outlast a
# real rate-limit window; it would only re-bill a doomed generation.
_TRANSIENT_MARKERS = ("overloaded", "internal_server_error",
                      "'type': 'api_error'")
# TWO attempts, not more: several callers are synchronous staff views
# ("Run now" buttons), and each retry re-runs a potentially minutes-long
# full generation — one second chance covers the transient case without
# tripling the worst-case request time.
_MAX_ATTEMPTS = 2


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
                 model: str = "claude-sonnet-5", effort: str = None,
                 agent_name: str = "unattributed",
                 record: bool = True,
                 source_ref: str = "") -> tuple:
        """
        Call Claude API and return (response_text, usage_dict).

        `effort` (low|medium|high|xhigh|max) controls thinking depth and
        token spend on models that support it; it is dropped for models
        that don't, so a tier swap can never send an invalid parameter.

        EVERY successful call is written to the AgentTask ledger from HERE
        — the one function the money actually leaves through. The ledger
        used to be written by BaseAgent.run() alone, and all seven brain
        modules call this method directly (they need their own context and
        parsing), so the platform's biggest recurring spender was
        invisible to spend.spent_today(), to the /ai-models/ readout, and
        to the daily budget that exists to govern it: the operator's
        Anthropic console read roughly double what the platform admitted
        to. A per-caller convention already failed once; the choke point
        cannot be bypassed by the next module.

        `agent_name` attributes the row; `record=False` is for the ONE
        caller that writes its own richer AgentTask row (BaseAgent.run) —
        anything else passing it is re-opening the hole, and a test
        source-pins that it does not.
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

        # Streamed, not create(): the SDK refuses a non-streaming request
        # whose max_tokens could outlive its ten-minute HTTP window, and the
        # 32k thinking budget is over that line — every deep-tier call died
        # with "Streaming is required for operations that may take longer
        # than 10 minutes" before a single token was generated. The stream
        # accumulates into the same Message object create() would return.
        #
        # Retried at the APP level: the SDK retries pre-stream HTTP errors
        # but an error EVENT arriving mid-stream (529 Overloaded does this)
        # raises without retry, and it used to bubble the raw payload all
        # the way to the operator's screen.
        response = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                with client.messages.stream(
                    model=model,
                    max_tokens=max_tokens,
                    system=system_prompt,
                    messages=[
                        {"role": "user", "content": user_message}
                    ],
                    **kwargs,
                ) as stream:
                    response = stream.get_final_message()
                break
            except Exception as e:  # noqa: BLE001 — matched on content below
                msg = str(e)
                transient = any(m in msg.lower() for m in _TRANSIENT_MARKERS)
                if not transient or attempt == _MAX_ATTEMPTS:
                    if "overloaded" in msg.lower():
                        raise RuntimeError(
                            "Anthropic is overloaded right now — "
                            f"{_MAX_ATTEMPTS} attempts all bounced. "
                            "Try again in a minute.") from e
                    raise
                wait = 2 * attempt  # 2s, then 4s
                logger.warning("[claude] transient API error "
                               "(attempt %d/%d, retrying in %ds): %.160s",
                               attempt, _MAX_ATTEMPTS, wait, msg)
                time.sleep(wait)

        # Adaptive-thinking models may put a thinking block before the text
        # block, and a safety refusal can return no text at all — never index
        # content[0] blindly.
        text = next((b.text for b in response.content if b.type == "text"), "")

        # Usage FIRST, before any verdict on the response: a refused or
        # empty generation was still generated, Anthropic still billed it,
        # and a ledger that only counts the calls that went well is the
        # same under-reporting this module was rewritten to end — one
        # failure mode over. Cost from the shared catalog, so a model
        # added there is priced correctly everywhere instead of silently
        # billing at a stale rate.
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        pricing = pricing_for(model)
        cost = (input_tokens * pricing["input"]
                + output_tokens * pricing["output"]) / 1_000_000
        usage = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": round(cost, 6),
        }

        def _ledger(success: bool, summary: str, error: str = ""):
            if not record:
                return
            # Fenced: a ledger hiccup must not kill the call it measures —
            # but it fails LOUDLY, because a quiet miss here is exactly the
            # under-reporting this write exists to end.
            try:
                from ai_agents.models import AgentTask
                AgentTask.objects.create(
                    agent=agent_name[:30],
                    provider="claude",
                    model=model,
                    prompt_summary=user_message[:500],
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=usage["cost_usd"],
                    response_summary=summary[:500],
                    # The row that lets the backfill recognise a call the
                    # provider already recorded, when the caller's own
                    # domain row predates the call (research asks, position
                    # reviews). See backfill_llm_ledger.
                    structured_output=({"source_ref": source_ref}
                                       if source_ref else {}),
                    success=success,
                    error=error[:1000],
                )
            except Exception:  # noqa: BLE001 — see the fence note above
                logger.error(
                    "[ledger] FAILED to record $%.4f for %s (%s) — the "
                    "daily budget is now undercounting", usage["cost_usd"],
                    agent_name, model, exc_info=True)

        def _raise_billed(message: str):
            # The exception carries the usage so record=False callers
            # (BaseAgent.run's except branch) can still ledger the real
            # cost of a failed-but-billed call in their own row.
            _ledger(False, text, error=message)
            err = RuntimeError(message)
            err.usage = usage
            raise err

        # A truncated or refused response is a FAILED call, not an empty
        # success: without this every caller's parse_response would swallow
        # it and log success=True with no output.
        stop_reason = getattr(response, "stop_reason", None)
        if stop_reason == "max_tokens":
            logger.warning("Claude response truncated at max_tokens (%s, %s)",
                           model, max_tokens)
        elif stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            _raise_billed(
                f"Claude declined the request (model={model}, "
                f"category={getattr(details, 'category', None)})")
        if not text:
            _raise_billed(
                f"Claude returned no text (model={model}, "
                f"stop_reason={stop_reason})")

        _ledger(True, text)
        return text, usage
