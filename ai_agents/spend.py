"""A hard daily ceiling on LLM spend.

The brain runs synthesis, a critic, a strategist, a generator, an earnings
reviewer and an anomaly scanner on schedules, each calling a frontier
model. That is the largest recurring variable cost in the platform and the
least validated component — it can quietly become the dominant expense of
running a system whose trading edge is not yet measured.

`AgentTask` already records `cost_usd` per call, so the budget is computed
from real spend rather than an estimate. Agents check `can_spend()` before
calling out and skip cleanly when the day's budget is gone: a skipped
briefing is an inconvenience, an unbounded bill is not.

Set AI_DAILY_BUDGET_USD=0 to disable the ceiling entirely.

TWO LINES, ONE TOTAL (PR O0a, 2026-10-15; the Orcs spec §7.1). The Orcs —
one trader agent per open position, from O2 — get a line of their own so
they can neither starve the brain nor be starved by it:

  * AI_DAILY_BUDGET_USD stays the TOTAL: no call on either line once the
    whole ledger's spend today reaches it. At 0 there is no total and the
    core line has no ceiling; the Orcs' cap still binds.
  * The ORCS line is a cap, ORC_DAILY_BUDGET_USD (0 = the line is off,
    which it is until O2 turns it on). It counts the rows of agents `orc`,
    `captain`, `orc_*` and `captain_*`, and any row whose source_ref starts
    with `Orc:` or `Captain:` (how the debate of an Orc's add is billed to
    the Orcs, through BaseAgent.run(source_ref=)).
  * The CORE line is everything else. Its allowance is the total minus
    what the Orcs have ACTUALLY spent today minus a floor kept for their
    live urgent and confirm wakes (ORC_LIVE_FLOOR_USD), never minus their
    cap: on a calm Orc day the brain may spend what the Orcs did not.
    While the Orcs' line is off there is no floor and the core line IS the
    whole ledger, read by today's single query.
  * DEEP_TIER_SHARE applies inside each line against that line's live
    allowance; inside the Orcs' line a caller may exempt a live urgent or
    confirm wake from it (`deep_share_exempt`, decision D30).

Every function keeps today's answer when no line is passed: the default
line is "core", and with the Orcs' line off the core line is today's
budget, word for word (tests/test_ai_spend_lines.py).
"""
from __future__ import annotations

import logging
import os

from django.utils import timezone

logger = logging.getLogger(__name__)

# 15, not the original 5 — and the two changes travel together. The ledger
# this budget reads used to miss every direct-provider caller (all seven
# brain modules), so "5" was really governing about half of true spend: the
# Anthropic console read ~2x what /ai-models/ admitted to. With the ledger
# complete, a 5 would suddenly halt the platform's cognition mid-afternoon
# — not a policy anyone chose, just yesterday's blind spot becoming today's
# throttle. 15 covers the measured full burn (~4/day) with honest headroom;
# the env var remains the operator's knob. Read at IMPORT: a changed value
# binds only once the containers are recreated (`./deploy/dc up -d`).
DEFAULT_DAILY_BUDGET_USD = float(os.getenv("AI_DAILY_BUDGET_USD", "15.0"))


def _env_usd(name: str, default: float) -> float:
    """A USD amount from the environment; `default` when it is unset,
    blank or unreadable. Every AI caller imports this module before it
    spends, so a typo in a variable that changes nothing until O2 must not
    stop the import: it leaves the line at its default, said loudly."""
    raw = os.getenv(name, "")
    if not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        logger.error("[spend] %s=%r is not a number: using %s", name, raw,
                     default)
        return default


# The Orcs' cap. 0 = their line is off: no Orc call is allowed, the core
# line is the whole ledger, and no floor is held back. O2 turns it on.
DEFAULT_ORC_DAILY_BUDGET_USD = _env_usd("ORC_DAILY_BUDGET_USD", 0.0)
# Held back from the core line, while the Orcs' line is on, for the Orcs'
# live urgent and confirm wakes (spec §7.1, §10.6).
ORC_LIVE_FLOOR_USD = 3.00
# Reserve a slice for the cheap, operationally useful agents (journals,
# pre-trade checks) so an expensive deep-tier run can't consume the lot.
DEEP_TIER_SHARE = 0.7

LINES = ("core", "orcs")
# Not a line: the whole ledger, for the total stop and the readouts.
TOTAL = "total"

# The Orcs' line, by agent name or by source_ref. Stricter than "starts
# with orc": a future `orchestra_*` agent must not land on the Orcs' line.
ORC_AGENTS = ("orc", "captain")
ORC_AGENT_PREFIXES = ("orc_", "captain_")
ORC_SOURCE_PREFIXES = ("Orc:", "Captain:")

