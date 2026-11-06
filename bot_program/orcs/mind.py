"""ONE CLAIMED WAKE, READ IN SHADOW (the O2 spec A.23-A.26, A.39-A.41;
O2a, 2026-11-05). A wake reaches it only through the queue: the render
pass admits it (wake.render_queued), the worker claims it (scheduler.claim)
with the four gates on, which the operator alone opens (the minds switch
with his PIN, the Orcs line above 0). Both arrive closed.

  build_request  A.23: the request from the wake's STORED blocks (S by its
                 hash; the shared turn MK0, the closed sessions, MK-E and
                 IN-slow; the private turn PS and the tail), the cache
                 breakpoints (S 1h; the last closed session, or MK0, and
                 MK-E 1h; IN-slow none), the schema, and the effort rule:
                 the effort-only message only for a model that takes it
                 AND whose family the smoke passed (OrcSetting
                 "smoke_verdict"), the top-level effort pinned at the
                 model's default then; else the rung's effort on top
  think          the call through the gateway (no lock held), the answer
                 judged (no lock held), then the settle (scheduler.settle)
  judge          the parse, the validator (V1-V14) and the officer
                 (I2-I12), as of the wake's own validation context: never
                 under a lock (N8)
  ticket_*       A.57 (O2a's arm, 2026-11-05): a ticket's caller, the
                 estimate of the exact text it sends and its bound, for the
                 scheduler's tickets and `orcs smoke` (reads, never a call)
  judge_probe    B.11 (O2b's probes, 2026-11-06): a probe's answer through
                 the same validator, with no lock held, blind to the
                 routed answer; probes_spent, the probes' booked spend
                 today, for the scheduler's allowance (a read)
  answering_map  B.5 (O2b, 2026-11-06): {rung: the rung that answers it},
                 the effort map the router reads (router.py names no
                 model): the gateway's ladder and the smoke's verdicts,
                 read once per render, never under a lock
  *_rung         B.2b (O2b's routed rung, 2026-11-06): the rung a wake is
                 answered on, behind the router's switch: admitted_rung
                 (admission: the route's answering rung while the switch is
                 ON and the dossier was rendered for its family, else r0),
                 claim_rung (each claim: the admitted rung through the
                 effort map again while ON, r0 once OFF), answering_rung
                 (B.5's map for one rung: the smoke), rung_family
  rung_words     a rung in tier words (A.62), or the router's choice in
                 them ("would route: r2 (deep tier, medium effort)", B.16c)
  write_*        the outcome's writes, called by the settle inside its one
                 transaction: database writes only. A done answer writes
                 its decision (with the booking), its plan (a revision),
                 its proposals (OrcIntent, one per proposal that is not a
                 hold), the filtered note, last_good_wake_at and
                 last_facts_hash; a refused one its decision and its
                 refusal; a late one its decision only (A.26); and on
                 every outcome the card's intellect says how the wake was
                 answered: its status words, and its rung in tier words
                 once a model was sent it (write_intellect, A.62)

Every proposal is in shadow: an OrcIntent is judged, queued for the Orc's
own arm or recorded, and never sent anywhere. Its level is the stored
reference copied from the wake's menu, never a model's price (A.30), and
its candidate and event are the answer as kept (_kept), refused or not:
an id that is not the wake's own reads "unknown", never the model's text
(N5; 2026-11-05)."""
import logging
import re
from datetime import timedelta
from decimal import Decimal

from bot_program.orcs.constants import (ACTIONS, CODE_UNSENT, INTENT_KINDS,
                                        REPLY_ANSWER, REPLY_BILLED,
                                        REPLY_CLOSED, REPLY_UNBILLED,
                                        REPLY_UNSENT, RUNG_LIMITS, RUNG_NONE,
                                        RUNG_T,
                                        INTENT_STATUS_QUEUED,
                                        INTENT_STATUS_RECORDED,
                                        INTENT_STATUS_REFUSED, INTENT_TTL_S,
                                        MINDS_SWITCH, MODE_REFUSED,
                                        MODE_SHADOW, O2A_RUNG,
                                        OFFICER_REFUSE, PROBE_CALLER,
                                        S_VERSION, SCHEMA_VERSION,
                                        SMOKE_VERDICT_KEY, STATE_CARE_OWNED,
                                        W11_ASK_KEY,
                                        WAKE_CODE_WORDS, WAKE_STATUS_DONE,
                                        WAKE_STATUS_FAILED, WAKE_STATUS_LATE,
                                        WAKE_STATUS_REFUSED,
                                        WAKE_STATUS_SKIPPED)
from bot_program.orcs.intents import CARD_INTENTS, STATUS_T, intent_words

logger = logging.getLogger(__name__)

#: The caller of a wake's call (§1.0.9) and its source_ref's word.
CALLER = "wake"
#: A fact id as the answer may cite one (F41, DR3).
FACT_ID = re.compile(r"(?:F|DR)\d{1,6}")
ACTION_WORDS = {"hold": "hold", "revise_plan": "revise the plan"}


def source_ref(wake, rung, caller=CALLER) -> str:
    """`Orc:<pk>:Wake:<w>:<rung>` (§1.0.9): the Orcs line's own prefix. A
    probe's names its wake and itself (B.11; O2b's probes, 2026-11-06):
    `Orc:<pk>:Wake:<w>:probe:<rung>`, so the ledger counts it on its rung
    and its own allowance finds it."""
    if caller == PROBE_CALLER:
        return f"Orc:{wake.orc_id}:Wake:{wake.pk}:{PROBE_CALLER}:{rung}"
    word = "Wake" if caller == CALLER else str(caller).capitalize()
    return f"Orc:{wake.orc_id}:{word}:{wake.pk}:{rung}"


#: The replies of a call that was sent (A.25): a model read the wake, or
#: its bill may follow.
SENT = (REPLY_ANSWER, REPLY_BILLED, REPLY_UNBILLED)


