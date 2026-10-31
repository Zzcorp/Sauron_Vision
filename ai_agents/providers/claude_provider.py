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

# Where a declined request re-runs. A model's safety classifiers can
# decline a request outright (stop_reason "refusal") — not an outage, not
# an answer. Opus 5 runs classifiers too and can decline as well; they are
# narrower than Opus 5.5's, which suits a rescue model. One re-run there
# is the platform's own fallback, and it never chains (a decline on the
# fallback is returned as it is).
REFUSAL_FALLBACK_MODEL = "claude-opus-5"
# The tiers whose caller cleared the deep reserve BEFORE calling:
# spend.can_spend keys DEEP_TIER_SHARE off "deep" and "frontier" alike, so
# a decline there re-runs on money the caller was already allowed. A fast-
# or balanced-tier caller (the hourly scan, the news read, the briefing)
# was guarded — where guarded at all — for a Haiku or a Sonnet call; its
# re-run is Opus money, late in the day exactly what the reserve holds
# back, so it asks the deep tier's own question first (_fallback_held).
_RESERVE_ALREADY_CLEARED = ("deep", "frontier")

# The beta headers complete()'s keyword arguments switch on (PR O0a; the
# bundled Claude API reference). Each is sent ONLY when its keyword is
# used, and a request carrying any of them goes through
# client.beta.messages: the plain stream() has no `betas`, `fallbacks` or
# `speed`. A default request carries none and keeps the plain client.
EFFORT_MESSAGE_BETA = "mid-conversation-output-config-2026-07-01"
SERVER_FALLBACK_BETA = "server-side-fallback-2026-07-01"        # "default"
SERVER_FALLBACK_LIST_BETA = "server-side-fallback-2026-06-01"   # [{model}]
TASK_BUDGET_BETA = "task-budgets-2026-03-13"
FAST_MODE_BETA = "fast-mode-2026-02-01"
# The API's limits, refused here before a 400 is paid for.
MAX_CACHE_BREAKPOINTS = 4
TASK_BUDGET_MIN = 20_000
_CACHE_TTLS = ("5m", "1h")

# The provider's clock for duration_seconds, patchable in tests without
# touching the time module every other library reads.
_monotonic = time.monotonic


def _fallback_held(model: str, usage: dict, line: str = "core",
                   write_x: float = 1.0) -> str:
    """Why a decline on `model` may NOT re-run on the deep tier — "" when
    it may. Priced as the re-run will bill: the same prompt again, at the
    fallback's own input rate. Asked on the caller's budget `line`.

    The WHOLE prompt: with cache blocks, input_tokens is only the uncached
    share, and the fallback cannot read another model's cache, so it pays
    the cached share again as fresh writes. `write_x` is the dearest write
    multiplier the request used (2x for a 1-hour breakpoint, 1.25x for a
    5-minute one, 1.0 without one); with no cache token and no breakpoint
    the figure is the one of before, to the bit."""
    from ai_agents.catalog import MODELS, pricing_for
    from ai_agents.spend import can_spend
    if MODELS.get(model, {}).get("tier_hint") in _RESERVE_ALREADY_CLEARED:
        return ""
    prompt = (usage["input_tokens"]
              + usage.get("cache_read_input_tokens", 0)
              + usage.get("cache_creation_input_tokens", 0))
    rerun = (prompt * pricing_for(REFUSAL_FALLBACK_MODEL)["input"]
             * write_x / 1_000_000)
    allowed, reason = can_spend(tier="deep", estimated_usd=rerun, line=line)
    return "" if allowed else reason


def _tok(obj, name: str) -> int:
    """A usage counter as an int: 0 when absent, None, or not an int.

    Not int(getattr(..., 0) or 0): the ledger tests build usages from
    MagicMock, whose every attribute is a truthy MagicMock and whose
    int() is 1 — a phantom token on each cache field would break "cost
    identical when cache tokens are 0". The real SDK reports an absent
    cache field as None."""
    value = getattr(obj, name, None)
    return value if isinstance(value, int) and not isinstance(value, bool) \
        else 0


