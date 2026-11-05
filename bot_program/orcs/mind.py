"""ONE CLAIMED WAKE, READ IN SHADOW (the O2 spec A.23-A.26, A.39-A.41;
O2a, 2026-11-05). Nothing reaches it in production yet: no wake is ever
claimed until the queue is built and the operator turns the minds on.

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
  write_*        the outcome's writes, called by the settle inside its one
                 transaction: database writes only. A done answer writes
                 its decision (with the booking), its plan (a revision),
                 its proposals (OrcIntent, one per proposal that is not a
                 hold), the filtered note, last_good_wake_at and
                 last_facts_hash; a refused one its decision and its
                 refusal; a late one its decision only (A.26)

Every proposal is in shadow: an OrcIntent is judged, queued for the Orc's
own arm or recorded, and never sent anywhere. Its level is the stored
reference copied from the wake's menu, never a model's price (A.30)."""
import logging
import re
from datetime import timedelta
from decimal import Decimal

from bot_program.orcs.constants import (CODE_UNSENT, INTENT_KINDS,
                                        REPLY_ANSWER, REPLY_BILLED,
                                        REPLY_CLOSED, REPLY_UNBILLED,
                                        REPLY_UNSENT,
                                        INTENT_STATUS_QUEUED,
                                        INTENT_STATUS_RECORDED,
                                        INTENT_STATUS_REFUSED, INTENT_TTL_S,
                                        MINDS_SWITCH, MODE_REFUSED,
                                        MODE_SHADOW, O2A_RUNG,
                                        OFFICER_REFUSE,
                                        S_VERSION, SCHEMA_VERSION,
                                        SMOKE_VERDICT_KEY, STATE_CARE_OWNED,
                                        WAKE_CODE_WORDS, WAKE_STATUS_DONE,
                                        WAKE_STATUS_FAILED, WAKE_STATUS_LATE,
                                        WAKE_STATUS_REFUSED,
                                        WAKE_STATUS_SKIPPED)

logger = logging.getLogger(__name__)

#: The caller of a wake's call (§1.0.9) and its source_ref's word.
CALLER = "wake"
#: A fact id as the answer may cite one (F41, DR3).
FACT_ID = re.compile(r"(?:F|DR)\d{1,6}")
#: The proposals' words (A.41): "tighten to S4h-L1 (2,612.00)".
INTENT_WORDS = {"tighten": "tighten to {lv}", "trim": "trim at {lv}",
                "exit": "exit at {lv}", "lock_waive": "waive the lock for {ev}",
                "add": "add at {lv}"}
ACTION_WORDS = {"hold": "hold", "revise_plan": "revise the plan"}
#: An intent's status on the card (A.41, A.62).
STATUS_T = {INTENT_STATUS_QUEUED: "queued for the shadow arm",
            INTENT_STATUS_RECORDED: "recorded, never applied",
            INTENT_STATUS_REFUSED: "would be refused",
            "simulated": "applied to the shadow arm",
            "expired": "expired"}
#: The card keeps the newest intents (A.41).
CARD_INTENTS = 3


def source_ref(wake, rung, caller=CALLER) -> str:
    """`Orc:<pk>:Wake:<w>:<rung>` (§1.0.9): the Orcs line's own prefix."""
    word = "Wake" if caller == CALLER else str(caller).capitalize()
    return f"Orc:{wake.orc_id}:{word}:{wake.pk}:{rung}"


# ── the request (A.23) ───────────────────────────────────────────────────

def smoke_pass(family) -> bool:
    """The smoke's recorded verdict for `family` is a PASS (A.61)."""
    from bot_program.orcs.models import OrcSetting
    verdicts = OrcSetting.get(SMOKE_VERDICT_KEY) or {}
    entry = verdicts.get(family) if isinstance(verdicts, dict) else None
    return isinstance(entry, dict) and str(entry.get("verdict") or "") \
        .lower() == "pass"


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


# ── one wake ─────────────────────────────────────────────────────────────

def _real_urgent(wake) -> bool:
    vctx = (wake.components or {}).get("vctx") or {}
    return vctx.get("world") == "live" and bool(vctx.get("urgent"))


def think(wake, *, now=None) -> dict:
    """Read one CLAIMED (running) wake: build the request, call once
    through the gateway, judge the answer, settle. No lock is held but
    the settle's own. Returns the settle's result."""
    from django.utils import timezone

    from bot_program.orcs import mind_gateway, scheduler
    comps = wake.components if isinstance(wake.components, dict) else {}
    rung_name = str(comps.get("rung") or O2A_RUNG)
    ref = source_ref(wake, rung_name)
    try:
        request = build_request(wake, rung_name)
    except (ValueError, KeyError, TypeError) as e:
        reply = {"kind": REPLY_UNSENT, "sent": False, "code": CODE_UNSENT,
                 "why": "", "text": None, "usage": None,
                 "error": f"{type(e).__name__}: {e}"[:300],
                 "rung": rung_name, "model": "", "latency": 0.0,
                 "stop_reason": None}
    else:
        bound_usd = float(wake.est_usd or 0) or mind_gateway.bound(
            rung_name, comps.get("tokens"))
        reply = mind_gateway.call(caller=CALLER, rung_name=rung_name,
                                  request=request, source_ref=ref,
                                  bound_usd=bound_usd, exclude_wake=wake.pk,
                                  real_urgent=_real_urgent(wake))
    now = now or timezone.now()
    outcome = judge(wake, reply, now=now)
    outcome["source_ref"] = ref
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
    intent = {"kind": action, "candidate": answer.get("candidate") or "",
              "level": verdict.get("level") or {},
              "would_stop": verdict.get("would_stop"),
              "event_id": (answer.get("event_id") if action == "lock_waive"
                           else ""),
              "share": verdict.get("share"),
              "facts_cited": list((outcome["kept"] or {}).get("facts_cited")
                                  or [])}
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


def _level_words(target, level) -> str:
    from bot_program.orcs.facts import px
    level = level if isinstance(level, dict) else {}
    if not level.get("level_id"):
        return "market"
    return f"{level['level_id']} ({px(target, level.get('price'))})"


def intent_words(target, intent) -> str:
    """A proposal in fixed words, its price drawn by code (A.41)."""
    tpl = INTENT_WORDS.get(str(intent.get("kind") or ""), "{lv}")
    return tpl.format(lv=_level_words(target, intent.get("level")),
                      ev=intent.get("event_id") or "—")


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


def write_late_settle(locked, w, outcome, *, now, fields, keys) -> None:
    """A.55: a settle on a wake that is no longer running (its wall time
    closed it): the real cost booked on an error entry, nothing else."""
    from bot_program.orcs import journal
    journal.append(locked, "error", "A call that ran past its wall time "
                   "came back: its cost is booked, nothing applied.",
                   body={"wake": w.pk, "late_settle": True,
                         "rung": str(outcome.get("rung") or ""),
                         "kind": str(outcome.get("kind") or "")},
                   wake=w, at=now, booking=_booking(outcome), fields=fields,
                   remember=keys)
