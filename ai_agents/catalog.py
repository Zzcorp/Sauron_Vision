"""Model catalog — the single source of truth for which Claude models this
platform may use, what they cost, and which one each tier resolves to.

Why this exists: model ids were hardcoded in five places, drifted out of
date (a retired id 404s every call), and pricing lived in a dict that only
knew three models, so any override silently mis-billed. Everything now
resolves through here.

Resolution order for a tier (first hit wins):
  1. AIModelSetting DB row for that tier      (runtime, editable in the UI)
  2. AI_MODEL_FAST / _BALANCED / _DEEP / _FRONTIER env var (deploy-time)
  3. The tier default below                    (code)

Per-agent overrides use the same DB table with scope="agent". Effort
resolves through the same rows, first hit wins: the agent's row, the
agent's own default (AGENT_EFFORT_DEFAULTS), the tier's row, the tier's
default.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Effort levels the Claude API accepts, cheapest → most thorough.
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")

# WHERE EVERY NUMBER BELOW COMES FROM (PR O0a, 2026-10-15). A price is the
# one figure in the ledger that cannot be derived from anything else, so
# each is copied from Anthropic's own pages, read on PRICES_READ_ON:
#   * `pricing`, `cache_read`, `fast_pricing`, `long_context`: the pricing
#     page (PRICING_SOURCE) — base input/output, cache hits, fast mode,
#     and Haiku 5.5's prompt-length card.
#   * `min_cache_tokens`: the prompt-caching page (CACHE_SOURCE), the
#     minimum cacheable prompt length per model; a shorter prefix silently
#     caches nothing.
#   * cache WRITES are not stored per model: both pages price them as a
#     multiple of the base input price, 1.25x for the 5-minute TTL and 2x
#     for the 1-hour TTL (CACHE_WRITE_5M_X, CACHE_WRITE_1H_X).
#   * `default_effort`, `per_message_effort`, `task_budget`,
#     `server_fallback`: the bundled Claude API reference (model-migration
#     and prompt-caching notes, cached 2026-10-06; CAPABILITY_SOURCE).
#     The provider refuses a keyword a model does not take BEFORE the
#     call, instead of paying for a 400.
# Not modelled: the 1.1x `inference_geo: "us"` multiplier, because the
# platform never sends `inference_geo`. Nothing below is unsourced; a
# price that could not be read would be written as None and said here.
PRICING_SOURCE = "https://platform.claude.com/docs/en/about-claude/pricing"
CACHE_SOURCE = ("https://platform.claude.com/docs/en/build-with-claude/"
                "prompt-caching")
CAPABILITY_SOURCE = ("the bundled Claude API reference (model-migration.md, "
                     "prompt-caching.md), cached 2026-10-06")
PRICES_READ_ON = "2026-10-15"
CACHE_WRITE_5M_X = 1.25
CACHE_WRITE_1H_X = 2.0
# An unknown model's cache read, as a share of its (fallback) input price:
# the pricing page's general rule, "0.1x base input price".
CACHE_READ_FALLBACK_X = 0.1

# Current roster. `pricing` is USD per million tokens.
# `thinking` marks models where adaptive thinking is on by default, so
# max_tokens must leave room for reasoning as well as the answer.
# `cache_read` is USD per million cached tokens read; `server_fallback`
# names the `fallbacks` forms a model accepts ("both": "default" and the
# list; "default": the scalar only; None: no server-side fallback).
MODELS = {
    "claude-fable-5-1": {
        "label": "Claude Fable 5.1",
        "tier_hint": "frontier",
        "pricing": {"input": 10.0, "output": 50.0},
        "context": 1_000_000,
        "thinking": True,
        "effort": True,
        "cache_read": 0.25,
        "min_cache_tokens": 512,
        "default_effort": "high",
        "per_message_effort": True,
        # The reference lists task budgets on Fable 5.1 with "confirm at
        # launch"; the API's own 400 is the last word.
        "task_budget": True,
        "server_fallback": "both",
        "notes": "Anthropic's most capable widely released model. Thinking "
                 "is always on (the provider never sends a thinking "
                 "parameter), effort low..max, 2.5 times the deep tier's "
                 "Opus 5.5 price — the weekly imagination pass, never the "
                 "five-minute loop. A safety refusal comes back as "
                 "stop_reason=refusal and the provider re-runs the call on "
                 "Opus 5.",
    },
    "claude-opus-5-5": {
        "label": "Claude Opus 5.5",
        "tier_hint": "deep",
        "pricing": {"input": 4.0, "output": 20.0},
        "context": 1_000_000,
        "thinking": True,
        "effort": True,
        "cache_read": 0.20,
        "min_cache_tokens": 512,
        "default_effort": "medium",
        "per_message_effort": True,
        "task_budget": True,
        "server_fallback": "both",
        "fast_pricing": {"input": 8.0, "output": 40.0},
        "notes": "The current Opus, below Opus 5's price, and the deep "
                 "tier's default since 2026-11-01. Thinking cannot be "
                 "disabled (the provider never sends a thinking parameter); "
                 "effort low..max is the control, and its API default is "
                 "medium, so every deep agent sends its own (high). The "
                 "trade debate and the council answer on it.",
    },
    "claude-opus-5": {
        "label": "Claude Opus 5",
        "tier_hint": "deep",
        "pricing": {"input": 5.0, "output": 25.0},
        "context": 1_000_000,
        "thinking": True,
        "effort": True,
        "cache_read": 0.50,
        "min_cache_tokens": 512,
        "default_effort": "high",
        "per_message_effort": True,
        "task_budget": True,
        "server_fallback": "both",
        "fast_pricing": {"input": 10.0, "output": 50.0},
        "notes": "Previous-generation Opus: the deep tier's default until "
                 "2026-11-01, and still the provider's refusal re-run "
                 "(REFUSAL_FALLBACK_MODEL). Thinking on by default, API "
                 "effort default high.",
    },
    "claude-opus-4-8": {
        "label": "Claude Opus 4.8",
        "tier_hint": "deep",
        "pricing": {"input": 5.0, "output": 25.0},
        "context": 1_000_000,
        "thinking": True,
        "effort": True,
        "cache_read": 0.50,
        "min_cache_tokens": 1024,
        "default_effort": "high",
        "per_message_effort": False,
        "task_budget": True,
        "server_fallback": None,
        "fast_pricing": {"input": 10.0, "output": 50.0},
        "notes": "Previous-generation Opus; solid fallback.",
    },
    "claude-sonnet-5": {
        "label": "Claude Sonnet 5",
        "tier_hint": "balanced",
        # $2/$10, NOT $3/$15 — that is Sonnet 4.6's rate, twenty lines down,
        # and it was copied up here when this entry was added. Every balanced
        # tier call is the workhorse of this platform, so the error was not
        # academic: cost_usd on each of those AgentTask rows read 50% high,
        # spend.spent_today() inherited it, and AI_DAILY_BUDGET_USD therefore
        # stopped work at roughly two thirds of the money the operator had
        # actually authorised. The ledger exists to be believed; a price is
        # the one number in it that cannot be derived from anything else.
        "pricing": {"input": 2.0, "output": 10.0},
        "context": 1_000_000,
        "thinking": True,
        "effort": True,
        "cache_read": 0.20,
        "min_cache_tokens": 1024,
        "default_effort": "high",
        "per_message_effort": False,
        "task_budget": False,
        "server_fallback": None,
        "notes": "Previous-generation Sonnet: the balanced tier's default "
                 "until 2026-11-01. Thinking on by default, API effort "
                 "default high.",
    },
    "claude-sonnet-5-5": {
        "label": "Claude Sonnet 5.5",
        "tier_hint": "balanced",
        "pricing": {"input": 2.0, "output": 10.0},
        "context": 1_000_000,
        "thinking": True,
        "effort": True,
        # $0.10, not the $0.20 of Sonnet 5 and Opus 5.5: the pricing page
        # prices Opus 5.5 and Sonnet 5.5 cache hits at 0.05x their base
        # input price (footnote 2), and $2 x 0.05 is $0.10.
        "cache_read": 0.10,
        "min_cache_tokens": 512,
        "default_effort": "high",
        "per_message_effort": True,
        "task_budget": True,
        # Only the "default" form of `fallbacks`, and only on the Claude
        # API (the reference); the list form is a 400 here.
        "server_fallback": "default",
        "notes": "The current Sonnet ($2/$10, cache reads $0.10) and the "
                 "balanced tier's default since 2026-11-01. Thinking is on "
                 "by default and the provider never sends a thinking "
                 "parameter ({type: disabled} is a 400 here); effort "
                 "low..max, default high, levels recalibrated from Sonnet "
                 "5. The Orcs' r0 and r1 rungs.",
    },
    "claude-sonnet-4-6": {
        "label": "Claude Sonnet 4.6",
        "tier_hint": "balanced",
        "pricing": {"input": 3.0, "output": 15.0},
        "context": 1_000_000,
        "thinking": True,
        "effort": True,
        "cache_read": 0.30,
        "min_cache_tokens": 1024,
        "default_effort": "high",
        "per_message_effort": False,
        "task_budget": False,
        "server_fallback": None,
        "notes": "Previous-generation Sonnet.",
    },
    # Older-but-live models: still valid deploy-time pins, so they must be
    # in the catalog or _validated would discard a deliberate choice with a
    # misleading "retired" warning.
    "claude-opus-4-7": {
        "label": "Claude Opus 4.7",
        "tier_hint": "deep",
        "pricing": {"input": 5.0, "output": 25.0},
        "context": 1_000_000,
        "thinking": True,
        "effort": True,
        "cache_read": 0.50,
        "min_cache_tokens": 2048,
        "default_effort": "high",
        "per_message_effort": False,
        "task_budget": True,
        "server_fallback": None,
        "notes": "Older Opus; still served.",
    },
    "claude-opus-4-6": {
        "label": "Claude Opus 4.6",
        "tier_hint": "deep",
        "pricing": {"input": 5.0, "output": 25.0},
        "context": 1_000_000,
        "thinking": True,
        "effort": True,
        "cache_read": 0.50,
        "min_cache_tokens": 4096,
        "default_effort": "high",
        "per_message_effort": False,
        "task_budget": False,
        "server_fallback": None,
        "notes": "Older Opus; adaptive thinking must be set explicitly.",
    },
    # RETIRING. Deprecated 2026-09-30, it retires on 2026-11-30, and from
    # that day a pin to it would 404 on every call. No tier defaults to
    # it. The row stays until then because a pin to it is a served model
    # today and a saved override may name it; remove it before the date,
    # and _validated then refuses such a pin and falls back to the tier.
    "claude-sonnet-4-5": {
        "label": "Claude Sonnet 4.5 (retires 2026-11-30)",
        "retires": "2026-11-30",
        "tier_hint": "balanced",
        "pricing": {"input": 3.0, "output": 15.0},
        "context": 1_000_000,
        "thinking": False,
        "effort": False,
        "cache_read": 0.30,
        "min_cache_tokens": 1024,
        "default_effort": None,
        "per_message_effort": False,
        "task_budget": False,
        "server_fallback": None,
        "notes": "Legacy Sonnet; no effort parameter. Retires 2026-11-30; "
                 "Anthropic names claude-sonnet-5-5 as its replacement.",
    },
    "claude-haiku-5-5": {
        "label": "Claude Haiku 5.5",
        "tier_hint": "fast",
        "pricing": {"input": 0.10, "output": 0.50},
        "context": 1_000_000,
        "thinking": True,
        "effort": True,
        "cache_read": 0.01,
        "min_cache_tokens": 512,
        "default_effort": "medium",
        "per_message_effort": True,
        "task_budget": True,
        # Refusals have no server-side fallback on Haiku 5.5.
        "server_fallback": None,
        # Priced by prompt length: a request whose prompt (input + cache
        # reads + cache writes) is over 100,000 tokens pays this card for
        # ALL of its tokens (pricing page, "Long context pricing").
        "long_context": {"above_prompt_tokens": 100_000,
                         "input": 0.50, "output": 2.50, "cache_read": 0.05},
        "notes": "The current Haiku and the fast tier's default since "
                 "2026-11-01: $0.10/$0.50 up to 100K prompt tokens, "
                 "$0.50/$2.50 beyond; cache reads $0.01. Thinking on by "
                 "default (billed as output), effort default medium; the "
                 "fast tier sends low. Its tokenizer counts about 30% more "
                 "tokens than Haiku 4.5's on the same text. No server-side "
                 "refusal fallback: a decline re-runs once on Opus 5 when "
                 "the deep reserve allows it.",
    },
    "claude-haiku-4-5": {
        "label": "Claude Haiku 4.5",
        "tier_hint": "fast",
        "pricing": {"input": 1.0, "output": 5.0},
        "context": 200_000,
        "thinking": False,
        "effort": False,
        "cache_read": 0.10,
        "min_cache_tokens": 4096,
        "default_effort": None,
        "per_message_effort": False,
        "task_budget": False,
        "server_fallback": None,
        "notes": "Previous-generation Haiku: the fast tier's default until "
                 "2026-11-01. No thinking and no effort parameter.",
    },
    "claude-haiku-4-5-20251001": {
        "label": "Claude Haiku 4.5 (pinned)",
        "tier_hint": "fast",
        "pricing": {"input": 1.0, "output": 5.0},
        "context": 200_000,
        "thinking": False,
        "effort": False,
        "cache_read": 0.10,
        "min_cache_tokens": 4096,
        "default_effort": None,
        "per_message_effort": False,
        "task_budget": False,
        "server_fallback": None,
        "notes": "Date-pinned Haiku 4.5 — same model, frozen id. "
                 "Previous-generation: settings.py's fast default until "
                 "2026-11-01.",
    },
}

# Tier → model when nothing overrides it. The current generation since
# 2026-11-01 (the operator's decision of 2026-10-31): Haiku 4.5, Sonnet 5
# and Opus 5 before it. Each successor is the same tier, better, and costs
# the same or less per token; the three it replaced stay in MODELS above,
# so a saved override or an AI_MODEL_* value naming one still runs.
# config/settings.py's AI_MODEL_* defaults name the same three ids.
TIER_DEFAULTS = {
    "fast": "claude-haiku-5-5",
    "balanced": "claude-sonnet-5-5",
    "deep": "claude-opus-5-5",
    # The frontier tier exists for the few calls where imagination is the
    # product — the weekly strategy generator — and nowhere the platform
    # calls every five minutes. It shares the deep tier's budget reserve.
    "frontier": "claude-fable-5-1",
}

TIERS = ("fast", "balanced", "deep", "frontier")

# Default effort per tier for models that support it. Cheap tiers stay
# cheap; the deep tier is where thoroughness is worth paying for.
TIER_EFFORT_DEFAULTS = {
    "fast": "low",
    "balanced": "medium",
    "deep": "high",
    "frontier": "high",
}

# An agent's own default effort, read after the agent's own row on
# /ai-models/ and before its tier's row (resolve_effort). These ten call
# the provider directly and sent no effort until 2026-10-31, so they ran
# at their model's API default, high, whatever /ai-models/ held: a tier's
# effort row never reached them. The balanced tier's "medium" would have
# cut the four balanced ones the day they started sending one, and a tier
# row saved earlier for the BaseAgent agents would have moved all ten,
# down or up. Only a row saved for the agent itself moves it.
#
# The tiers moved on 2026-11-01 and these did not: each keeps the effort
# it ran at on the old model. On the deep tier that matters most: Opus
# 5.5's API default is medium, a level below Opus 5's high.
AGENT_EFFORT_DEFAULTS = {
    # balanced: Sonnet 5's API default, kept on Sonnet 5.5
    "position_reviewer": "high",
    "close_advisor": "high",
    "daily_briefing": "high",
    "monday_plan": "high",
    # deep: Opus 5's API default, kept on Opus 5.5 (whose default is
    # medium); their tier's default is high too
    "sauron_mind": "high",
    "critic": "high",
    "strategist": "high",
    "earnings_reviewer": "high",
    "research": "high",
    # frontier, Fable 5.1's default; its tier's default is high too
    "strategy_generator": "high",
}


def known_model(model_id: str) -> bool:
    return model_id in MODELS


def pricing_for(model_id: str) -> dict:
    """USD per million tokens. Unknown models fall back to Sonnet rates so
    cost tracking degrades to an estimate instead of reporting zero."""
    entry = MODELS.get(model_id)
    if entry:
        return entry["pricing"]
    return {"input": 3.0, "output": 15.0}


def supports_effort(model_id: str) -> bool:
    return bool(MODELS.get(model_id, {}).get("effort"))


def supports_thinking(model_id: str) -> bool:
    """True when adaptive thinking is on by default, so max_tokens must
    cover reasoning as well as the answer."""
    return bool(MODELS.get(model_id, {}).get("thinking"))


def cache_pricing_for(model_id: str) -> dict:
    """USD per million tokens for the cache: {"read", "write_5m",
    "write_1h"}. The writes are the base input price times the TTL's
    multiplier; an unknown model reads at 0.1x and writes at 1.25x / 2x
    of the $3 fallback, so a cached call is never booked at zero.

    Kept apart from pricing_for(), whose {"input", "output"} shape four
    suites compare whole and every caller of today reads."""
    entry = MODELS.get(model_id)
    base = pricing_for(model_id)["input"]
    read = (entry["cache_read"] if entry and entry.get("cache_read") is not None
            else base * CACHE_READ_FALLBACK_X)
    return {"read": read,
            "write_5m": base * CACHE_WRITE_5M_X,
            "write_1h": base * CACHE_WRITE_1H_X}


def fast_pricing_for(model_id: str) -> dict | None:
    """Fast mode's {"input", "output"}, or None where it does not exist."""
    return MODELS.get(model_id, {}).get("fast_pricing")


