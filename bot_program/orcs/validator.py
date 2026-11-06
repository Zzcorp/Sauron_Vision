"""THE VALIDATOR (the O2 spec A.30-A.35; O2a, 2026-11-05): pure but for the
facts index's one journal read.

A model's answer is text, never a fact, money or an instruction (N5). It
is kept only after code has read it against the wake's validation
context (OrcWake.components["vctx"], written by the render as of the
dossier), the Orc's journal and the Orc row's own counters:

  SCHEMA_V1     the answer's JSON schema, by the raw API's rules: every key
                required, additionalProperties false, no bound keyword, no
                field named reasoning, thinking or trace, no per-Orc enum
  shape         the hand-written check of that schema (V1): jsonschema is
                not pinned
  facts_index   A.35: {fact id: {kind, symbol, at, event, drum_kind}} from
                the Orc's journal up to the wake's as-of moment
  validate      V1-V14 in A.31's order and classes. V1-V8, V10, V12, V13
                and V14 refuse the whole answer; V9 drops the asked wake
                and V11 withholds the note, the rest standing
  refusal       A.33: a refusal entry's headline and body, in fixed words

The model names ids; code stores prices. Every level the answer names is
kept as the reference {level_id, kind, tf, price, stop} copied from the
wake's own menu (vctx["menu"]): a menu id names a price only within one
build of the menu, so no later use resolves the id again (A.30).
"""
import json
import math
import unicodedata
from datetime import timedelta

from bot_program.orcs.constants import (ACTIONS, CLAUSE_KINDS,
                                        CLAUSE_TRIGGERS, EXPECTATION_KINDS,
                                        FENCE_CAPS, MAX_LEVEL_DIST_ATR4H,
                                        MIN_STOP_ROOM_ATR, NEXT_WAKE_MAX_MIN,
                                        NEXT_WAKE_MIN_MIN,
                                        NOTE_NON_LATIN1_MAX,
                                        PLAN_CHANGES_24H_MAX,
                                        PLAN_CLAUSES_MAX, PLAN_WINDOW_H,
                                        REACHED_KINDS, RISK_SHARE_WORDS,
                                        SCHEMA_VERSION, TRIM_SHARE, V_PART,
                                        V_RULES, V_WHOLE)

#: The answer's keys, in the schema's order (A.30).
KEYS = ("action", "candidate", "level_id", "risk_share", "facts_cited",
        "event_id", "plan_clauses", "expectation", "next_wake_min", "note")
NONE = "none"


def _str(**extra) -> dict:
    return {"type": "string", **extra}


#: A.30: one object for every Orc and every model (the cache key holds
#: the schema, so it never varies per Orc: code checks the ids after).
SCHEMA_V1 = {
    "type": "object",
    "additionalProperties": False,
    "required": list(KEYS),
    "properties": {
        "action": _str(enum=list(ACTIONS)),
        "candidate": _str(),
        "level_id": _str(),
        "risk_share": _str(enum=list(RISK_SHARE_WORDS)),
        "facts_cited": {"type": "array", "items": _str()},
        "event_id": _str(),
        "plan_clauses": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["kind", "level_id", "trigger"],
            "properties": {"kind": _str(enum=list(CLAUSE_KINDS)),
                           "level_id": _str(),
                           "trigger": _str(enum=list(CLAUSE_TRIGGERS))}}},
        "expectation": {
            "type": "object", "additionalProperties": False,
            "required": ["kind", "level_id"],
            "properties": {"kind": _str(enum=list(EXPECTATION_KINDS)),
                           "level_id": _str()}},
        "next_wake_min": {"type": "integer"},
        "note": _str(),
    },
}