def rung_words(rung_name, words=RUNG_T) -> str:
    """A rung in tier words for the card (A.62): "r0 · balanced tier, low
    effort"; with `words` constants.ROUTE_WOULD_T, the router's choice as
    the Orc's page shows it (B.16c; O2b, 2026-11-06): "would route: r2
    (deep tier, medium effort)". No model id, no cost. Read through the
    gateway's catalog read (no query), never under a lock (think, before
    the settle; the render, before its journal entry)."""
    from bot_program.orcs import mind_gateway
    try:
        step = mind_gateway.rung(rung_name)
    except (ValueError, KeyError):
        return RUNG_NONE
    return words.format(rung=step["rung"], tier=step["tier"],
                        effort=step["effort"])


def answering_map() -> dict:
    """B.5 (O2b, 2026-11-06): {rung: the rung that answers it}, the effort
    map the router reads (router.py holds no model knowledge). Until the
    smoke's PASS is recorded for a model's family (A.61), that model runs
    at one effort, its first rung's on the ladder: Sonnet's rungs answer
    as r0 (low effort), Opus's as r2 (medium), so r1 answers as r0 and r3
    and r4 as r2. With the PASS each of its rungs answers as itself. The
    gateway's ladder (the catalog, no query) and the smoke's verdicts (one
    read) are read once per render, before its transaction: never under
    a lock (N8). A rung the ladder does not hold is left out."""
    from bot_program.orcs import mind_gateway
    from bot_program.orcs.models import OrcSetting
    verdicts = OrcSetting.get(SMOKE_VERDICT_KEY) or {}
    steps = []
    for name in sorted(RUNG_LIMITS):
        try:
            steps.append(mind_gateway.rung(name))
        except (ValueError, KeyError):
            continue
    first = {}
    for step in steps:
        first.setdefault(step["family"], step["rung"])
    return {step["rung"]: (step["rung"] if _passed(verdicts, step["family"])
                           else first[step["family"]])
            for step in steps}


# ── the request (A.23) ───────────────────────────────────────────────────

def _passed(verdicts, family) -> bool:
    entry = verdicts.get(family) if isinstance(verdicts, dict) else None
    return isinstance(entry, dict) and str(entry.get("verdict") or "") \
        .lower() == "pass"


def smoke_pass(family) -> bool:
    """The smoke's recorded verdict for `family` is a PASS (A.61)."""
    from bot_program.orcs.models import OrcSetting
    return _passed(OrcSetting.get(SMOKE_VERDICT_KEY) or {}, family)


def efforts(rung_name) -> dict:
    """A.23's effort rule. The effort-only message governs the private
    turn only when the model takes it AND the smoke's effort check passed
    for its family; then the top-level effort is pinned at the model's
    default, so the cache key never moves. Otherwise no turn_effort, and
    the rung's own effort at the top level."""
    from bot_program.orcs import mind_gateway
    step = mind_gateway.rung(rung_name)
    if mind_gateway.supports_turn_effort(rung_name) and \
            smoke_pass(step["family"]):
        return {"turn_effort": step["effort"],
                "effort": mind_gateway.default_effort(rung_name)}
    return {"effort": step["effort"]}


def build_request(wake, rung_name) -> dict:
    """The call's blocks, schema and efforts, from the wake's stored
    blocks (dossier.text_of's store). ValueError when a block is
    missing: nothing is sent."""
    from bot_program.orcs import validator
    from bot_program.orcs.models import OrcDossierBlock
    comps = wake.components if isinstance(wake.components, dict) else {}
    hashes = [str(h) for h in wake.block_hashes or []]
    s_hash = str((comps.get("s") or {}).get("hash") or "")
    shared_n = int(comps.get("shared") or 0)
    if not s_hash or not hashes or not 0 < shared_n < len(hashes):
        raise ValueError("the wake holds no stored dossier to send")
    found = {b.hash: b for b in OrcDossierBlock.objects.filter(
        hash__in=hashes + [s_hash]).only("hash", "kind", "text")}
    missing = [h for h in hashes + [s_hash] if h not in found]
    if missing:
        raise ValueError(f"{len(missing)} stored block(s) missing")
    shared = hashes[:shared_n]
    kinds = [found[h].kind for h in shared]
    sessions = [i for i, k in enumerate(kinds) if k == "mk_session"]
    first = [i for i, k in enumerate(kinds) if k == "mk0"]
    marks = set(sessions[-1:] or first[:1])
    marks |= {i for i, k in enumerate(kinds) if k == "mk_e"}
    return {
        "system_blocks": [{"text": found[s_hash].text, "cache_ttl": "1h"}],
        "shared_user_blocks": [
            {"text": found[h].text, "cache_ttl": "1h" if i in marks else None}
            for i, h in enumerate(shared)],
        "private_user_blocks": [{"text": found[h].text, "cache_ttl": None}
                                for h in hashes[shared_n:]],
        "output_schema": validator.SCHEMA_V1,
        **efforts(rung_name)}


# ── the line, as the scheduler weighs it (O2a's queue, 2026-11-05) ───────
# The scheduler holds the line lock and the Orc's lock over its checks
# and names no gateway (N8; tests/orcs/test_orc_o2a_locks.py): these are
# the gateway's READS it needs there, the ledger's sums, the settings and
# the catalog's arithmetic. None of them sends anything.

def price(wake, rung_name, *, real=False) -> dict:
    """{bound, model, tier, fallback} of one call for `wake` on rung
    `rung_name`: A.21's bound on the render's estimate of the exact text
    sent (components["tokens"]), the rung's model and tier read from the
    catalog by the rung's name. `real`: the wake is real money, so on
    r2-r5 it names the fallback and its bound adds the fallback's own
    (B.14; O2b, 2026-11-06)."""
    from bot_program.orcs import mind_gateway
    step = mind_gateway.rung(rung_name)
    comps = wake.components if isinstance(wake.components, dict) else {}
    fallback = mind_gateway.sends_fallback(CALLER, rung_name, real)
    return {"bound": float(mind_gateway.bound(rung_name, comps.get("tokens"),
                                              fallback=fallback)),
            "model": step["model"], "tier": step["tier"],
            "fallback": bool(fallback)}