def cost_usd(model_id: str, *, input_tokens: int, output_tokens: int,
             cache_read: int = 0, cache_write_5m: int = 0,
             cache_write_1h: int = 0, speed: str | None = None) -> float:
    """What one request costs, in USD, at the catalog's prices.

    With every cache counter at 0 (and no fast mode, no long prompt) this
    is (input x p_in + output x p_out) / 1e6 computed in exactly the order
    the provider always computed it, so a call that caches nothing books
    the same float it booked before PR O0a. The cache terms are added only
    when nonzero.

    `speed="fast"` prices at the model's fast card, with the caching
    multipliers on top of it (the pricing page: "Prompt caching
    multipliers apply on top of fast mode pricing"). A long prompt on
    Haiku 5.5 (input + cache reads + cache writes over 100,000 tokens)
    prices the WHOLE request at its long-context card."""
    p = pricing_for(model_id)
    p_in, p_out = p["input"], p["output"]
    read_price = cache_pricing_for(model_id)["read"]
    entry = MODELS.get(model_id, {})
    fast = entry.get("fast_pricing") if speed == "fast" else None
    if fast:
        read_price = fast["input"] * (read_price / p_in)
        p_in, p_out = fast["input"], fast["output"]
    long_card = entry.get("long_context")
    if long_card and (input_tokens + cache_read + cache_write_5m
                      + cache_write_1h) > long_card["above_prompt_tokens"]:
        p_in, p_out = long_card["input"], long_card["output"]
        read_price = long_card["cache_read"]
    cost = input_tokens * p_in + output_tokens * p_out
    if cache_read:
        cost += cache_read * read_price
    if cache_write_5m:
        cost += cache_write_5m * p_in * CACHE_WRITE_5M_X
    if cache_write_1h:
        cost += cache_write_1h * p_in * CACHE_WRITE_1H_X
    return cost / 1_000_000