#: The validator's own words for each rule (A.33): fixed, never a model's
#: text, never "advisory to the phone".
WORDS = {
    "V1": "the answer is not one JSON object of the schema's keys, types "
          "and values",
    "V1_cut": "the answer was cut off at its bound",
    "V1_empty": "the call ended without an answer",
    "V2": "the plan already changed twice in 24 hours; a wake that is not "
          "urgent may not change it again",
    "V3": "the action is not on PS1's allowed list",
    "V4": "the candidate is not on the list, or its action or level "
          "differs",
    "V5": "the action names no level of the menu",
    "V5_none": "this action needs a level of the menu",
    "V6": "an exit or trim with the thesis intact needs a level the price "
          "reached, and its level_reached fact cited",
    "V7_own": "a tighten names a level with a stop of its own; CARE and EFF "
              "are the care's",
    "V7_room": "the would-stop needs 0.5 ATR of room from the price and "
               "the closing-side mark",
    "V7_far": "the would-stop is more than 3 ATR(4h) from the mark",
    "V7_tighter": "the would-stop is not tighter than the effective stop",
    "V8": "F5 holds a critical input: only hold, a plan revision and a "
          "tighten on a fresh mark",
    "V9": "an asked wake is 0, or 15 to 480 minutes: the request is "
          "dropped",
    "V10": "the action cites no fact of its relevance set",
    "V11_money": "the note may name an amount of money: withheld",
    "V11_error": "the note quotes an error: withheld",
    "V11_instruction": "the note reads as an instruction: withheld",
    "V11_script": "the note is mostly outside plain English letters: "
                  "withheld",
    "V12": "a plan revision holds 1 to 4 clauses, each on a watchable menu "
           "level",
    "V12_add": "an add clause needs add on PS1's allowed list",
    "V12_other": "only a plan revision sends clauses",
    "V13": "the expectation names no level of the menu",
    "V14": "a lock waiver names an event of PS1; no other action names one",
}
#: The words a withheld note is replaced by (V11).
NOTE_WITHHELD = "Withheld by the validator."


# ── the shape (V1) ───────────────────────────────────────────────────────

def _is_str(x) -> bool:
    return isinstance(x, str)


def _is_int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def shape(text) -> tuple:
    """(answer, "") when `text` is one JSON object of SCHEMA_V1's exact
    keys, types and values; (None, why) otherwise. Hand-written, like
    claude_smoke.validate_decision; the why is code's own words."""
    try:
        data = json.loads(str(text or ""))
    except (TypeError, ValueError):
        return None, "not JSON"
    if not isinstance(data, dict):
        return None, "not a JSON object"
    if set(data) != set(KEYS):
        return None, "not the schema's keys"
    props = SCHEMA_V1["properties"]
    for key in ("action", "risk_share"):
        if not _is_str(data[key]) or data[key] not in props[key]["enum"]:
            return None, f"{key} is off the schema"
    for key in ("candidate", "level_id", "event_id", "note"):
        if not _is_str(data[key]):
            return None, f"{key} is not a string"
    if not (isinstance(data["facts_cited"], list)
            and all(_is_str(f) for f in data["facts_cited"])):
        return None, "facts_cited is not a list of strings"
    if not _is_int(data["next_wake_min"]):
        return None, "next_wake_min is not an integer"
    clauses = data["plan_clauses"]
    if not isinstance(clauses, list):
        return None, "plan_clauses is not a list"
    for c in clauses:
        if not isinstance(c, dict) or set(c) != {"kind", "level_id",
                                                 "trigger"}:
            return None, "a plan clause is not the schema's object"
        if c["kind"] not in CLAUSE_KINDS or c["trigger"] not in \
                CLAUSE_TRIGGERS or not _is_str(c["level_id"]):
            return None, "a plan clause is off the schema"
    exp = data["expectation"]
    if not isinstance(exp, dict) or set(exp) != {"kind", "level_id"} or \
            exp["kind"] not in EXPECTATION_KINDS or \
            not _is_str(exp["level_id"]):
        return None, "the expectation is off the schema"
    return data, ""


# ── the facts index (A.35) ───────────────────────────────────────────────

def _event_of(body, events) -> str:
    """A calendar fact's event: its code id (C-n), matched on the print's
    time in the wake's events, never on its title (map_wakes trap 14). A
    gap fact names its event itself."""
    if body.get("event"):
        return str(body["event"])
    at = str(body.get("at") or "")
    for code, ev in (events or {}).items():
        if at and str((ev or {}).get("at") or "") == at:
            return str(code)
    return ""


def facts_index(orc, *, as_of, vctx=None) -> dict:
    """{fact id: {kind, symbol, at, event, drum_kind, level}} from the
    Orc's journal facts written up to `as_of`. `kind` is
    fence.fact_kind; `symbol` the Orc's own, or a drum's body["symbol"]
    (a correlate's drum fails V10's symbol test by design); `event` the
    calendar row's code id; `level` a level_reached fact's reference."""
    from bot_program.orcs import fence
    from bot_program.orcs.models import OrcJournal
    events = (vctx or {}).get("events") or {}
    out = {}
    qs = OrcJournal.objects.filter(orc_id=orc.pk).exclude(fact_id="")
    if as_of is not None:
        qs = qs.filter(at__lte=as_of)
    for e in qs.only("fact_id", "kind", "author", "body", "at"):
        body = e.body if isinstance(e.body, dict) else {}
        kind = fence.fact_kind(e)
        out[e.fact_id] = {
            "kind": kind,
            "symbol": (str(body.get("symbol") or "") if e.kind == "drum"
                       else str(body.get("symbol") or orc.symbol)),
            "at": e.at.isoformat() if e.at else "",
            "event": (_event_of(body, events)
                      if kind in ("calendar", "gap") else ""),
            "drum_kind": str(body.get("drum_kind") or ""),
            "level": ({k: body.get(k) for k in ("level_id", "kind", "tf",
                                                "price")}
                      if kind == "level_reached" else None)}
    return out