def purse(*, exclude_wake=None) -> dict:
    """The Orcs line as admission and the claim weigh it (A.13, A.18): its
    cap, what it booked today, the OTHER calls' money in flight and held
    (every running wake's est_usd but `exclude_wake`'s, and the holds and
    tickets of OrcSetting "minds_inflight"), the floor the core line
    holds back for the Orcs (ORC_LIVE_FLOOR_USD), and the deep tiers'
    share of the line (DEEP_TIER_SHARE: B.13, O2b, 2026-11-06)."""
    from bot_program.orcs import mind_gateway
    return {"cap": mind_gateway.line_cap(),
            "spent": mind_gateway.line_spent(),
            "inflight": mind_gateway.inflight_usd(exclude_wake=exclude_wake),
            "floor": mind_gateway.live_floor(),
            "deep_share": mind_gateway.deep_share()}


# ── the answering rung (B.2b, B.4, B.5; O2b's routed rung, 2026-11-06) ──
# The router's switch (`orcs_router`) decides which rung answers a wake a
# model reads: OFF, r0 (O2A_RUNG), the router's choice only recorded; ON,
# the rung the router chose, through the effort map. The scheduler reads
# these before its locks and names no gateway (N8).

def rung_family(rung_name) -> str:
    """The model family of rung `rung_name` (the catalog's, through the
    gateway's ladder): the family a routed wake's dossier is rendered for
    (B.4). "" for a rung the ladder does not hold."""
    from bot_program.orcs import mind_gateway
    try:
        return str(mind_gateway.rung(rung_name)["family"])
    except (ValueError, KeyError):
        return ""


def answering_rung(rung_name) -> str:
    """B.5 for one rung, read now: the rung that answers `rung_name` (one
    effort per model until the smoke's PASS for its family). Tickets map
    the same way (the smoke here)."""
    return str(answering_map().get(rung_name, rung_name))


def admitted_rung(wake, *, router_on) -> str:
    """B.2b at admission: the rung written in components["rung"]. While
    the router's switch is ON, the route's answering rung, when the wake
    caller may use it (CALLER_RUNGS: r0-r4) and the stored dossier was
    rendered for its model's family (the render read the switch first,
    B.4); otherwise r0, as O2a."""
    from bot_program.orcs import mind_gateway
    if not router_on:
        return O2A_RUNG
    comps = wake.components if isinstance(wake.components, dict) else {}
    route = comps.get("route") if isinstance(comps.get("route"), dict) else {}
    rung = str(route.get("rung") or "")
    if rung not in mind_gateway.CALLER_RUNGS[CALLER] or \
            rung_family(rung) != str(comps.get("family") or ""):
        return O2A_RUNG
    return rung


def claim_rung(wake, *, router_on) -> str:
    """B.2b at each claim (frictionless off): while the router's switch is
    ON, the admitted rung (components["rung"]) through the effort map once
    more, so a verdict recorded since the render binds now (the map keeps
    a model's family, so the dossier still fits); once it is OFF, r0: the
    wake is re-priced and answered on r0 from its stored dossier (Opus's
    and Sonnet's texts are one size at the factor 1.0)."""
    if not router_on:
        return O2A_RUNG
    comps = wake.components if isinstance(wake.components, dict) else {}
    return answering_rung(str(comps.get("rung") or O2A_RUNG))


def ask_line(*, rung_name, bound_usd, exclude_wake=None,
             real_urgent=False) -> tuple:
    """The line's answer for one call (A.20), (allowed, code, why): the
    gateway asks spend.can_spend for this bound plus the other calls'
    money, never its own twice, never total_only."""
    from bot_program.orcs import mind_gateway
    return mind_gateway.ask_line(rung_name=rung_name, bound_usd=bound_usd,
                                 exclude_wake=exclude_wake,
                                 real_urgent=real_urgent)


# ── the tickets, as the scheduler and the commands weigh them (A.57; O2a's
# arm, 2026-11-05): the gateway's reads, never a call ────────────────────

def ticket_caller(caller, rung_name, *, would=None) -> None:
    """A.57: a ticket is for a caller of §1.0.9 that is not the wake
    (mind_gateway.CALLER_RUNGS), on one of that caller's rungs, or one it
    reaches only as B.5's map of `would` (a probe's r2: O2b's probes,
    2026-11-06): else ValueError, before anything is held or sent (N4)."""
    from bot_program.orcs import mind_gateway
    if caller == CALLER:
        raise ValueError("a wake is claimed, never ticketed")
    mind_gateway.check_rung(caller, rung_name, would=would)


def probes_spent() -> float:
    """What the probes booked today on the Orcs line (the ledger's probe
    rows, through the gateway): their own allowance weighs it (B.11; O2b's
    probes, 2026-11-06). A read, never a call."""
    from bot_program.orcs import mind_gateway
    return mind_gateway.probes_spent()


def ticket_price(rung_name, tokens) -> dict:
    """{bound, model, tier, wall_s} of one ticket on rung `rung_name`:
    A.21's bound on `tokens`, the estimate of the exact text sent, with
    the rung's own limits; a ticket sends no fallback (B.14)."""
    from bot_program.orcs import mind_gateway
    step = mind_gateway.rung(rung_name)
    return {"bound": float(mind_gateway.bound(rung_name, tokens)),
            "model": step["model"], "tier": step["tier"],
            "wall_s": int(step["wall_s"])}