_LINE_LABEL = {"core": "core AI", "orcs": "Orcs"}


class BudgetRefused(RuntimeError):
    """Raised by BaseAgent.run when the day's total is spent: nothing was
    sent and nothing was billed, so no ledger row is written."""


def _check_line(line: str, *, allow_total: bool = False) -> None:
    if line in LINES or (allow_total and line == TOTAL):
        return
    raise ValueError(f"unknown budget line {line!r} (one of {LINES})")


def _configured(key: str, default: float) -> float:
    from django.conf import settings
    configured = getattr(settings, "AI_CONFIG", {}).get(key)
    if configured is not None:
        try:
            return float(configured)
        except (TypeError, ValueError):
            pass
    return default


def orc_line_cap() -> float:
    """The Orcs' daily cap in USD; 0 when their line is off."""
    return max(0.0, _configured("orc_daily_budget_usd",
                                DEFAULT_ORC_DAILY_BUDGET_USD))


def orc_line_q():
    """The Orcs' rows, as a POSITIVE filter. The core line is computed as
    the whole ledger minus this, never as its negation: a negated JSON key
    lookup would also drop every row that has no source_ref at all."""
    from django.db.models import Q
    q = Q(agent__in=ORC_AGENTS)
    for prefix in ORC_AGENT_PREFIXES:
        q |= Q(agent__startswith=prefix)
    for prefix in ORC_SOURCE_PREFIXES:
        q |= Q(structured_output__source_ref__startswith=prefix)
    return q


def _today():
    from ai_agents.models import AgentTask
    start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return AgentTask.objects.filter(created_at__gte=start)


def _spent_split() -> tuple:
    """(the whole ledger today, the Orcs' share of it), one query."""
    from django.db.models import Sum
    agg = _today().aggregate(all=Sum("cost_usd"),
                             orcs=Sum("cost_usd", filter=orc_line_q()))
    return float(agg["all"] or 0), float(agg["orcs"] or 0)


def daily_budget(line: str = "core") -> float:
    """The day's allowance of `line` ("core", "orcs") or of the "total".

    With the Orcs' line off, "core" is the total — today's number."""
    _check_line(line, allow_total=True)
    total = _configured("daily_budget_usd", DEFAULT_DAILY_BUDGET_USD)
    if line == TOTAL:
        return total
    cap = orc_line_cap()
    if line == "orcs":
        return cap
    if cap <= 0 or total <= 0:
        return total
    return max(0.0, total - spent_today("orcs") - ORC_LIVE_FLOOR_USD)


def spent_today(line: str = "core") -> float:
    """Actual USD spent today on `line` (or the "total"), from the ledger.

    With the Orcs' line off, "core" runs today's single aggregate over the
    whole ledger."""
    _check_line(line, allow_total=True)
    from django.db.models import Sum
    if line == "orcs":
        total = _today().filter(orc_line_q()).aggregate(
            s=Sum("cost_usd"))["s"]
        return float(total or 0)
    if line == "core" and orc_line_cap() > 0:
        spent_all, spent_orcs = _spent_split()
        return max(0.0, spent_all - spent_orcs)
    total = _today().aggregate(s=Sum("cost_usd"))["s"]
    return float(total or 0)


def remaining_today(line: str = "core") -> float:
    """What `line` may still spend today; inf when no ceiling is set.

    The Orcs' line always has one, its cap: with no total ceiling it is
    what is left of the cap (0 while the line is off), never inf."""
    _check_line(line, allow_total=True)
    total = daily_budget(TOTAL)
    if total <= 0:
        if line == "orcs":
            return max(0.0, orc_line_cap() - spent_today("orcs"))
        return float("inf")
    if line == TOTAL or (line == "core" and orc_line_cap() <= 0):
        return max(0.0, daily_budget(line) - spent_today(line))
    left_total = max(0.0, total - spent_today(TOTAL))
    return max(0.0, min(daily_budget(line) - spent_today(line), left_total))