def min_cache_tokens(model_id: str) -> int | None:
    """The shortest prefix the model will cache; shorter caches nothing."""
    return MODELS.get(model_id, {}).get("min_cache_tokens")


def default_effort(model_id: str) -> str | None:
    """The effort the API applies when none is sent (None: no effort)."""
    return MODELS.get(model_id, {}).get("default_effort")


def supports_per_message_effort(model_id: str) -> bool:
    """The effort-only system message (beta) — an effort change between
    turns that keeps the prompt cache (spec §5.2a)."""
    return bool(MODELS.get(model_id, {}).get("per_message_effort"))


def supports_task_budget(model_id: str) -> bool:
    return bool(MODELS.get(model_id, {}).get("task_budget"))


def server_fallback(model_id: str) -> str | None:
    """"both", "default" or None: the `fallbacks` forms the model takes."""
    return MODELS.get(model_id, {}).get("server_fallback")


# The provider smoke's models (ai_agents/management/commands/claude_smoke.py):
# the three the Orcs' ladder routes to, and Fable 5.1 on request.
SMOKE_MODELS = ("claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5")
SMOKE_OPTIONAL = ("claude-fable-5-1",)

# The Orcs' routing ladder, table v1 (spec §7.5.4). DISPLAY ONLY in O0:
# /ai-models/ shows it so the operator sees which ids the Orcs will pin.
# The router (O2) reads its own versioned copy and never the tier
# resolver, so no tier setting on that page ever moves it, and until each
# band boundary has two completed probe blocks it is an unvalidated prior.
ORC_LADDER_V1 = (
    {"rung": "h0", "model": "claude-haiku-5-5", "effort": "low",
     "note": "a paper probe only; never decides"},
    {"rung": "r0", "model": "claude-sonnet-5-5", "effort": "low",
     "note": "routine"},
    {"rung": "r1", "model": "claude-sonnet-5-5", "effort": "high",
     "note": "paper material; real money only for questions"},
    {"rung": "r2", "model": "claude-opus-5-5", "effort": "medium",
     "note": "real-money material"},
    {"rung": "r3", "model": "claude-opus-5-5", "effort": "high",
     "note": "complex"},
    {"rung": "r4", "model": "claude-opus-5-5", "effort": "xhigh",
     "note": "extreme when the Fable gate fails; Fable's blind twin"},
    {"rung": "r5", "model": "claude-fable-5-1", "effort": "max",
     "note": "extreme, gate passes; real money only, under a quota"},
)