def ticket_tokens(wake, rung_name) -> int:
    """A.57: the estimate of the exact text a ticket sends from `wake`'s
    stored dossier: dossier.estimate_tokens of S and of each stored block
    (with its own bar rows), x the rung's family factor."""
    from bot_program.orcs import dossier, mind_gateway
    from bot_program.orcs.models import OrcDossierBlock
    model = mind_gateway.rung(rung_name)["model"]
    comps = wake.components if isinstance(wake.components, dict) else {}
    hashes = [str(h) for h in wake.block_hashes or []]
    s = comps.get("s") if isinstance(comps.get("s"), dict) else {}
    s_hash = str(s.get("hash") or "")
    if s_hash:
        hashes.append(s_hash)
    found = {b.hash: b for b in OrcDossierBlock.objects.filter(
        hash__in=hashes).only("hash", "text", "body")}
    total = 0
    for h in hashes:
        b = found.get(h)
        if b is None:
            continue
        body = b.body if isinstance(b.body, dict) else {}
        total += dossier.estimate_tokens(b.text, int(body.get("bar_rows")
                                                     or 0), model)
    return int(total)


# ── one wake ─────────────────────────────────────────────────────────────

def _real_urgent(wake) -> bool:
    """A real-money urgent wake, as the claim judged it (A.14): the seat
    AND the row's own world live, never birth.world's guess for a row that
    states no world. Only such a wake passes the deep share (D30)."""
    comps = wake.components if isinstance(wake.components, dict) else {}
    return bool(comps.get("real")) and bool(comps.get("urgent"))


def think(wake, *, now=None) -> dict:
    """Read one CLAIMED (running) wake: build the request, call once
    through the gateway, judge the answer, settle. No lock is held but
    the settle's own. Returns the settle's result."""
    from django.utils import timezone

    from bot_program.orcs import mind_gateway, scheduler
    comps = wake.components if isinstance(wake.components, dict) else {}
    # B.2b (O2b, 2026-11-06): the claim's rung, the answering rung
    rung_name = str(comps.get("rung") or O2A_RUNG)
    real = bool(comps.get("real"))
    ref = source_ref(wake, rung_name)
    try:
        request = build_request(wake, rung_name)
        bound_usd = float(wake.est_usd or 0) or mind_gateway.bound(
            rung_name, comps.get("tokens"), fallback=mind_gateway
            .sends_fallback(CALLER, rung_name, real))
        reply = mind_gateway.call(caller=CALLER, rung_name=rung_name,
                                  request=request, source_ref=ref,
                                  bound_usd=bound_usd, exclude_wake=wake.pk,
                                  real_urgent=_real_urgent(wake),
                                  real_money=real)
    except (ValueError, KeyError, TypeError) as e:
        # nothing was sent: a block missing, or a rung the wake caller may
        # not use (N4), which the gateway refuses before any send
        reply = {"kind": REPLY_UNSENT, "sent": False, "code": CODE_UNSENT,
                 "why": "", "text": None, "usage": None,
                 "error": f"{type(e).__name__}: {e}"[:300],
                 "rung": rung_name, "model": "", "latency": 0.0,
                 "stop_reason": None}
    now = now or timezone.now()
    outcome = judge(wake, reply, now=now)
    outcome["source_ref"] = ref
    # A.62: the card's rung, once a model was sent the wake (no lock held)
    outcome["rung_t"] = (rung_words(rung_name) if reply.get("kind") in SENT
                         else RUNG_NONE)
    # A.24 step 3: the provider's own ledger row of this call, looked up
    # once, before the settle takes its locks
    outcome["ledger"] = (mind_gateway.ledger_row(ref, since=wake.started_at)
                         if isinstance(outcome.get("usage"), dict) else None)
    return scheduler.settle(wake, outcome, now=now)


def _kept(answer, vctx) -> dict:
    """The answer as it is stored and shown again: the note already
    filtered (V11), and every id the model wrote kept only when it names
    code's own (a menu level, a candidate, an event, a fact id): a
    model's free text never rides an id into a page or a prompt."""
    vctx = vctx if isinstance(vctx, dict) else {}
    menu = {str(lv.get("id")) for lv in vctx.get("menu") or []
            if isinstance(lv, dict)}
    cands = {str(c.get("id")) for c in vctx.get("candidates") or []
             if isinstance(c, dict)}
    events = set((vctx.get("events") or {}).keys())

    def keep(value, known):
        v = str(value or "")
        return v if v == "none" or v in known else "unknown"
    a = dict(answer or {})
    a["level_id"] = keep(a.get("level_id"), menu)
    a["candidate"] = keep(a.get("candidate"), cands)
    a["event_id"] = keep(a.get("event_id"), events)
    a["facts_cited"] = [str(f) for f in a.get("facts_cited") or []
                        if FACT_ID.fullmatch(str(f))]
    a["plan_clauses"] = [{"kind": c.get("kind"),
                          "level_id": keep(c.get("level_id"), menu),
                          "trigger": c.get("trigger")}
                         for c in a.get("plan_clauses") or []
                         if isinstance(c, dict)]
    exp = a.get("expectation") if isinstance(a.get("expectation"),
                                             dict) else {}
    a["expectation"] = {"kind": exp.get("kind"),
                        "level_id": keep(exp.get("level_id"), menu)}
    return a


def _verdict_v1(words) -> dict:
    from bot_program.orcs.constants import V_RULES
    verdicts = {r: "n/a" for r in V_RULES}
    verdicts["V1"] = f"refused: {words}"
    return {"status": "refused", "rule": "V1", "verdicts": verdicts,
            "refusals": [{"rule": "V1", "part": "whole", "words": words}],
            "answer": None, "level": None, "would_stop": None,
            "share": None, "clauses": [], "expectation": None,
            "next_wake_min": 0, "schema_version": SCHEMA_VERSION}