def can_spend(*, tier: str = "balanced", estimated_usd: float = 0.05,
              line: str = "core", total_only: bool = False,
              deep_share_exempt: bool = False) -> tuple:
    """(allowed, reason) — may an agent on `tier` make a call now?

    `line`: the budget line the call is billed to ("core" by default).
    `total_only`: ask only whether the day's TOTAL is spent (BaseAgent.run:
    no deep share, no estimate, never refused earlier than the total).
    `deep_share_exempt`: on the Orcs' line, the 70% deep share does not
    refuse this call (a live urgent or confirm wake, D30); it means
    nothing on the core line.

    With no line passed and the Orcs' line off, the answers and their
    words are today's, read from one query.

    AI_DAILY_BUDGET_USD=0 lifts the TOTAL only. The Orcs' line is a cap
    whatever the total (spec §7.1): off, it refuses every Orc call; on,
    it binds at ORC_DAILY_BUDGET_USD with no total above it."""
    _check_line(line)
    total = daily_budget(TOTAL)
    cap = orc_line_cap()
    if line == "orcs" and not total_only and cap <= 0:
        return False, "the Orcs line is off (ORC_DAILY_BUDGET_USD=0)"
    no_total = total <= 0
    if no_total and (line == "core" or total_only):
        return True, "no budget configured"

    # Past here with no total, the line is the Orcs' and it is on.
    if cap <= 0:
        spent_all, spent_orcs = spent_today(TOTAL), 0.0
    else:
        spent_all, spent_orcs = _spent_split()

    if not no_total and total - spent_all <= 0:
        return False, (f"daily AI budget spent (${spent_all:.2f} of "
                       f"${total:.2f})")
    if total_only:
        return True, f"${total - spent_all:.2f} of ${total:.2f} remaining"

    if line == "orcs":
        budget, spent = cap, spent_orcs
    elif cap <= 0:
        budget, spent = total, spent_all
    else:
        budget = max(0.0, total - spent_orcs - ORC_LIVE_FLOOR_USD)
        spent = max(0.0, spent_all - spent_orcs)
    remaining = (budget - spent if no_total
                 else min(budget - spent, total - spent_all))
    if remaining <= 0:
        why = (f"the {_LINE_LABEL[line]} line is spent (${spent:.2f} of "
               f"${budget:.2f}")
        if line == "core":
            why += (f"; the Orcs spent ${spent_orcs:.2f} and "
                    f"${ORC_LIVE_FLOOR_USD:.2f} is held for their live wakes")
        return False, why + ")"

    # Deep-tier work is the expensive kind; hold back a slice of the line's
    # live allowance so the cheap operational agents still run late in
    # the day.
    exempt = deep_share_exempt and line == "orcs"
    if (tier in ("deep", "frontier") and not exempt
            and spent > budget * DEEP_TIER_SHARE):
        return False, (f"deep-tier reserve reached (${spent:.2f} of "
                       f"${budget:.2f}; deep tier capped at "
                       f"{DEEP_TIER_SHARE:.0%})")
    if estimated_usd > remaining:
        return False, (f"call would exceed the daily budget "
                       f"(${remaining:.2f} left)")
    return True, f"${remaining:.2f} of ${budget:.2f} remaining"


def guard(tier: str = "balanced", estimated_usd: float = 0.05,
          line: str = "core"):
    """Decorator: skip an agent task when the day's budget is exhausted."""
    def decorator(fn):
        from functools import wraps

        @wraps(fn)
        def wrapper(*args, **kwargs):
            allowed, reason = can_spend(tier=tier, estimated_usd=estimated_usd,
                                        line=line)
            if not allowed:
                logger.warning("[spend] skipping %s — %s", fn.__name__, reason)
                return {"status": "skipped", "reason": reason}
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def lines_summary() -> dict:
    """Both lines and the total for /ai-models/, from one ledger query."""
    total = daily_budget(TOTAL)
    cap = orc_line_cap()
    spent_all, spent_orcs = _spent_split()
    on = cap > 0
    if on and total > 0:
        core_budget = max(0.0, total - spent_orcs - ORC_LIVE_FLOOR_USD)
        core_spent = max(0.0, spent_all - spent_orcs)
        formula = (f"= ${total:.2f} − Orcs spent − ${ORC_LIVE_FLOOR_USD:.2f} "
                   f"floor")
    else:
        core_budget, core_spent = total, spent_all
        formula = "= the total (the Orcs line is off)"
    return {
        "no_ceiling": total <= 0,
        "total": total,
        "spent_total": round(spent_all, 4),
        "remaining_total": (None if total <= 0
                            else round(max(0.0, total - spent_all), 4)),
        "orcs_enabled": on,
        "orcs_cap": cap,
        "orcs_spent": round(spent_orcs, 4),
        "orcs_remaining": round(max(0.0, cap - spent_orcs), 4),
        "core_budget": round(core_budget, 4),
        "core_spent": round(core_spent, 4),
        "core_formula": formula,
        "floor": ORC_LIVE_FLOOR_USD,
    }