def _text_blocks(spec, slot: str) -> list:
    """[{"text", "cache_ttl"}] -> API text blocks. cache_ttl "5m" is the
    default ephemeral TTL, "1h" the long one, None no breakpoint."""
    if not isinstance(spec, (list, tuple)) or not spec:
        raise ValueError(f"{slot}: a non-empty list of "
                         "{'text': str, 'cache_ttl': '5m'|'1h'|None}")
    out = []
    for item in spec:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str) \
                or not item["text"]:
            raise ValueError(f"{slot}: each block is {{'text': non-empty str, "
                             f"'cache_ttl': '5m'|'1h'|None}}, got {item!r}")
        ttl = item.get("cache_ttl")
        if ttl is not None and ttl not in _CACHE_TTLS:
            raise ValueError(f"{slot}: cache_ttl is '5m', '1h' or None, "
                             f"not {ttl!r}")
        block = {"type": "text", "text": item["text"]}
        if ttl == "5m":
            block["cache_control"] = {"type": "ephemeral"}
        elif ttl == "1h":
            block["cache_control"] = {"type": "ephemeral", "ttl": "1h"}
        out.append(block)
    return out


def _turns(*, user_message, user_blocks, shared_user_blocks,
           private_user_blocks, turn_effort):
    """The `messages` list, and the text the ledger summarises."""
    if user_blocks is not None:
        content = _text_blocks(user_blocks, "user_blocks")
        return ([{"role": "user", "content": content}],
                "\n".join(b["text"] for b in content))
    if shared_user_blocks is not None:
        shared = _text_blocks(shared_user_blocks, "shared_user_blocks")
        messages = [{"role": "user", "content": shared}]
        summary = "\n".join(b["text"] for b in shared)
        if private_user_blocks is not None:
            private = _text_blocks(private_user_blocks, "private_user_blocks")
            if turn_effort is not None:
                # The effort-only system message: no text, so it may sit
                # anywhere; the API applies it from the NEXT user turn,
                # which is why it goes between the shared turn and the
                # private one it must govern (spec §5.2a).
                messages.append({"role": "system", "content": [],
                                 "output_config": {"effort": turn_effort}})
            messages.append({"role": "user", "content": private})
            summary = "\n".join(b["text"] for b in private)
        return messages, summary
    return [{"role": "user", "content": user_message}], user_message