def choices() -> list[tuple[str, str]]:
    """(id, label) pairs for form/select rendering."""
    return [(mid, m["label"]) for mid, m in MODELS.items()]


def _validated(model_id: str, tier: str, source: str) -> str | None:
    """Accept a configured id only if the catalog knows it.

    A stale env var or DB row pointing at a retired model (e.g. a pinned
    `claude-sonnet-4-*`) would otherwise 404 on every single call, silently
    disabling that tier. Falling back to the current default keeps the
    platform working and logs loudly instead.
    """
    if not model_id:
        return None
    if known_model(model_id):
        return model_id
    logger.warning(
        "AI model %r configured for %s tier via %s is not in the catalog "
        "(retired or misspelled?) — falling back to %s",
        model_id, tier, source, TIER_DEFAULTS[tier])
    return None


def resolve_tier(tier: str) -> str:
    """Model id for a tier, honouring DB settings then env then defaults."""
    from django.conf import settings

    tier = tier if tier in TIERS else "balanced"
    try:
        from ai_agents.models import AIModelSetting
        row = AIModelSetting.objects.filter(scope="tier", key=tier).first()
        if row and row.model_id:
            chosen = _validated(row.model_id, tier, "the model-selection UI")
            if chosen:
                return chosen
    except Exception:
        pass  # table may not exist yet (migrations), or DB unavailable
    env_model = settings.AI_CONFIG.get("models", {}).get(tier)
    return _validated(env_model, tier, "an AI_MODEL_* env var") \
        or TIER_DEFAULTS[tier]