def judge(wake, reply, *, now) -> dict:
    """What the call came back with, read: the outcome the settle writes.
    The parse, V1-V14 and the officer's would-verdict, with no lock held
    (N8). Never raises: an answer that cannot be judged is refused."""
    from bot_program.orcs import mandate, validator
    from bot_program.orcs.models import Orc
    from bot_program.orcs.sessions import trading_day
    outcome = {k: reply.get(k) for k in ("kind", "code", "usage", "rung",
                                         "model", "error", "latency",
                                         "stop_reason", "why")}
    outcome["validated_at"] = now.isoformat()
    kind = reply.get("kind")
    if kind == REPLY_BILLED:
        words = (validator.WORDS["V1_cut"]
                 if reply.get("stop_reason") == "max_tokens"
                 else validator.WORDS["V1_empty"])
        outcome["verdict"] = _verdict_v1(words)
        return outcome
    if kind != REPLY_ANSWER:
        return outcome
    comps = wake.components if isinstance(wake.components, dict) else {}
    vctx = comps.get("vctx") if isinstance(comps.get("vctx"), dict) else {}
    from django.utils.dateparse import parse_datetime
    try:
        orc = Orc.objects.select_related("root_trade").get(pk=wake.orc_id)
        trade = orc.root_trade
        # the facts index as of the wake's own moment (A.35): what its
        # dossier showed, never a fact written since
        as_of = parse_datetime(str(comps.get("as_of") or "")) or now
        facts = validator.facts_index(orc, as_of=as_of, vctx=vctx)
        verdict = validator.validate(
            reply.get("text"), stop_reason=reply.get("stop_reason"),
            vctx=vctx, facts=facts,
            plan_changes=orc.plan_changes_24h,
            plan_version=orc.plan_version,
            plan_at=(orc.plan or {}).get("at") if isinstance(orc.plan,
                                                             dict) else None,
            reasons=wake.reasons, symbol=orc.symbol, side=orc.side, now=now,
            marks=_marks(trade), precision=_precision(trade))
    except Exception as e:  # noqa: BLE001 — never lose the booking
        logger.warning("[orcs] wake %s: the answer could not be judged: %s",
                       wake.pk, e)
        outcome["verdict"] = _verdict_v1(validator.WORDS["V1"])
        return outcome
    outcome["verdict"] = verdict
    answer = verdict.get("answer") or {}
    action = answer.get("action")
    outcome["kept"] = _kept(answer, vctx) if answer else None
    if action not in INTENT_KINDS:
        return outcome
    day = trading_day(now).isoformat()
    bars = list(vctx.get("decision_bars") or [])
    # the proposal's ids are the answer AS KEPT (N5; 2026-11-05, completing
    # O2a): an answer refused whole is stored and shown too (A.41), so a
    # candidate or an event that is not one of the wake's own reads
    # "unknown", never the model's text
    kept = outcome["kept"] or {}
    intent = {"kind": action, "candidate": str(kept.get("candidate") or ""),
              "level": verdict.get("level") or {},
              "would_stop": verdict.get("would_stop"),
              "event_id": (str(kept.get("event_id") or "")
                           if action == "lock_waive" else ""),
              "share": verdict.get("share"),
              "facts_cited": list(kept.get("facts_cited") or [])}
    if verdict["status"] != WAKE_STATUS_DONE:
        intent.update(mode=MODE_REFUSED, status=INTENT_STATUS_REFUSED,
                      rule=verdict.get("rule") or "", officer={},
                      why=_words_of(verdict))
        outcome["intent"] = intent
        return outcome
    from bot_program.orcs.situation import exotic_legs
    try:
        legs = exotic_legs(trade)
    except Exception:  # noqa: BLE001 — unread legs are none
        legs = []
    officer = mandate.judge(orc, action=action, vctx=vctx, facts=facts,
                            cited=intent["facts_cited"],
                            share=verdict.get("share"),
                            event_id=intent["event_id"], day=day,
                            exotic_legs=legs)
    intent["officer"] = officer
    if officer["verdict"] == OFFICER_REFUSE:
        intent.update(mode=MODE_REFUSED, status=INTENT_STATUS_REFUSED,
                      rule=officer["rule"], why=officer["words"][:200])
    else:
        if action == "add":
            intent["share"] = officer.get("share")
        care_owned = orc.state == STATE_CARE_OWNED
        queued = action != "add" and not care_owned
        intent.update(mode=MODE_SHADOW,
                      status=(INTENT_STATUS_QUEUED if queued
                              else INTENT_STATUS_RECORDED),
                      rule="",
                      why=("queued for the shadow arm" if queued else
                           "the care holds the position: recorded"
                           if care_owned else "an add: judged, never applied"),
                      expires_at=(now + timedelta(seconds=INTENT_TTL_S)
                                  if queued else None))
        outcome["accept"] = {"action": action, "day": day,
                             "bar": bars[-1] if bars else None}
    outcome["intent"] = intent
    return outcome