# ── the checks ───────────────────────────────────────────────────────────

def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _sign(side) -> int:
    return 1 if str(side or "").upper() == "BUY" else -1


def _menu(vctx) -> dict:
    return {str(lv.get("id")): lv for lv in (vctx or {}).get("menu") or []
            if isinstance(lv, dict) and lv.get("id")}


def reference(level) -> dict:
    """The stored reference of a menu level (A.30): copied by code."""
    return {"level_id": str(level.get("id") or ""),
            "kind": str(level.get("kind") or ""),
            "tf": str(level.get("tf") or ""),
            "price": _f(level.get("price")),
            "stop": _f(level.get("stop"))}


def _parse(at):
    from django.utils.dateparse import parse_datetime
    try:
        return parse_datetime(str(at)) if at else None
    except (TypeError, ValueError):
        return None


def plan_window(changes, now) -> list:
    """V2's window: each change {at, urgent} of the last 24 hours."""
    out = []
    for c in changes or ():
        at = _parse((c or {}).get("at")) if isinstance(c, dict) else None
        if at is not None and now - at < timedelta(hours=PLAN_WINDOW_H):
            out.append(c)
    return out


def urgent_for_plan(reasons) -> bool:
    """A wake is urgent for V2 when a reason is urgent and does not come
    from the plan's own watch (A.48)."""
    return any(isinstance(r, dict) and r.get("urgent")
               and r.get("source") != "plan" for r in reasons or ())


def _non_latin1_share(text) -> float:
    letters = [c for c in str(text or "") if c.isalpha()]
    if not letters:
        return 0.0
    out = sum(1 for c in letters if ord(c) > 0xFF)
    return out / len(letters)


def note_words(note, marks=None) -> tuple:
    """V11: (kept, rule words or ""). The note through the platform's
    money filter (plain.voice, dashboard/plain_words.scrub, widened in
    O2a), then the fence's quarantine and sanitize, cut at
    FENCE_CAPS["note"]. More than 20% of its letters outside Latin-1,
    measured before sanitize folds it to ASCII, is refused. A withheld
    note is replaced by NOTE_WITHHELD."""
    from dashboard.plain_words import WITHHELD, WITHHELD_ERROR

    from bot_program.orcs import fence
    from bot_program.orcs.plain import voice
    raw = str(note or "")
    if not raw.strip():
        return "", ""
    if _non_latin1_share(unicodedata.normalize("NFKC", raw)) > \
            NOTE_NON_LATIN1_MAX:
        return NOTE_WITHHELD, WORDS["V11_script"]
    plain = voice(raw, marks)
    if plain == WITHHELD:
        return NOTE_WITHHELD, WORDS["V11_money"]
    if plain == WITHHELD_ERROR:
        return NOTE_WITHHELD, WORDS["V11_error"]
    q, withheld = fence.quarantine(plain)
    if withheld:
        return NOTE_WITHHELD, WORDS["V11_instruction"]
    return fence.sanitize(q, FENCE_CAPS["note"]), ""


def _v7(level, vctx, side) -> tuple:
    """(would_stop, words): the would-stop of a tighten naming `level`."""
    lid = str(level.get("id") or "")
    if lid in ("CARE", "EFF"):
        return None, WORDS["V7_own"]
    stop = _f(level.get("price")) if lid == "BE" else _f(level.get("stop"))
    if stop is None:
        return None, WORDS["V7_own"]
    sign = _sign(side)
    atr = (vctx or {}).get("atr") or {}
    tf = str(level.get("tf") or "") or "4h"
    a, a4 = _f(atr.get(tf)) or _f(atr.get("4h")), _f(atr.get("4h"))
    p, m = _f(vctx.get("p")), _f(vctx.get("m"))
    if not a or p is None or m is None:
        return stop, WORDS["V7_room"]
    room = MIN_STOP_ROOM_ATR * a
    if sign * (p - stop) < room or sign * (m - stop) < room:
        return stop, WORDS["V7_room"]
    if a4 and abs(m - stop) > MAX_LEVEL_DIST_ATR4H * a4:
        return stop, WORDS["V7_far"]
    eff = _f(vctx.get("effective"))
    if eff is not None and sign * (stop - eff) <= 0:
        return stop, WORDS["V7_tighter"]
    return stop, ""