def build_request(*, model: str, system_prompt: str = "",
                  user_message: str = "", effort: str = None,
                  system_blocks=None, user_blocks=None,
                  shared_user_blocks=None, private_user_blocks=None,
                  turn_effort: str = None, output_schema: dict = None,
                  max_tokens: int = None, fallbacks=None,
                  timeout_s: float = None, task_budget: int = None,
                  speed: str = None) -> dict:
    """The exact keyword arguments complete() hands the SDK's stream(),
    after every check: {"beta": bool, "kwargs": {...}, "summary": str,
    "ttls": [...]}. Raises ValueError, before anything is sent, on a
    request the API would refuse or this platform does not allow.

    With every PR O0a keyword at its default the kwargs are byte for byte
    the request of before (tests/test_claude_provider_bytes.py)."""
    from ai_agents.catalog import (EFFORT_LEVELS, fast_pricing_for,
                                   server_fallback, supports_effort,
                                   supports_per_message_effort,
                                   supports_task_budget, supports_thinking)

    # ── which slots, and not two ways of filling one ─────────────────
    if system_blocks is not None and system_prompt:
        raise ValueError("pass system_prompt OR system_blocks, not both")
    blocks_for_user = (user_blocks, shared_user_blocks, private_user_blocks)
    if any(b is not None for b in blocks_for_user) and user_message:
        raise ValueError("pass user_message OR user blocks, not both")
    if user_blocks is not None and (shared_user_blocks is not None
                                    or private_user_blocks is not None):
        raise ValueError("user_blocks is one turn; shared_user_blocks and "
                         "private_user_blocks are the two-turn layout — "
                         "not both")
    if private_user_blocks is not None and shared_user_blocks is None:
        raise ValueError("private_user_blocks needs shared_user_blocks: the "
                         "shared, cached turn comes first")
    if turn_effort is not None:
        if private_user_blocks is None:
            raise ValueError("turn_effort governs the private turn: pass "
                             "shared_user_blocks and private_user_blocks")
        if turn_effort not in EFFORT_LEVELS:
            raise ValueError(f"turn_effort {turn_effort!r} is not one of "
                             f"{EFFORT_LEVELS}")
        if not supports_per_message_effort(model):
            raise ValueError(f"{model} does not take the effort-only system "
                             "message")
    if output_schema is not None and not isinstance(output_schema, dict):
        raise ValueError("output_schema is a JSON schema (a dict)")
    if max_tokens is not None and (not isinstance(max_tokens, int)
                                   or isinstance(max_tokens, bool)
                                   or max_tokens < 1):
        raise ValueError(f"max_tokens must be a positive int, not "
                         f"{max_tokens!r}")
    if task_budget is not None:
        if (not isinstance(task_budget, int) or isinstance(task_budget, bool)
                or task_budget < TASK_BUDGET_MIN):
            raise ValueError(f"task_budget is at least {TASK_BUDGET_MIN} "
                             f"tokens, not {task_budget!r}")
        if not supports_task_budget(model):
            raise ValueError(f"{model} does not take a task budget")
    if speed is not None:
        if speed != "fast":
            raise ValueError(f"speed is 'fast' or None, not {speed!r}")
        if not fast_pricing_for(model):
            raise ValueError(f"{model} has no fast mode")
    if fallbacks is not None:
        forms = server_fallback(model)
        if forms is None:
            raise ValueError(f"{model} has no server-side fallback")
        if fallbacks == "default":
            pass
        elif isinstance(fallbacks, list):
            if forms != "both":
                raise ValueError(f"{model} takes only fallbacks=\"default\"")
            if not fallbacks or not all(
                    isinstance(f, dict) and isinstance(f.get("model"), str)
                    for f in fallbacks):
                raise ValueError("the list form is [{'model': id}, ...]")
        else:
            raise ValueError(f"fallbacks is \"default\" or a list of "
                             f"{{'model': id}}, not {fallbacks!r}")
    if timeout_s is not None and not (isinstance(timeout_s, (int, float))
                                      and timeout_s > 0):
        raise ValueError(f"timeout_s must be positive, not {timeout_s!r}")

    # ── the blocks, the turns, the breakpoints ───────────────────────
    system = (system_prompt if system_blocks is None
              else _text_blocks(system_blocks, "system_blocks"))
    messages, summary = _turns(
        user_message=user_message, user_blocks=user_blocks,
        shared_user_blocks=shared_user_blocks,
        private_user_blocks=private_user_blocks, turn_effort=turn_effort)
    ttls = []
    for block in (system if isinstance(system, list) else []) + [
            b for m in messages if isinstance(m.get("content"), list)
            for b in m["content"]]:
        if "cache_control" in block:
            ttls.append(block["cache_control"].get("ttl", "5m"))
    if len(ttls) > MAX_CACHE_BREAKPOINTS:
        raise ValueError(f"{len(ttls)} cache breakpoints; the API allows "
                         f"{MAX_CACHE_BREAKPOINTS}")
    if "1h" in ttls and "5m" in ttls[:len(ttls) - ttls[::-1].index("1h")]:
        raise ValueError("a 1-hour cache breakpoint after a 5-minute one: "
                         "the longer TTL must come first")

    # ── the request ──────────────────────────────────────────────────
    # max_tokens caps thinking AND response text together, and adaptive
    # thinking is on by default on the current models — a budget sized
    # for the answer alone truncates it. Thinking models get headroom. A
    # caller's own bound (the Orcs' per-wake cap, spec §7.3) replaces it.
    if max_tokens is None:
        max_tokens = 32000 if supports_thinking(model) else 8192
    kwargs = {"model": model, "max_tokens": max_tokens, "system": system,
              "messages": messages}
    output_config = {}
    if effort and supports_effort(model):
        output_config["effort"] = effort
    if output_schema is not None:
        output_config["format"] = {"type": "json_schema",
                                   "schema": output_schema}
    if task_budget is not None:
        output_config["task_budget"] = {"type": "tokens",
                                        "total": task_budget}
    if output_config:
        kwargs["output_config"] = output_config
    betas = []
    if turn_effort is not None:
        betas.append(EFFORT_MESSAGE_BETA)
    if fallbacks is not None:
        kwargs["fallbacks"] = fallbacks
        betas.append(SERVER_FALLBACK_BETA if fallbacks == "default"
                     else SERVER_FALLBACK_LIST_BETA)
    if task_budget is not None:
        betas.append(TASK_BUDGET_BETA)
    if speed is not None:
        kwargs["speed"] = speed
        betas.append(FAST_MODE_BETA)
    if betas:
        kwargs["betas"] = betas
    if timeout_s is not None:
        kwargs["timeout"] = float(timeout_s)
    return {"beta": bool(betas), "kwargs": kwargs, "summary": summary,
            "ttls": ttls}


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

    def complete(self, system_prompt: str = "", user_message: str = "",
                 model: str = "claude-sonnet-5", effort: str = None,
                 agent_name: str = "unattributed",
                 record: bool = True,
                 source_ref: str = "", *,
                 system_blocks: list = None,
                 user_blocks: list = None,
                 shared_user_blocks: list = None,
                 private_user_blocks: list = None,
                 turn_effort: str = None,
                 output_schema: dict = None,
                 max_tokens: int = None,
                 fallbacks=None,
                 line: str = "core",
                 client_refusal_rerun: bool = True,
                 timeout_s: float = None,
                 task_budget: int = None,
                 speed: str = None) -> tuple:
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
        source-pins that it does not. The usage dict names the `model`
        that answered: after a refusal re-run that is the fallback, not
        the model asked for, and the opt-out caller's own row must say
        whose rate it was billed at.

        THE KEYWORD-ONLY ARGUMENTS (PR O0a, 2026-10-15; the Orcs spec
        §7.3, §7.5.8, §5.2a). No caller of today passes one, and with all
        of them at their defaults the request is byte for byte the one of
        before (tests/test_claude_provider_bytes.py). build_request()
        checks them and raises ValueError before anything is sent.

        * `system_blocks=[{"text", "cache_ttl"}]` replaces the plain
          `system_prompt` with text blocks; cache_ttl "1h", "5m" or None
          puts a cache breakpoint on the block (or none).
        * `user_blocks` does the same for the one user turn.
        * `shared_user_blocks` + `private_user_blocks`: TWO user turns —
          the shared, cached one (the market day every Orc on a model
          shares) and the private one (the position and the tail).
          `turn_effort` puts the effort-only system message between them
          (beta): the API applies it from the next user turn, so it rules
          the private turn without invalidating the cached shared one.
          `effort` stays the top-level effort, pinned per model.
        * `output_schema`: structured outputs, output_config.format.
        * `max_tokens`: the caller's bound (the Orcs' per-wake cap).
        * `fallbacks`: "default" or [{"model": id}] — the server re-runs a
          refused request itself (beta). The ledger then books the model
          that answered and the cost of every attempt.
        * `line`: the budget line the client-side refusal re-run asks.
        * `client_refusal_rerun=False`: no re-run on
          REFUSAL_FALLBACK_MODEL; a refusal is a billed failure. Every Orc
          call passes False and relies on `fallbacks` alone.
        * `timeout_s`, `task_budget` (beta, >= 20,000 tokens) and
          `speed="fast"` (beta, Opus only, the fast price): off by default.

        The cost is cache-aware (catalog.cost_usd): cache reads at the
        model's cache price, 5-minute writes at 1.25x and 1-hour writes at
        2x its input price. With no cache token it is the old two-term
        arithmetic, bit for bit. The usage dict adds the cache counters,
        the stop reason and the call's wall time; the ledger row adds
        `duration_seconds` and the cache columns.
        """
        from ai_agents.catalog import (CACHE_WRITE_1H_X, CACHE_WRITE_5M_X,
                                       cost_usd, known_model)
        from ai_agents.spend import LINES

        if line not in LINES:
            raise ValueError(f"unknown budget line {line!r} (one of {LINES})")
        request = build_request(
            model=model, system_prompt=system_prompt,
            user_message=user_message, effort=effort,
            system_blocks=system_blocks, user_blocks=user_blocks,
            shared_user_blocks=shared_user_blocks,
            private_user_blocks=private_user_blocks, turn_effort=turn_effort,
            output_schema=output_schema, max_tokens=max_tokens,
            fallbacks=fallbacks, timeout_s=timeout_s,
            task_budget=task_budget, speed=speed)
        call = request["kwargs"]
        bound = call["max_tokens"]

        client = self._get_client()
        # The beta client only when a beta is in play; the default request
        # keeps going through client.messages.stream, as it always did.
        api = client.beta.messages if request["beta"] else client.messages

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
        #
        # Timed from before the first attempt to the final message: the
        # latency the ledger records is the caller's wall time, retries
        # included — what a deadline sees (spec §7.5.5).
        response = None
        started = _monotonic()
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                with api.stream(**call) as stream:
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
        duration = round(_monotonic() - started, 3)

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
        usage_obj = response.usage
        dearest_ttl = "1h" if "1h" in request["ttls"] else "5m"
        speed_used = getattr(usage_obj, "speed", None)
        speed_used = speed_used if isinstance(speed_used, str) else speed

        def _counts(u):
            """(input, output, cache read, 5m writes, 1h writes) of one
            usage. Writes come from the TTL split; whatever the split does
            not explain (an SDK without it) is billed at the dearest TTL
            the request used, never the cheaper one."""
            w5 = _tok(getattr(u, "cache_creation", None),
                      "ephemeral_5m_input_tokens")
            w1h = _tok(getattr(u, "cache_creation", None),
                       "ephemeral_1h_input_tokens")
            rest = _tok(u, "cache_creation_input_tokens") - (w5 + w1h)
            if rest > 0:
                if dearest_ttl == "1h":
                    w1h += rest
                else:
                    w5 += rest
            return (_tok(u, "input_tokens"), _tok(u, "output_tokens"),
                    _tok(u, "cache_read_input_tokens"), w5, w1h)

        # The model that answered: recorded only when the server may have
        # switched it (`fallbacks`). Otherwise the API's echo can be a
        # dated snapshot of the alias asked for, and booking that would
        # split one model's spend across two ledger names.
        served = model
        echoed = getattr(response, "model", None)
        if fallbacks is not None and isinstance(echoed, str) and echoed:
            served = echoed
        iterations = getattr(usage_obj, "iterations", None)
        if fallbacks is not None and isinstance(iterations, list) \
                and iterations:
            # usage.iterations is the per-attempt bill: each attempt at
            # its own model's price (a declined attempt at the model that
            # declined it, the rescue at the fallback's).
            input_tokens = output_tokens = cache_read = w5 = w1h = 0
            cost = 0.0
            for it in iterations:
                it_model = getattr(it, "model", None)
                it_model = it_model if isinstance(it_model, str) and \
                    it_model else model
                i, o, r, a, b = _counts(it)
                input_tokens += i
                output_tokens += o
                cache_read += r
                w5 += a
                w1h += b
                bill = dict(input_tokens=i, output_tokens=o, cache_read=r,
                            cache_write_5m=a, cache_write_1h=b,
                            speed=speed_used)
                if known_model(it_model):
                    cost += cost_usd(it_model, **bill)
                else:
                    # An attempt by a model the catalog does not price (a
                    # fallback it lacks, a dated id) is booked at the
                    # dearer of the asked model's card and the unknown-
                    # model card, never below either.
                    logger.warning(
                        "[claude] usage.iterations names %r, not in the "
                        "catalog: booked at the dearer of %s's card and "
                        "the unknown-model card", it_model, model)
                    cost += max(cost_usd(model, **bill),
                                cost_usd(it_model, **bill))
        else:
            # Today's two reads, untouched; then the cache's share.
            input_tokens = usage_obj.input_tokens
            output_tokens = usage_obj.output_tokens
            _, _, cache_read, w5, w1h = _counts(usage_obj)
            priced_as = served if known_model(served) else model
            cost = cost_usd(priced_as, input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            cache_read=cache_read, cache_write_5m=w5,
                            cache_write_1h=w1h, speed=speed_used)
        stop_reason = getattr(response, "stop_reason", None)
        usage = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": round(cost, 6),
            "model": served,
            "cache_read_input_tokens": cache_read,
            "cache_creation_input_tokens": w5 + w1h,
            "cache_write_5m_tokens": w5,
            "cache_write_1h_tokens": w1h,
            "stop_reason": stop_reason if isinstance(stop_reason, str)
            else None,
            "duration_seconds": duration,
        }
        prompt_summary = request["summary"]

        def _ledger(success: bool, summary: str, error: str = "",
                    unclaimed: bool = False):
            # `unclaimed`: a billed call no caller will ever write a row
            # for — the generation a refusal re-run replaces. A record=False
            # caller writes ONE row from the usage it gets back, and that
            # is the re-run's; this one is nobody's but the provider's.
            if not record and not unclaimed:
                return
            # The row that lets the backfill recognise a call the provider
            # already recorded, when the caller's own domain row predates
            # the call (research asks, position reviews). See
            # backfill_llm_ledger. With `fallbacks`, the model asked for
            # when another one answered.
            ref = {"source_ref": source_ref} if source_ref else {}
            if served != model:
                ref["asked_model"] = model
            # Fenced: a ledger hiccup must not kill the call it measures —
            # but it fails LOUDLY, because a quiet miss here is exactly the
            # under-reporting this write exists to end.
            try:
                from ai_agents.models import AgentTask
                AgentTask.objects.create(
                    agent=agent_name[:30],
                    provider="claude",
                    model=served,
                    prompt_summary=prompt_summary[:500],
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cache_read_tokens=cache_read,
                    cache_write_tokens=w5 + w1h,
                    cost_usd=usage["cost_usd"],
                    response_summary=summary[:500],
                    structured_output=ref,
                    success=success,
                    error=error[:1000],
                    duration_seconds=duration,
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
        if stop_reason == "max_tokens":
            logger.warning("Claude response truncated at max_tokens (%s, %s)",
                           model, bound)
        elif stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            declined = (f"Claude declined the request (model={model}, "
                        f"category={getattr(details, 'category', None)})")
            if client_refusal_rerun and model != REFUSAL_FALLBACK_MODEL:
                # The re-run writes the cached blocks afresh on another
                # model: priced at the dearest TTL the request used.
                write_x = (CACHE_WRITE_1H_X if "1h" in request["ttls"]
                           else CACHE_WRITE_5M_X if request["ttls"] else 1.0)
                held = _fallback_held(model, usage, line=line,
                                      write_x=write_x)
                if not held:
                    # The declined generation was billed — on the frontier
                    # tier at the platform's dearest rate on its largest
                    # prompt — and it lands in the ledger BEFORE the re-run,
                    # under the model that declined it, opt-out or not (see
                    # `unclaimed`). The re-run's row is written by whoever
                    # writes rows for this call, under the model that
                    # answers it.
                    _ledger(False, text, unclaimed=True,
                            error=f"{declined}; re-run on "
                                  f"{REFUSAL_FALLBACK_MODEL}")
                    logger.warning(
                        "[claude] %s declined the request (%s) — re-running "
                        "once on %s", model,
                        getattr(details, "category", None) or "no category",
                        REFUSAL_FALLBACK_MODEL)
                    # The SAME request on another model: every keyword as
                    # the caller gave it — max_tokens included, so an
                    # unset bound is sized again for the fallback model.
                    return self.complete(
                        system_prompt, user_message,
                        model=REFUSAL_FALLBACK_MODEL,
                        effort=effort, agent_name=agent_name,
                        record=record, source_ref=source_ref,
                        system_blocks=system_blocks, user_blocks=user_blocks,
                        shared_user_blocks=shared_user_blocks,
                        private_user_blocks=private_user_blocks,
                        turn_effort=turn_effort, output_schema=output_schema,
                        max_tokens=max_tokens, fallbacks=fallbacks,
                        line=line, client_refusal_rerun=client_refusal_rerun,
                        timeout_s=timeout_s, task_budget=task_budget,
                        speed=speed)
                declined += f"; not re-run on {REFUSAL_FALLBACK_MODEL}: {held}"
            _raise_billed(declined)
        if not text:
            _raise_billed(
                f"Claude returned no text (model={model}, "
                f"stop_reason={stop_reason})")

        _ledger(True, text)
        return text, usage

    def count_tokens(self, *, model: str, system_prompt: str = "",
                     system_blocks: list = None, user_message: str = "",
                     user_blocks: list = None,
                     shared_user_blocks: list = None,
                     private_user_blocks: list = None) -> int:
        """The input tokens of a request on `model`, from the API's free
        token-counting endpoint. Never ledgered (it costs nothing). The
        effort-only message carries no tokens and is left out; the two
        user turns are counted as they would be sent."""
        request = build_request(
            model=model, system_prompt=system_prompt,
            user_message=user_message, system_blocks=system_blocks,
            user_blocks=user_blocks, shared_user_blocks=shared_user_blocks,
            private_user_blocks=private_user_blocks)
        call = {"model": model, "messages": request["kwargs"]["messages"]}
        if request["kwargs"]["system"]:
            call["system"] = request["kwargs"]["system"]
        result = self._get_client().messages.count_tokens(**call)
        return int(result.input_tokens)