def judge_probe(wake, reply, *, now) -> dict:
    """B.11 (O2b's probes, 2026-11-06): a probe's answer through the same
    validator as the wake's (V1-V14), with no lock held, BLIND to the
    routed answer: as of the wake's own moment (its validation context,
    the facts its dossier showed), on the Orc's plan as that context read
    it (vctx's plan_version and plan_at, and the 24-hour plan changes made
    before the wake's claim), so the routed answer's own plan change never
    judges the probe. The officer is not asked: a pair compares answers,
    and the officer's day counters already hold the routed answer's. One
    side of the pair: {action, level_id (kept as _kept keeps it: an id
    only when it names the wake's own menu), valid, rule, stop (a
    tighten's would-stop, a price), at}; nothing of its note. A billed
    failure, or an answer that cannot be judged, is invalid (V1). Never
    raises."""
    from django.utils.dateparse import parse_datetime

    from bot_program.orcs import validator
    from bot_program.orcs.models import Orc
    side = {"action": "", "level_id": "", "valid": False, "rule": "V1",
            "stop": None, "at": now.isoformat()}
    if reply.get("kind") != REPLY_ANSWER:
        return side
    comps = wake.components if isinstance(wake.components, dict) else {}
    vctx = comps.get("vctx") if isinstance(comps.get("vctx"), dict) else {}
    try:
        orc = Orc.objects.select_related("root_trade").get(pk=wake.orc_id)
        trade = orc.root_trade
        as_of = parse_datetime(str(comps.get("as_of") or "")) or now
        facts = validator.facts_index(orc, as_of=as_of, vctx=vctx)
        claimed = wake.started_at or as_of
        before = []
        for change in orc.plan_changes_24h or []:
            at = (parse_datetime(str(change.get("at") or ""))
                  if isinstance(change, dict) else None)
            if at is not None and at < claimed:
                before.append(change)
        verdict = validator.validate(
            reply.get("text"), stop_reason=reply.get("stop_reason"),
            vctx=vctx, facts=facts, plan_changes=before,
            plan_version=vctx.get("plan_version"),
            plan_at=vctx.get("plan_at"), reasons=wake.reasons,
            symbol=orc.symbol, side=orc.side, now=wake.finished_at or now,
            marks=_marks(trade), precision=_precision(trade))
    except Exception as e:  # noqa: BLE001 — an unjudged probe is invalid
        logger.warning("[orcs] wake %s: a probe's answer could not be "
                       "judged: %s", wake.pk, e)
        return side
    answer = verdict.get("answer") or {}
    kept = _kept(answer, vctx) if answer else {}
    action = str(kept.get("action") or "")
    action = action if action in ACTIONS else ""
    stop = verdict.get("would_stop") if action == "tighten" else None
    side.update(action=action,
                level_id=str(kept.get("level_id") or "") if answer else "",
                valid=verdict.get("status") == WAKE_STATUS_DONE,
                rule=str(verdict.get("rule") or ""),
                stop=float(stop) if stop is not None else None)
    return side


def _words_of(verdict) -> str:
    for r in verdict.get("refusals") or []:
        if r.get("part") == "whole":
            return str(r.get("words") or "")[:200]
    return ""


def _marks(trade):
    from bot_program.orcs.plain import row_marks
    return row_marks(trade)


def _precision(trade) -> int:
    try:
        from core.price_format import price_decimals
        return int(price_decimals(trade.entry_price, trade.asset_class,
                                  trade.symbol))
    except Exception:  # noqa: BLE001 — eight places when unread
        return 8


# ── the writes, inside the settle (database writes only) ─────────────────

def _booking(outcome) -> dict:
    usage = outcome.get("usage") if isinstance(outcome.get("usage"),
                                               dict) else None
    if usage is None:
        return {}
    return {"model": str(usage.get("model") or outcome.get("model") or "")
            [:50],
            "tokens_in": int(usage.get("input_tokens") or 0),
            "tokens_out": int(usage.get("output_tokens") or 0),
            "cache_read": int(usage.get("cache_read_input_tokens") or 0),
            "cache_write": int(usage.get("cache_creation_input_tokens")
                               or 0),
            "cost_usd": Decimal(str(round(float(usage.get("cost_usd")
                                                or 0), 6)))}


def decision_words(target, verdict) -> str:
    answer = (verdict or {}).get("answer") or {}
    action = str(answer.get("action") or "")
    if action in ACTION_WORDS:
        return ACTION_WORDS[action]
    return intent_words(target, {"kind": action,
                                 "level": verdict.get("level"),
                                 "event_id": answer.get("event_id")})


def _body(w, outcome, **extra) -> dict:
    verdict = outcome.get("verdict") if isinstance(outcome.get("verdict"),
                                                   dict) else {}
    intent = outcome.get("intent") if isinstance(outcome.get("intent"),
                                                 dict) else {}
    return {"wake": w.pk, "rung": str(outcome.get("rung") or ""),
            "answer": outcome.get("kept"),
            "verdicts": verdict.get("verdicts") or {},
            "officer": intent.get("officer") or {},
            "status": verdict.get("status") or "",
            "rule": verdict.get("rule") or "",
            "expectation": verdict.get("expectation"),
            "s_version": S_VERSION, "schema_version": SCHEMA_VERSION,
            "latency": outcome.get("latency"), **extra}


def _minds_switch_on() -> bool:
    from bot_program.orcs.switches import _component_on
    return _component_on(MINDS_SWITCH)


def write_outcome(locked, w, outcome, *, now, fields, keys) -> None:
    """The outcome's writes inside the settle (A.25, A.39-A.41): sets the
    wake's status and code in memory (the settle saves it)."""
    from bot_program.orcs import journal
    kind = outcome.get("kind")
    code = str(outcome.get("code") or "")
    if kind == REPLY_CLOSED:
        # a gate closed before the send: answered by code (A.5), a
        # budget entry only while the minds switch itself is on
        w.status, w.skipped_reason = WAKE_STATUS_SKIPPED, code
        if _minds_switch_on():
            journal.append(locked, "budget", f"Answered by code: "
                           f"{WAKE_CODE_WORDS.get(code, code)}.",
                           body={"wake": w.pk, "code": code,
                                 "why": outcome.get("why") or ""},
                           wake=w, card=False, at=now, fields=fields,
                           remember=keys)
        else:
            journal.remember(locked, fields=fields, **keys)
        return
    if kind in (REPLY_UNSENT, REPLY_UNBILLED):
        w.status, w.skipped_reason = WAKE_STATUS_FAILED, code
        text = ("The model call was refused before it was sent: nothing "
                "was billed." if kind == REPLY_UNSENT else
                "The model call failed with no bill: its bound stays held "
                "until 00:00 UTC.")
        journal.append(locked, "error", text,
                       body={"wake": w.pk, "code": code,
                             "rung": str(outcome.get("rung") or ""),
                             "error": str(outcome.get("error") or "")[:300],
                             "held": kind == REPLY_UNBILLED},
                       wake=w, at=now, fields=fields, remember=keys)
        return
    verdict = outcome.get("verdict") if isinstance(outcome.get("verdict"),
                                                   dict) else {}
    if verdict.get("status") != WAKE_STATUS_DONE:
        _write_refused(locked, w, outcome, verdict, now=now, fields=fields,
                       keys=keys)
        return
    _write_done(locked, w, outcome, verdict, now=now, fields=fields,
                keys=keys)


