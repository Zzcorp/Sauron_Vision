"""THE GATEWAY (the O2 spec A.20-A.23, N3, N4; O2a, 2026-11-05): the one
module of the Orcs that names the provider, the budget and the ledger.
Every other module of the package reaches a model only through `call`,
and the tick's import path never loads this one: it imports ai_agents
inside its functions.

  rung(name)        a rung of catalog.ORC_LADDER_V1, read by its name: the
                    model, the effort and the tier, with the rung's own
                    limits (constants.RUNG_LIMITS, WALL_S). No model id is
                    written here or anywhere in the package.
  CALLER_RUNGS      the rungs each caller may use (§1.0.9). A rung outside
                    the caller's list raises before anything is sent.
  bound             A.21: every prompt token at the model's 1h cache write
                    on 1.35 x the estimate of the exact text sent, plus the
                    rung's max_tokens of output. O2a sends no fallback.
  ask_line          A.20: the Orcs line asked for this call's bound PLUS the
                    money of the OTHER calls in flight (the running wakes'
                    est_usd and the holds in OrcSetting "minds_inflight"),
                    never the call's own twice, never the default estimate,
                    never `total_only`. Its refusal is a code: line_off,
                    total, line or deep_share.
  call              the four gates read again just before the send (A.2),
                    the refusal while any seat reads above L0 (A.29), the
                    line asked, then ONE send (max_attempts=1) on the Orcs
                    line, agent "orc", the caller's source_ref, no client
                    refusal re-run. What came back is a reply dict, never
                    an exception, but for a rung the caller may not use.
  measure_tokens    the provider's free token count (`orcs tokens`, A.61):
                    never complete(), never ledgered.
  ledger_row        the settle's one lookup of the provider's own ledger
                    row for this call (A.24).

A model's words leave here as text only: never a fact, money or an
instruction (N5); validator.py reads them.
"""
import logging
import time
from datetime import timedelta

from bot_program.orcs.constants import (BOUND_HEADROOM, CODE_AUTHORITY,
                                        CODE_BILLED_FAILURE, CODE_DEEP_SHARE,
                                        CODE_LINE, CODE_LINE_OFF, CODE_TOTAL,
                                        CODE_UNBILLED, CODE_UNSENT,
                                        MINDS_INFLIGHT_KEY, REPLY_ANSWER,
                                        REPLY_BILLED, REPLY_CLOSED,
                                        REPLY_UNBILLED, REPLY_UNSENT,
                                        RUNG_LIMITS, WAKE_STATUS_RUNNING,
                                        WALL_S)

logger = logging.getLogger(__name__)

#: The agent every O2a call is billed under, and the line it lands on
#: (spend.orc_line_q: agent "orc", source_ref "Orc:...", A.27).
ORC_AGENT = "orc"
ORC_LINE = "orcs"
SOURCE_PREFIX = "Orc:"
#: §1.0.9: each caller and the rungs it may use. Later commits extend it;
#: r5 is reachable only through O2b's Fable gate.
CALLER_RUNGS = {"wake": ("r0",), "smoke": ("r0", "h0")}
#: The keywords a caller's request may carry; the gateway sets the rest.
REQUEST_KEYS = ("system_blocks", "shared_user_blocks", "private_user_blocks",
                "turn_effort", "effort", "output_schema", "fallbacks")


# ── the rungs ────────────────────────────────────────────────────────────

def rung(name) -> dict:
    """{rung, model, effort, tier, family, max_tokens, timeout_s, wall_s}
    of the ladder's rung `name` (catalog.ORC_LADDER_V1). ValueError for a
    rung the ladder does not hold."""
    from ai_agents.catalog import MODELS, ORC_LADDER_V1

    from bot_program.orcs.dossier import family_of
    for step in ORC_LADDER_V1:
        if step["rung"] == name:
            model = step["model"]
            limits = RUNG_LIMITS[name]
            return {"rung": name, "model": model, "effort": step["effort"],
                    "tier": MODELS.get(model, {}).get("tier_hint",
                                                      "balanced"),
                    "family": family_of(model),
                    "max_tokens": int(limits["max_tokens"]),
                    "timeout_s": float(limits["timeout_s"]),
                    "wall_s": int(WALL_S[name])}
    raise ValueError(f"no rung {name!r} on the Orcs' ladder")


