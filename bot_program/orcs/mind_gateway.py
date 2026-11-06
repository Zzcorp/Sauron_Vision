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
                    the caller's list raises before anything is sent. From
                    O2b (2026-11-06, B.15a) the wake's are r0-r4 (r5 only
                    through the Fable gate, C4's) and the smoke's h0, r0-r4;
                    the probe's (B.15b) h0, r0, r1, r3 and r4, with r2 only
                    as B.5's map of r3 and r4 (MAPPED_RUNGS)
  bound             A.21: every prompt token at the model's 1h cache write
                    on 1.35 x the estimate of the exact text sent, plus the
                    rung's max_tokens of output; plus the fallback's own,
                    where one is sent (B.14)
  fallback_list     B.14 (O2b, 2026-11-06): the list form the gateway
                    builds for a real-money wake on r2-r5, the fallback's
                    id read from the catalog; none for any other call
  ask_line          A.20: the Orcs line asked for this call's bound PLUS the
                    money of the OTHER calls in flight (the running wakes'
                    est_usd and the holds in OrcSetting "minds_inflight"),
                    never the call's own twice, never the default estimate,
                    never `total_only`. Its refusal is a code: line_off,
                    total, line or deep_share.
  call              the four gates read again just before the send (A.2),
                    and the caller's own switch (the probes', O2b), the
                    refusal while any seat reads above L0 (A.29), the
                    line asked, then ONE send (max_attempts=1) on the Orcs
                    line, agent "orc", the caller's source_ref, no client
                    refusal re-run. What came back is a reply dict, never
                    an exception, but for a rung the caller may not use.
  probes_spent      what the probes booked today on the Orcs line (the
                    ledger's ':probe:' rows), which their own allowance
                    weighs (B.11; O2b's probes, 2026-11-06)
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
                                        FALLBACK_MAX_TOKENS, FALLBACK_RUNGS,
                                        MINDS_INFLIGHT_KEY, PROBE_REF_MARK,
                                        REPLY_ANSWER, REPLY_BILLED,
                                        REPLY_CLOSED, REPLY_UNBILLED,
                                        REPLY_UNSENT, RUNG_LIMITS,
                                        WAKE_STATUS_RUNNING, WALL_S)

logger = logging.getLogger(__name__)

#: The agent every O2a call is billed under, and the line it lands on
#: (spend.orc_line_q: agent "orc", source_ref "Orc:...", A.27).
ORC_AGENT = "orc"
ORC_LINE = "orcs"
SOURCE_PREFIX = "Orc:"
#: §1.0.9: each caller and the rungs it may use. Later commits extend it;
#: r5 is reachable only through O2b's Fable gate (C4's). O2b's routed rung
#: (2026-11-06, B.15a): a wake answers on the rung the router chose, r0-r4,
#: and the smoke takes the wake's rungs beside h0. O2b's probes (2026-11-06,
#: B.15b): a probe reads on h0, r0, r1, r3 or r4 (paper never routes to r2,
#: real money's material rung).
CALLER_RUNGS = {"wake": ("r0", "r1", "r2", "r3", "r4"),
                "smoke": ("h0", "r0", "r1", "r2", "r3", "r4"),
                "probe": ("h0", "r0", "r1", "r3", "r4")}
#: §1.0.9's "mapped": a rung a caller reaches only as B.5's map of another
#: (one effort per model until the smoke's PASS): a probe answers on r2
#: only as the map of r3 or r4 (Opus at its one effort), named by the
#: rung it was asked as (`would`).
MAPPED_RUNGS = {"probe": {"r2": ("r3", "r4")}}
#: The keywords a caller's request may carry; the gateway sets the rest,
#: the fallbacks among them (B.14: the gateway builds the list form).
REQUEST_KEYS = ("system_blocks", "shared_user_blocks", "private_user_blocks",
                "turn_effort", "effort", "output_schema")


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


def check_rung(caller, name, *, would=None) -> None:
    """ValueError, before anything is sent, for a caller missing from
    CALLER_RUNGS or a rung outside its list (N4), but a rung MAPPED_RUNGS
    admits as B.5's map of `would`, the rung it was asked as (O2b's
    probes, 2026-11-06)."""
    allowed = CALLER_RUNGS.get(caller)
    if allowed is None:
        raise ValueError(f"no Orc caller {caller!r}: every model caller is "
                         f"a row of CALLER_RUNGS")
    if name in allowed:
        return
    if would is not None and would in MAPPED_RUNGS.get(caller, {}).get(
            name, ()):
        return
    raise ValueError(f"the {caller} caller may not use rung {name!r} "
                     f"(its rungs: {', '.join(allowed)})")


def bound(name, est_tokens, *, fallback=False) -> float:
    """A.21: what one call on rung `name` can cost at most, for a request
    estimated at `est_tokens`: every prompt token written to the 1h cache
    (the dearest input price) on ceil(est x 1.35), plus max_tokens of
    output. With `fallback` (B.14; O2b, 2026-11-06: a real-money wake on
    r2-r5), plus the fallback model's own bound: the same prompt written
    at its 1h price, and its own max_tokens of output."""
    from ai_agents.catalog import ORC_FALLBACK_V1, cost_usd
    step = rung(name)
    est = max(0, int(est_tokens or 0))
    headroom = int(round(BOUND_HEADROOM * 100))
    written = -(-est * headroom // 100)
    out = float(cost_usd(step["model"], input_tokens=0,
                         output_tokens=step["max_tokens"],
                         cache_write_1h=written))
    if fallback:
        out += float(cost_usd(ORC_FALLBACK_V1, input_tokens=0,
                              output_tokens=FALLBACK_MAX_TOKENS,
                              cache_write_1h=written))
    return out


def sends_fallback(caller, name, real_money) -> bool:
    """B.14 (O2b, 2026-11-06): only a real-money wake on r2-r5 names a
    fallback. Paper and demo wakes, and every ticket (the smoke, the
    probes; later the twin, Captains and the rest), send none: their
    bounds stay the primary's alone, and a refusal is a billed failure, as
    on r0 (a refused probe is stored invalid)."""
    return caller == "wake" and bool(real_money) and name in FALLBACK_RUNGS


def fallback_list(caller, name, real_money):
    """The list form [{"model": ORC_FALLBACK_V1, "max_tokens": 8000}] the
    gateway sends (B.14), the id read from the catalog by its name; None
    when sends_fallback says none."""
    if not sends_fallback(caller, name, real_money):
        return None
    from ai_agents.catalog import ORC_FALLBACK_V1
    return [{"model": ORC_FALLBACK_V1, "max_tokens": FALLBACK_MAX_TOKENS}]


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


def probes_spent() -> float:
    """What the probes booked today on the Orcs line (B.11; O2b's probes,
    2026-11-06): the ledger's rows since 00:00 UTC, on the line's own
    membership, whose source_ref names a probe (Orc:<pk>:Wake:<w>:probe:
    <rung>). Their own allowance weighs it, never the whole line's spend,
    which would let an Opus probe run only in the first hours of the UTC
    day."""
    from django.db.models import Sum
    from django.utils import timezone

    from ai_agents.models import AgentTask
    from ai_agents.spend import orc_line_q
    start = timezone.now().replace(hour=0, minute=0, second=0,
                                   microsecond=0)
    total = (AgentTask.objects.filter(created_at__gte=start)
             .filter(orc_line_q())
             .filter(structured_output__source_ref__icontains=PROBE_REF_MARK)
             .aggregate(s=Sum("cost_usd"))["s"])
    return float(total or 0)


def deep_share() -> float:
    """DEEP_TIER_SHARE (spend.py): the share of a line the deep and
    frontier tiers stop at. can_spend weighs only the line's BOOKED spend
    against it; the scheduler mirrors it on the money in flight and held
    (B.13; O2b, 2026-11-06), reading the share here."""
    from ai_agents import spend
    return float(spend.DEEP_TIER_SHARE)


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
         exclude_wake=None, exclude_key=None, real_urgent=False,
         real_money=False, would_rung=None) -> dict:
    """ONE model call for `caller` on rung `rung_name`, or none. `request`
    holds the caller's blocks, schema and efforts (REQUEST_KEYS); this
    function sets the model, the rung's limits, the agent, the line, the
    source_ref, max_attempts=1 and the fallback: the list form for a
    real-money wake (`real_money`) on r2-r5 only (B.14; O2b, 2026-11-06).
    `would_rung`: the rung a probe was asked as, which admits its mapped
    r2 (MAPPED_RUNGS; O2b's probes, 2026-11-06). Returns a reply dict:

      closed     nothing sent: a gate is OFF, the caller's own switch is
                 OFF (the probes'), a seat reads above L0, or the line
                 refused (`code`)
      unsent     nothing sent: the request was refused before the send
                 (a ValueError of build_request)
      answer     the model answered (`text`, `usage`)
      billed     the call failed and was billed (`usage`: a refusal, a
                 max_tokens stop with no text, an empty answer)
      unbilled   the call failed with no bill read (a timeout, a network
                 error, an error mid-stream): its bound stays held

    ValueError for a rung the caller may not use, a source_ref that is not
    an Orc's, or a request key the gateway owns: before anything is sent."""
    check_rung(caller, rung_name, would=would_rung)
    if not str(source_ref or "").startswith(SOURCE_PREFIX):
        raise ValueError(f"an Orc call's source_ref starts {SOURCE_PREFIX!r}")
    extra = set(request or {}) - set(REQUEST_KEYS)
    if extra:
        raise ValueError(f"the gateway sets {sorted(extra)} itself")
    step = rung(rung_name)
    from bot_program.orcs.switches import caller_code, gate_code
    code = gate_code() or caller_code(caller) or authority_code()
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
            timeout_s=step["timeout_s"],
            fallbacks=fallback_list(caller, rung_name, real_money),
            **dict(request or {}))
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