def _write_refused(locked, w, outcome, verdict, *, now, fields, keys):
    from bot_program.orcs import journal, validator
    rule = verdict.get("rule") or "V1"
    w.status, w.skipped_reason = WAKE_STATUS_REFUSED, rule
    decision = journal.append(
        locked, "decision", f"Decision in shadow, refused by the validator "
        f"({rule}).", author="orc", body=_body(w, outcome), wake=w, at=now,
        booking=_booking(outcome), fields=fields, remember=keys)
    for r in verdict.get("refusals") or []:
        journal.append(locked, "refusal", validator.refusal_headline(
            r["rule"], r["words"]),
            body={"rule": r["rule"], "part": r["part"], "words": r["words"],
                  "wake": w.pk, "decision": decision.pk}, wake=w, at=now)
    intent = outcome.get("intent")
    if isinstance(intent, dict):
        _write_intent(locked, w, outcome, intent, decision, now=now)


def _plan_writes(locked, w, outcome, verdict, decision, *, now) -> None:
    """A.39: a done revision writes the plan, its version, its 24-hour
    change list and the watches, with prices from the wake's menu, and a
    `plan` entry drawn by code."""
    from bot_program.orcs import journal, notes
    from bot_program.orcs.validator import plan_window, urgent_for_plan
    clauses = list(verdict.get("clauses") or [])
    version = int(locked.plan_version or 0) + 1
    plan = {"v": version, "at": now.isoformat(), "wake": w.pk,
            "decision": decision.pk, "clauses": clauses,
            "expectation": verdict.get("expectation"), "s": S_VERSION,
            "schema": SCHEMA_VERSION}
    changes = plan_window(locked.plan_changes_24h, now) + [
        {"at": now.isoformat(), "urgent": urgent_for_plan(w.reasons)}]
    watches = [{"level_id": c.get("level_id"), "kind": c.get("kind"),
                "tf": c.get("tf"), "price": c.get("price"),
                "stop": c.get("stop"), "side": c.get("side"),
                "clause": c.get("clause")} for c in clauses]
    locked.plan = plan
    line = notes.plan_line(locked)
    journal.append(locked, "plan", f"Plan v{version} in shadow: {line}.",
                   author="orc", body={"plan": plan, "wake": w.pk,
                                       "decision": decision.pk},
                   wake=w, at=now,
                   fields={"plan": plan, "plan_version": version,
                           "plan_changes_24h": changes[-50:],
                           "watches": watches})


def _write_done(locked, w, outcome, verdict, *, now, fields, keys):
    from bot_program.orcs import journal, mandate, validator
    w.status, w.skipped_reason = WAKE_STATUS_DONE, ""
    answer = verdict.get("answer") or {}
    note = str(answer.get("note") or "")
    comps = w.components if isinstance(w.components, dict) else {}
    done = dict(fields)
    done["last_good_wake_at"] = now
    if comps.get("facts_hash"):
        done["last_facts_hash"] = str(comps["facts_hash"])[:64]
    if note:
        done["latest_note"] = note[:140]
        done["latest_note_at"] = now
    remember = dict(keys)
    # A.49 (P23): a next_wake_min that passed V9 asks for a wake at the
    # answer's time plus n minutes; W11 fires it at the first open-market
    # tick at or after then (wake._w11), and the next wake is due at the
    # earlier of the metronome and the ask
    asked = int(verdict.get("next_wake_min") or 0)
    if asked:
        ask = now + timedelta(minutes=asked)
        remember[W11_ASK_KEY] = ask.isoformat()
        due = locked.next_wake_due
        done["next_wake_due"] = ask if due is None or ask < due else due
    accept = outcome.get("accept")
    if isinstance(accept, dict):
        remember["officer"] = (lambda cur, a=accept: mandate.accept(
            cur, action=a["action"], day=a["day"], bar=a["bar"]))
    decision = journal.append(
        locked, "decision", f"Decision in shadow: "
        f"{decision_words(locked, verdict)}.", author="orc",
        body=_body(w, outcome), wake=w, at=now, booking=_booking(outcome),
        fields=done, remember=remember)
    if (answer.get("action") == "revise_plan"):
        _plan_writes(locked, w, outcome, verdict, decision, now=now)
    for r in verdict.get("refusals") or []:
        journal.append(locked, "refusal", validator.refusal_headline(
            r["rule"], r["words"]),
            body={"rule": r["rule"], "part": r["part"], "words": r["words"],
                  "wake": w.pk, "decision": decision.pk}, wake=w, at=now)
    intent = outcome.get("intent")
    if isinstance(intent, dict):
        _write_intent(locked, w, outcome, intent, decision, now=now)