def check_rung(caller, name) -> None:
    """ValueError, before anything is sent, for a caller missing from
    CALLER_RUNGS or a rung outside its list (N4)."""
    allowed = CALLER_RUNGS.get(caller)
    if allowed is None:
        raise ValueError(f"no Orc caller {caller!r}: every model caller is "
                         f"a row of CALLER_RUNGS")
    if name not in allowed:
        raise ValueError(f"the {caller} caller may not use rung {name!r} "
                         f"(its rungs: {', '.join(allowed)})")


def bound(name, est_tokens) -> float:
    """A.21: what one call on rung `name` can cost at most, for a request
    estimated at `est_tokens`: every prompt token written to the 1h cache
    (the dearest input price) on ceil(est x 1.35), plus max_tokens of
    output. No fallback is sent in O2a."""
    from ai_agents.catalog import cost_usd
    step = rung(name)
    est = max(0, int(est_tokens or 0))
    headroom = int(round(BOUND_HEADROOM * 100))
    written = -(-est * headroom // 100)
    return float(cost_usd(step["model"], input_tokens=0,
                          output_tokens=step["max_tokens"],
                          cache_write_1h=written))


def supports_turn_effort(name) -> bool:
    """The rung's model takes the effort-only system message (A.23)."""
    from ai_agents.catalog import supports_per_message_effort
    return bool(supports_per_message_effort(rung(name)["model"]))


def default_effort(name):
    """The effort the API applies to the rung's model when none is sent."""
    from ai_agents.catalog import default_effort as catalog_default
    return catalog_default(rung(name)["model"])


# ── the line ─────────────────────────────────────────────────────────────

def line_cap() -> float:
    """The Orcs line's cap today (spend.orc_line_cap): 0 while it is off."""
    from ai_agents import spend
    return float(spend.orc_line_cap())


def line_spent() -> float:
    """What the Orcs line booked today, from the ledger."""
    from ai_agents import spend
    return float(spend.spent_today(ORC_LINE))


def line_summary() -> dict:
    """Both lines and the total (spend.lines_summary), for the staff."""
    from ai_agents import spend
    return spend.lines_summary()


def live_floor() -> float:
    """ORC_LIVE_FLOOR_USD: what the core line holds back while the Orcs
    line is on (spend.py). The core subtracts only the Orcs' BOOKED spend
    and this floor, so the Orcs' money in flight and held never passes it
    (A.18's `inflight` rule; O2a's queue, 2026-11-05)."""
    from ai_agents import spend
    return float(spend.ORC_LIVE_FLOOR_USD)


def _until_ok(entry, now) -> bool:
    from django.utils.dateparse import parse_datetime
    until = entry.get("until")
    if not until:
        return True
    try:
        at = parse_datetime(str(until))
    except (TypeError, ValueError):
        return True
    return at is None or at > now


def holds(now=None) -> dict:
    """The money held in OrcSetting "minds_inflight" that has not expired:
    {key: entry}. An expired hold is money no longer held."""
    from django.utils import timezone

    from bot_program.orcs.models import OrcSetting
    now = now or timezone.now()
    value = OrcSetting.get(MINDS_INFLIGHT_KEY) or {}
    if not isinstance(value, dict):
        return {}
    return {k: v for k, v in value.items()
            if isinstance(v, dict) and _until_ok(v, now)}


def inflight_usd(*, exclude_wake=None, exclude_key=None, now=None) -> float:
    """The OTHER calls' money: the est_usd of every running wake but
    `exclude_wake`, and every hold or ticket but `exclude_key` and those of
    `exclude_wake` (A.20). A call's own reservation is never counted."""
    from django.db.models import Sum

    from bot_program.orcs.models import OrcWake
    qs = OrcWake.objects.filter(status=WAKE_STATUS_RUNNING)
    if exclude_wake is not None:
        qs = qs.exclude(pk=exclude_wake)
    running = float(qs.aggregate(s=Sum("est_usd"))["s"] or 0)
    held = 0.0
    for key, entry in holds(now).items():
        if key == exclude_key or (exclude_wake is not None
                                  and entry.get("wake") == exclude_wake):
            continue
        try:
            held += float(entry.get("usd") or 0)
        except (TypeError, ValueError):
            continue
    return running + held


def ask_line(*, rung_name, bound_usd, exclude_wake=None, exclude_key=None,
             real_urgent=False) -> tuple:
    """(allowed, code, why) for one call of `bound_usd` on rung
    `rung_name` (A.20). It classifies first: the line off (`line_off`),
    the whole AI budget spent (`total`); then asks spend.can_spend on the
    Orcs line, with the rung's honest tier, for the bound plus the other
    calls' money in flight and held. A refusal is `deep_share` when it
    names the deep-tier reserve, else `line`. `real_urgent` exempts a
    real-money urgent wake from the deep share (D30)."""
    from ai_agents import spend
    if spend.orc_line_cap() <= 0:
        return False, CODE_LINE_OFF, "the Orcs line is off"
    total = spend.daily_budget(spend.TOTAL)
    if total > 0 and spend.spent_today(spend.TOTAL) >= total:
        return False, CODE_TOTAL, "the whole AI budget of the day is spent"
    step = rung(rung_name)
    others = inflight_usd(exclude_wake=exclude_wake, exclude_key=exclude_key)
    allowed, why = spend.can_spend(tier=step["tier"],
                                   estimated_usd=float(bound_usd) + others,
                                   line=ORC_LINE,
                                   deep_share_exempt=bool(real_urgent))
    if allowed:
        return True, "", why
    text = str(why or "")
    if "deep-tier" in text:
        return False, CODE_DEEP_SHARE, text
    if "line is off" in text:
        return False, CODE_LINE_OFF, text
    if "daily AI budget spent" in text:
        return False, CODE_TOTAL, text
    return False, CODE_LINE, text


# ── the gates ────────────────────────────────────────────────────────────

def authority_code() -> str:
    """`authority` while any OrcSeat reads above L0 (A.29): S tells the
    model that nothing it decides is applied, and the gateway keeps that
    sentence true. An unreadable seat table refuses too."""
    try:
        from bot_program.orcs.models import OrcSeat
        above = OrcSeat.objects.filter(level__gt=0).exists()
    except Exception as e:  # noqa: BLE001 — unread is refused
        logger.warning("[orcs] the seats could not be read: %s", e)
        above = True
    return CODE_AUTHORITY if above else ""


# ── the call ─────────────────────────────────────────────────────────────

def _reply(kind, *, sent, code="", why="", text=None, usage=None, error="",
           step=None, latency=0.0, stop_reason=None) -> dict:
    return {"kind": kind, "sent": bool(sent), "code": str(code or ""),
            "why": str(why or "")[:300], "text": text, "usage": usage,
            "error": str(error or "")[:300],
            "rung": (step or {}).get("rung", ""),
            "model": (step or {}).get("model", ""),
            "latency": round(float(latency or 0.0), 3),
            "stop_reason": stop_reason}


def _error_words(exc) -> str:
    """An exception as the journal's body keeps it: its class, and its
    first words folded to plain ASCII (never a headline)."""
    from bot_program.orcs.fence import sanitize
    return f"{type(exc).__name__}: {sanitize(str(exc), 160)}"


def call(*, caller, rung_name, request, source_ref, bound_usd,
         exclude_wake=None, exclude_key=None, real_urgent=False) -> dict:
    """ONE model call for `caller` on rung `rung_name`, or none. `request`
    holds the caller's blocks, schema and efforts (REQUEST_KEYS); this
    function sets the model, the rung's limits, the agent, the line, the
    source_ref and max_attempts=1. Returns a reply dict:

      closed     nothing sent: a gate is OFF, a seat reads above L0, or
                 the line refused (`code`)
      unsent     nothing sent: the request was refused before the send
                 (a ValueError of build_request)
      answer     the model answered (`text`, `usage`)
      billed     the call failed and was billed (`usage`: a refusal, a
                 max_tokens stop with no text, an empty answer)
      unbilled   the call failed with no bill read (a timeout, a network
                 error, an error mid-stream): its bound stays held

    ValueError for a rung the caller may not use, a source_ref that is not
    an Orc's, or a request key the gateway owns: before anything is sent."""
    check_rung(caller, rung_name)
    if not str(source_ref or "").startswith(SOURCE_PREFIX):
        raise ValueError(f"an Orc call's source_ref starts {SOURCE_PREFIX!r}")
    extra = set(request or {}) - set(REQUEST_KEYS)
    if extra:
        raise ValueError(f"the gateway sets {sorted(extra)} itself")
    step = rung(rung_name)
    from bot_program.orcs.switches import gate_code
    code = gate_code() or authority_code()
    if code:
        return _reply(REPLY_CLOSED, sent=False, code=code, step=step)
    allowed, code, why = ask_line(rung_name=rung_name, bound_usd=bound_usd,
                                  exclude_wake=exclude_wake,
                                  exclude_key=exclude_key,
                                  real_urgent=real_urgent)
    if not allowed:
        return _reply(REPLY_CLOSED, sent=False, code=code, why=why,
                      step=step)
    from ai_agents.providers.claude_provider import ClaudeProvider
    provider = ClaudeProvider()
    started = time.monotonic()
    try:
        text, usage = provider.complete(
            agent_name=ORC_AGENT, record=True, source_ref=str(source_ref),
            model=step["model"], line=ORC_LINE, client_refusal_rerun=False,
            max_attempts=1, max_tokens=step["max_tokens"],
            timeout_s=step["timeout_s"], **dict(request or {}))
    except ValueError as e:
        return _reply(REPLY_UNSENT, sent=False, code=CODE_UNSENT,
                      error=_error_words(e), step=step,
                      latency=time.monotonic() - started)
    except RuntimeError as e:
        usage = getattr(e, "usage", None)
        if isinstance(usage, dict):
            return _reply(REPLY_BILLED, sent=True, code=CODE_BILLED_FAILURE,
                          usage=usage, error=_error_words(e), step=step,
                          latency=time.monotonic() - started,
                          stop_reason=usage.get("stop_reason"))
        return _reply(REPLY_UNBILLED, sent=True, code=CODE_UNBILLED,
                      error=_error_words(e), step=step,
                      latency=time.monotonic() - started)
    except Exception as e:  # noqa: BLE001 — a timeout, the network, the SDK
        return _reply(REPLY_UNBILLED, sent=True, code=CODE_UNBILLED,
                      error=_error_words(e), step=step,
                      latency=time.monotonic() - started)
    return _reply(REPLY_ANSWER, sent=True, text=text, usage=usage, step=step,
                  latency=time.monotonic() - started,
                  stop_reason=(usage or {}).get("stop_reason"))


def has_key() -> bool:
    """The provider's API key is set in this process: what `orcs tokens
    --yes` needs, and all it needs (A.61)."""
    from ai_agents.providers.claude_provider import ClaudeProvider
    return bool(ClaudeProvider().api_key)


def measure_tokens(*, rung_name="r0", system_blocks=None,
                   shared_user_blocks=None, private_user_blocks=None,
                   system_prompt="", user_message="") -> int:
    """The input tokens of a request on the rung's model, from the
    provider's free count (N3's one exception): never complete(), never
    ledgered, no switch and no line asked (A.61)."""
    from ai_agents.providers.claude_provider import ClaudeProvider
    step = rung(rung_name)
    provider = ClaudeProvider()
    return int(provider.count_tokens(
        model=step["model"], system_prompt=system_prompt,
        system_blocks=system_blocks, user_message=user_message,
        shared_user_blocks=shared_user_blocks,
        private_user_blocks=private_user_blocks))


# ── the ledger ───────────────────────────────────────────────────────────

def ledger_row(source_ref, since=None) -> bool:
    """True when the provider's own ledger row of this call exists: an
    AgentTask whose structured_output.source_ref is `source_ref`, created
    since `since` (A.24). The provider fences that write and only logs a
    failure, while the line reads AgentTask alone: no row means the line
    undercounts, and the settle holds the money instead."""
    from ai_agents.models import AgentTask
    qs = AgentTask.objects.filter(structured_output__source_ref=str(
        source_ref or ""))
    if since is not None:
        qs = qs.filter(created_at__gte=since - timedelta(seconds=1))
    return qs.exists()