def _reached(level, cited, facts, precision) -> bool:
    """V6: a cited level_reached fact whose (kind, tf, price) equals the
    named level's in the menu, to the instrument's precision."""
    for fid in cited:
        info = facts.get(fid) or {}
        ref = info.get("level") if info.get("kind") == "level_reached" \
            else None
        if not isinstance(ref, dict):
            continue
        a, b = _f(ref.get("price")), _f(level.get("price"))
        if a is None or b is None:
            continue
        if str(ref.get("kind") or "") == str(level.get("kind") or "") and \
                str(ref.get("tf") or "") == str(level.get("tf") or "") and \
                round(a, precision) == round(b, precision):
            return True
    return False


def validate(text, *, stop_reason, vctx, facts, plan_changes, plan_version,
             plan_at, reasons, symbol, side, now, marks=None,
             precision=8) -> dict:
    """V1-V14 on one answer, in A.31's order and classes. Returns:

      status     "done", or "refused" (a whole-answer rule failed)
      rule       the first whole-answer rule that failed, or ""
      verdicts   {rule: "pass" | "refused: words" | "dropped: words" |
                  "withheld: words" | "n/a"}, in V_RULES' order
      refusals   [{rule, part ("whole", "next_wake" or "note"), words}]
      answer     the parsed answer, its note after V11 (None for V1)
      level      the named level's stored reference, or None
      would_stop a tighten's would-stop (V7), else None
      share      a trim's TRIM_SHARE or an add's risk share, else None
      clauses    a plan revision's clauses as stored references
      expectation the expectation with its stored reference, or None
      next_wake_min  0 when dropped (V9)

    `facts` is facts_index; `plan_changes`, `plan_version` and `plan_at`
    are the Orc row's own (V2 reads them at validation, never the
    dossier's copy); `reasons` the wake's (V2's urgency)."""
    verdicts = {r: "n/a" for r in V_RULES}
    refusals = []
    out = {"status": "refused", "rule": "", "verdicts": verdicts,
           "refusals": refusals, "answer": None, "level": None,
           "would_stop": None, "share": None, "clauses": [],
           "expectation": None, "next_wake_min": 0,
           "schema_version": SCHEMA_VERSION}

    def fail(rule, words, part="whole"):
        verdicts[rule] = (f"refused: {words}" if part == "whole" else
                          f"{'dropped' if part == 'next_wake' else 'withheld'}"
                          f": {words}")
        refusals.append({"rule": rule, "part": part, "words": words})
        if part == "whole" and not out["rule"]:
            out["rule"] = rule

    # V1: the shape, and a whole answer
    if stop_reason == "max_tokens":
        fail("V1", WORDS["V1_cut"])
        return out
    if stop_reason not in (None, "end_turn") or not str(text or "").strip():
        fail("V1", WORDS["V1_empty"] if not str(text or "").strip()
             else WORDS["V1"])
        return out
    answer, _why = shape(text)
    if answer is None:
        fail("V1", WORDS["V1"])
        return out
    verdicts["V1"] = "pass"
    out["answer"] = answer
    vctx = vctx if isinstance(vctx, dict) else {}
    menu = _menu(vctx)
    action = answer["action"]
    lid = answer["level_id"]
    cited = [str(f) for f in answer["facts_cited"]]
    allowed = list(vctx.get("allowed") or ["hold"])
    f5 = list(vctx.get("f5") or [])

    # V2: the plan's rate over 24 hours
    if action == "revise_plan":
        window = plan_window(plan_changes, now)
        if int(plan_version or 0) > 0 and \
                len(window) >= PLAN_CHANGES_24H_MAX and \
                not urgent_for_plan(reasons):
            fail("V2", WORDS["V2"])
        else:
            verdicts["V2"] = "pass"
    # V3: allowed
    if action in allowed:
        verdicts["V3"] = "pass"
    else:
        fail("V3", WORDS["V3"])
    # V4: the candidate
    cand = answer["candidate"]
    if cand == NONE:
        verdicts["V4"] = "pass"
    else:
        listed = {str(c.get("id")): c for c in vctx.get("candidates") or []
                  if isinstance(c, dict)}
        c = listed.get(cand)
        levels = [str(x) for x in (c or {}).get("level_ids") or []]
        if c is not None and c.get("action") == action and (
                not levels or lid in levels):
            verdicts["V4"] = "pass"
        else:
            fail("V4", WORDS["V4"])
    # V5: the level
    level = None
    if lid == NONE:
        market_exit = action == "exit"
        if action in ("hold", "revise_plan", "lock_waive") or market_exit:
            verdicts["V5"] = "pass"
        else:
            fail("V5", WORDS["V5_none"])
    elif lid in menu:
        level = menu[lid]
        out["level"] = reference(level)
        verdicts["V5"] = "pass"
    else:
        fail("V5", WORDS["V5"])
    # V6: reached, while the thesis is intact
    if action in ("exit", "trim"):
        if not vctx.get("thesis_intact"):
            verdicts["V6"] = "pass"
        elif level is not None and str(level.get("kind") or "") in \
                REACHED_KINDS and _reached(level, cited, facts or {},
                                           precision):
            verdicts["V6"] = "pass"
        else:
            fail("V6", WORDS["V6"])
    # V7: the stop room, and a tighten only
    if action == "tighten" and level is not None:
        stop, words = _v7(level, vctx, side)
        out["would_stop"] = stop
        if words:
            fail("V7", words)
        else:
            verdicts["V7"] = "pass"
    # V8: F5
    if f5:
        if action in ("hold", "revise_plan") or (
                action == "tighten" and vctx.get("mark_fresh")):
            verdicts["V8"] = "pass"
        else:
            fail("V8", WORDS["V8"])
    # V9: the asked wake (a part)
    n = answer["next_wake_min"]
    if n == 0 or NEXT_WAKE_MIN_MIN <= n <= NEXT_WAKE_MAX_MIN:
        verdicts["V9"] = "pass"
        out["next_wake_min"] = n
    else:
        fail("V9", WORDS["V9"], part="next_wake")
    # V10: relevance
    from bot_program.orcs import fence
    kind = "plan" if action == "revise_plan" else action
    ok, _w = fence.v10_satisfied(
        kind, cited, facts or {}, symbol,
        event=(answer["event_id"] if action == "lock_waive" else None),
        since=(plan_at if action == "revise_plan" and plan_version
               else None))
    if ok:
        verdicts["V10"] = "pass"
    else:
        fail("V10", WORDS["V10"])
    # V11: the note's words (a part)
    note, words = note_words(answer["note"], marks)
    if words:
        fail("V11", words, part="note")
    else:
        verdicts["V11"] = "pass"
    # V12: the plan's structure
    clauses = answer["plan_clauses"]
    if action == "revise_plan":
        refs, bad = [], not (1 <= len(clauses) <= PLAN_CLAUSES_MAX)
        add_bad = False
        for c in clauses:
            lv = menu.get(str(c.get("level_id")))
            if lv is None or not lv.get("watchable"):
                bad = True
                continue
            if c.get("kind") == "add" and "add" not in allowed:
                add_bad = True
            refs.append({**reference(lv), "clause": c.get("kind"),
                         "trigger": c.get("trigger"),
                         "side": str(lv.get("side") or "")})
        if bad:
            fail("V12", WORDS["V12"])
        elif add_bad:
            fail("V12", WORDS["V12_add"])
        else:
            verdicts["V12"] = "pass"
            out["clauses"] = refs
    elif clauses:
        fail("V12", WORDS["V12_other"])
    else:
        verdicts["V12"] = "pass"
    # V13: the expectation
    exp = answer["expectation"]
    if exp["kind"] == NONE:
        verdicts["V13"] = "pass"
    elif exp["level_id"] in menu:
        verdicts["V13"] = "pass"
        out["expectation"] = {"kind": exp["kind"],
                              "level": reference(menu[exp["level_id"]])}
    else:
        fail("V13", WORDS["V13"])
    # V14: the event
    events = vctx.get("events") or {}
    ev = answer["event_id"]
    if (action == "lock_waive" and ev in events) or (
            action != "lock_waive" and ev == NONE):
        verdicts["V14"] = "pass"
    else:
        fail("V14", WORDS["V14"])

    if action == "trim":
        out["share"] = TRIM_SHARE
    elif action == "add":
        out["share"] = RISK_SHARE_WORDS.get(answer["risk_share"])
    out["answer"] = {**answer, "note": note}
    if not any(r["part"] == "whole" for r in refusals):
        out["status"] = "done"
    return out


def whole(rule) -> bool:
    """A.31: does `rule` refuse the whole answer (or only a part)?"""
    return rule in V_WHOLE and rule not in V_PART


# ── the refusal entries (A.33) ───────────────────────────────────────────

def refusal_headline(rule, words, *, officer=False) -> str:
    """"Refused by the validator ({rule}): {words}." or, for the officer,
    "Would be refused by the officer ({rule}): {words}."."""
    words = str(words or "").rstrip(".")
    if officer:
        return f"Would be refused by the officer ({rule}): {words}."
    return f"Refused by the validator ({rule}): {words}."