def _write_intent(locked, w, outcome, intent, decision, *, now) -> None:
    """One OrcIntent and its `intent` entry (A.41), the card's newest
    three rewritten in the same append; a queued one's id joins
    seen["intents_queued"]; an officer's refusal writes its refusal."""
    from bot_program.orcs import journal, validator
    from bot_program.orcs.models import OrcIntent
    level = intent.get("level") if isinstance(intent.get("level"),
                                              dict) else {}
    stop = intent.get("would_stop")
    row_ = OrcIntent.objects.create(
        orc_id=locked.pk, wake=w, decision=decision, kind=intent["kind"],
        candidate=str(intent.get("candidate") or "")[:16],
        level_id=str(level.get("level_id") or "")[:24], level=level,
        would_stop=(Decimal(str(round(float(stop), 8)))
                    if stop is not None else None),
        event_id=str(intent.get("event_id") or "")[:16],
        share=intent.get("share"),
        facts_cited=list(intent.get("facts_cited") or []),
        mode=intent["mode"], rule=str(intent.get("rule") or "")[:16],
        officer=dict(intent.get("officer") or {}), status=intent["status"],
        why=str(intent.get("why") or "")[:200],
        expires_at=intent.get("expires_at"),
        rung=str(outcome.get("rung") or "")[:4], s_version=S_VERSION,
        schema_version=SCHEMA_VERSION)
    words = intent_words(locked, intent)
    card = locked.card if isinstance(locked.card, dict) else {}
    shown = [i for i in card.get("intents") or [] if isinstance(i, dict)]
    shown = (shown + [{"kind_t": f"proposed in shadow: {words}",
                       "mode": row_.mode,
                       "status_t": STATUS_T.get(row_.status,
                                                row_.status)}])[-CARD_INTENTS:]
    remember = {}
    if row_.status == INTENT_STATUS_QUEUED:
        remember["intents_queued"] = (
            lambda cur, pk=row_.pk: [x for x in (cur or [])
                                     if isinstance(x, int)] + [pk])
    journal.append(locked, "intent", f"Proposed in shadow: {words}.",
                   author="orc",
                   body={"intent": row_.pk, "kind": row_.kind,
                         "mode": row_.mode, "status": row_.status,
                         "rule": row_.rule, "wake": w.pk,
                         "decision": decision.pk},
                   wake=w, at=now, card_extra={"intents": shown},
                   remember=remember)
    officer = intent.get("officer") or {}
    if officer.get("verdict") == OFFICER_REFUSE:
        journal.append(locked, "refusal", validator.refusal_headline(
            officer["rule"], officer["words"], officer=True),
            body={"rule": officer["rule"], "part": "officer",
                  "words": officer["words"], "wake": w.pk,
                  "decision": decision.pk, "intent": row_.pk},
            wake=w, at=now)


def write_late(locked, w, outcome, *, now, code, fields, keys) -> None:
    """A.26: the answer came back after the row closed, the Orc died or a
    gate went OFF: booked, journaled as late, nothing else written."""
    from bot_program.orcs import journal
    w.status, w.skipped_reason = WAKE_STATUS_LATE, code
    journal.append(locked, "decision", f"Decision in shadow, late: "
                   f"{WAKE_CODE_WORDS.get(code, code)}; nothing applied.",
                   author="orc", body=_body(w, outcome, late=True, code=code),
                   wake=w, at=now, booking=_booking(outcome), fields=fields,
                   remember=keys)


def write_intellect(locked, w, outcome) -> None:
    """A.62, at the settle, inside its transaction (database writes only):
    the card's intellect says how wake `w` was answered (its status words)
    and, once a model was sent it, the rung in tier words (rung_t, which
    think() read before the locks). Written only while the card's
    intellect is this wake's: a newer render's is left as it is."""
    from bot_program.orcs import journal, notes
    from bot_program.orcs.constants import WAKE_STATUS_LATE as LATE
    it = notes.intellect_after(
        locked.card, w.pk,
        status_t=notes.wake_status_t(w.status, w.skipped_reason),
        rung_t=outcome.get("rung_t") or RUNG_NONE, late=w.status == LATE)
    if it is not None:
        journal.remember(locked, card_extra={"intellect": it})


#: A late settle's words (A.24, A.25, A.55), by what came back: a bill
#: with its ledger row, a bill with none (held as `ledger_gap`), no bill
#: (the orphan hold kept, or already ended at 00:00 UTC), nothing sent
#: (released). Code's fixed words.
LATE_SETTLE_WORDS = {
    "booked": "A call that ran past its wall time came back: its cost is "
              "booked, nothing applied.",
    "ledger_gap": "A call that ran past its wall time came back: its cost "
                  "is booked and held until 00:00 UTC (the provider wrote "
                  "no ledger row), nothing applied.",
    "unbilled": "A call that ran past its wall time came back with no "
                "bill: its bound stays held until 00:00 UTC, nothing "
                "applied.",
    "unbilled_ended": "A call that ran past its wall time came back with "
                      "no bill after its hold ended at 00:00 UTC, nothing "
                      "applied.",
    "unsent": "A call that ran past its wall time was never sent: its "
              "bound is released, nothing applied.",
}


def write_late_settle(locked, w, outcome, *, now, fields, keys,
                      held="") -> None:
    """A.55: a settle on a wake that is no longer running (its wall time
    closed it): the real cost booked on an error entry, nothing else. Its
    words say what became of the orphan hold (`held`, the settle's: the
    kind kept, or "" released; 2026-11-05, completing O2a)."""
    from bot_program.orcs import journal
    kind = str(outcome.get("kind") or "")
    if isinstance(outcome.get("usage"), dict):
        words = LATE_SETTLE_WORDS["ledger_gap" if held else "booked"]
    elif kind in (REPLY_CLOSED, REPLY_UNSENT):
        words = LATE_SETTLE_WORDS["unsent"]
    else:
        words = LATE_SETTLE_WORDS["unbilled" if held else "unbilled_ended"]
    journal.append(locked, "error", words,
                   body={"wake": w.pk, "late_settle": True,
                         "rung": str(outcome.get("rung") or ""),
                         "kind": kind, "code": str(outcome.get("code") or ""),
                         "held": str(held or "")},
                   wake=w, at=now, booking=_booking(outcome), fields=fields,
                   remember=keys)
