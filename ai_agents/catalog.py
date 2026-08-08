"""Model catalog — the single source of truth for which Claude models this
platform may use, what they cost, and which one each tier resolves to.

Why this exists: model ids were hardcoded in five places, drifted out of
date (a retired id 404s every call), and pricing lived in a dict that only
knew three models, so any override silently mis-billed. Everything now
resolves through here.

Resolution order for a tier (first hit wins):
  1. AIModelSetting DB row for that tier      (runtime, editable in the UI)
  2. AI_MODEL_FAST / _BALANCED / _DEEP env var (deploy-time)
  3. The tier default below                    (code)

Per-agent overrides use the same DB table with scope="agent".
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Effort levels the Claude API accepts, cheapest → most thorough.
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")

# Current roster. `pricing` is USD per million tokens.
# `thinking` marks models where adaptive thinking is on by default, so
# max_tokens must leave room for reasoning as well as the answer.
MODELS = {
    "claude-opus-5": {
        "label": "Claude Opus 5",
        "tier_hint": "deep",
        "pricing": {"input": 5.0, "output": 25.0},
        "context": 1_000_000,
        "thinking": True,
        "effort": True,
        "notes": "Strongest agentic/coding model. Thinking on by default.",
    },
    "claude-opus-4-8": {
        "label": "Claude Opus 4.8",
        "tier_hint": "deep",
        "pricing": {"input": 5.0, "output": 25.0},
        "context": 1_000_000,
        "thinking": True,
        "effort": True,
        "notes": "Previous-generation Opus; solid fallback.",
    },
    "claude-sonnet-5": {
        "label": "Claude Sonnet 5",
        "tier_hint": "balanced",
        "pricing": {"input": 3.0, "output": 15.0},
        "context": 1_000_000,
        "thinking": True,
        "effort": True,
        "notes": "Near-Opus quality at Sonnet cost. Good default workhorse.",
    },
    "claude-sonnet-4-6": {
        "label": "Claude Sonnet 4.6",
        "tier_hint": "balanced",
        "pricing": {"input": 3.0, "output": 15.0},
        "context": 1_000_000,
        "thinking": True,
        "effort": True,
        "notes": "Previous-generation Sonnet.",
    },
    "claude-haiku-4-5": {
        "label": "Claude Haiku 4.5",
        "tier_hint": "fast",
        "pricing": {"input": 1.0, "output": 5.0},
        "context": 200_000,
        "thinking": False,
        "effort": False,
        "notes": "Cheapest + fastest. Classification, short prose, journals.",
    },
    "claude-haiku-4-5-20251001": {
        "label": "Claude Haiku 4.5 (pinned)",
        "tier_hint": "fast",
        "pricing": {"input": 1.0, "output": 5.0},
        "context": 200_000,
        "thinking": False,
        "effort": False,
        "notes": "Date-pinned Haiku 4.5 — same model, frozen id.",
    },
}

# Tier → model when nothing overrides it.
TIER_DEFAULTS = {
    "fast": "claude-haiku-4-5",
    "balanced": "claude-sonnet-5",
    "deep": "claude-opus-5",
}

TIERS = ("fast", "balanced", "deep")

# Default effort per tier for models that support it. Cheap tiers stay
# cheap; the deep tier is where thoroughness is worth paying for.
TIER_EFFORT_DEFAULTS = {
    "fast": "low",
    "balanced": "medium",
    "deep": "high",
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
    """Effort level for a call, or None when the model doesn't support it."""
    if not supports_effort(model_id):
        return None
    for scope, key in (("agent", agent_name), ("tier", tier)):
        if not key:
            continue
        try:
            from ai_agents.models import AIModelSetting
            row = AIModelSetting.objects.filter(scope=scope, key=key).first()
            if row and row.effort:
                return row.effort
        except Exception:
            pass
    return TIER_EFFORT_DEFAULTS.get(tier, "medium")