def resolve_agent(agent_name: str, tier: str) -> str:
    """Model id for a named agent: per-agent override, else its tier."""
    if agent_name:
        try:
            from ai_agents.models import AIModelSetting
            row = AIModelSetting.objects.filter(
                scope="agent", key=agent_name).first()
            if row and row.model_id:
                chosen = _validated(row.model_id, tier if tier in TIERS
                                     else "balanced", f"agent {agent_name}")
                if chosen:
                    return chosen
        except Exception:
            pass
    return resolve_tier(tier)


def resolve_effort(model_id: str, tier: str, agent_name: str = "") -> str | None:
    """Effort level for a call, or None when the model doesn't support it.

    First hit wins: the agent's DB row, the agent's own default
    (AGENT_EFFORT_DEFAULTS), the tier's DB row, the tier's default. An
    agent with its own default therefore moves only by its own row."""
    if not supports_effort(model_id):
        return None
    return (_effort_row("agent", agent_name)
            or AGENT_EFFORT_DEFAULTS.get(agent_name)
            or _effort_row("tier", tier)
            or TIER_EFFORT_DEFAULTS.get(tier, "medium"))


def _effort_row(scope: str, key: str) -> str:
    """The effort saved on /ai-models/ for (scope, key), or ""."""
    if not key:
        return ""
    try:
        from ai_agents.models import AIModelSetting
        row = AIModelSetting.objects.filter(scope=scope, key=key).first()
        return (row.effort if row else "") or ""
    except Exception:
        return ""   # table may not exist yet (migrations), or DB unavailable
