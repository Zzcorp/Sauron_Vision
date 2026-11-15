"""THE CODE OF HONOR, IN SHADOW (the O2 spec C.1, C.2; O2c, 2026-11-15): pure
audits over one dead idea's shadow record, run by its grade
(bot_program/orcs/grading.py) before the grade's own transaction. No model
and no switch: honor runs at every grade whatever the switches say, and on
an idea no model read it finds nothing.

The lost code of honor's article numbers are not restated (C.1), but VI
(the integrity verdict, integrity.py) and IX (the fence, fence.py), which
the code cites. Each audit carries its own code:

  H1  an unacknowledged miss: the first decision the validator passed whose
      own dossier showed a "missed" expectation fact (evidence.py writes it
      before the dossier of the wake after the graded bar) and that does
      not cite it among its facts_cited. The doctrine asks it first (S8:
      "cite a missed expectation before anything else"). Its dossier showed
      the fact when the decision's wake's validation context counted it
      (vctx.max_fact); a decision with no such record is judged when it was
      written after the fact. A decision whose call was in flight while the
      miss was written read a dossier without it, so it is not the one
      judged.
  H2  an unacted signpost: a met predicate (predicates.py) or the thesis
      check's exit (facts.py; a reviewer's exit is no signpost), with no
      exit, trim or tighten proposed (an OrcIntent created, whatever became
      of it) within one bar of the idea's decision frame after it
      (dossier.decision_tf). Only a signpost the idea outlived by that bar
      is judged: one whose idea died, or whose O arm closed, inside it was
      never left unacted past one decision bar (tribunal.IdeaFacts).
  H3  the tripwire: the O arm, in would mode (the Orc's own proposals
      stepped it), closed below TRIPWIRE_IDEA_R, -1.2R, Morgul's G12: "the
      stop did not hold". The arm recording the row (O1's mode, no proposal
      applied) is the care's loss, never a breach.

H1 and H2 read only the signposts written at or after the moment of the
idea's first wake a model read (its status one of MODEL_ANSWERED; that
wake's own moment): an Orc no model read could not have proposed anything.

THE ORC'S OWN "DEAD" (C.1 names it beside H2's signposts) is not measured
in O2: the answer's schema (validator.SCHEMA_V1) has no field in which an
Orc declares its thesis dead, so no record holds one to audit.

REFUSALS NEVER COUNT (tribunal.py): a validator's or the officer's refusal
is no breach. H1 reads only the decisions the validator passed (a refused
answer neither breaches nor acknowledges a miss), and H2 counts every exit,
trim or tighten proposed, refused ones included, as acted upon.

A finding is {code, evidence, at, t}: the fact ids (F-n) it rests on, the
moment it was made (H1 the uncited decision, H2 the end of the bar left
unacted, H3 the arm's exit) and its words. What it becomes is the grade's:
a `breach` entry by code, the grade's tag shadow_breach:<code>, and the
class the idea would get if its breaches bound, kept in the grade's body as
`shadow`. The grade itself still passes breaches=0, so no idea is FAULT in
O2. O2d's council of war reads `h2` for IdeaFacts.signpost_unacted (D.12).

Every input is a model row or a dict of the same keys (an entry: id, kind,
author, fact_id, body, at, wake_id; an intent: id, kind, created_at; a
wake: id, status, created_at, components; the O arm: state, open, exit_r,
exit_at), read as given: nothing here reaches the database.
"""
import re

from bot_program.orcs import bars, fence
from bot_program.orcs.constants import (ARM_ORC, MODEL_ANSWERED, PRED_MET,
                                        TRIPWIRE_IDEA_R)

H1, H2, H3 = "H1", "H2", "H3"
CODES = (H1, H2, H3)
#: Each code in words: the breach entry's headline and the Orc page.
WORDS = {H1: "an unacknowledged miss", H2: "an unacted signpost",
         H3: "the stop did not hold"}
#: The proposals that act on a signpost (H2).
ACTS = ("exit", "trim", "tighten")
#: The thesis check's verdict that is a signpost (brain/thesis_check.EXIT).
THESIS_EXIT = "exit"
_FACT_NO = re.compile(r"F(\d+)")


def _g(obj, name, default=None):
    """A field of a model row or a dict; an id is the row's pk."""
    if isinstance(obj, dict):
        value = obj.get(name, default)
        if value is None and name == "id":
            value = obj.get("pk", default)
        return value
    if name == "id":
        return getattr(obj, "pk", default)
    return getattr(obj, name, default)


def _body(entry) -> dict:
    body = _g(entry, "body")
    return body if isinstance(body, dict) else {}


def _order(entry) -> tuple:
    return (_g(entry, "at"), _g(entry, "id") or 0)


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def _fact_no(fact_id):
    m = _FACT_NO.fullmatch(str(fact_id or ""))
    return int(m.group(1)) if m else None


def first_read_at(wakes):
    """The moment of the idea's first wake a model read (MODEL_ANSWERED),
    or None when no model ever read it."""
    times = [_g(w, "created_at") for w in wakes or ()
             if _g(w, "status") in MODEL_ANSWERED
             and _g(w, "created_at") is not None]
    return min(times) if times else None


def _facts(entries) -> list:
    return sorted((e for e in entries or ()
                   if _g(e, "kind") == "fact" and _g(e, "fact_id")),
                  key=_order)


def _decisions(entries) -> list:
    """The decisions the validator passed, oldest first."""
    return sorted((e for e in entries or ()
                   if _g(e, "kind") == "decision"
                   and _body(e).get("status") == "done"), key=_order)


def _cited(decision) -> set:
    answer = _body(decision).get("answer")
    answer = answer if isinstance(answer, dict) else {}
    return {str(f) for f in answer.get("facts_cited") or ()}


def _shown_upto(wakes) -> dict:
    """{wake id: the last fact number its dossier counted} (vctx.max_fact),
    for the wakes whose validation context kept it."""
    out = {}
    for w in wakes or ():
        comps = _g(w, "components")
        vctx = comps.get("vctx") if isinstance(comps, dict) else None
        n = vctx.get("max_fact") if isinstance(vctx, dict) else None
        if isinstance(n, int):
            out[_g(w, "id")] = n
    return out


def _saw(decision, fact, shown) -> bool:
    """The decision's own dossier showed the fact."""
    if _order(decision) <= _order(fact):
        return False
    upto = shown.get(_g(decision, "wake_id"))
    n = _fact_no(_g(fact, "fact_id"))
    return True if upto is None or n is None else n <= upto


def h1(entries, *, wakes) -> list:
    """H1, an unacknowledged miss (module docstring)."""
    since = first_read_at(wakes)
    if since is None:
        return []
    shown = _shown_upto(wakes)
    decisions = _decisions(entries)
    out = []
    for miss in _facts(entries):
        body = _body(miss)
        if body.get("fk") != "expectation" or body.get("result") != "missed":
            continue
        if _g(miss, "at") < since:
            continue
        first = next((d for d in decisions if _saw(d, miss, shown)), None)
        fid = str(_g(miss, "fact_id"))
        if first is None or fid in _cited(first):
            continue
        out += [{"code": H1, "evidence": [fid], "at": _g(first, "at"),
                 "t": (f"Shadow breach H1, {WORDS[H1]}: the first decision "
                       f"after the missed expectation {fid} did not cite "
                       f"it.")}]
    return out


def _signpost(entry) -> bool:
    """A met predicate, or the thesis check's exit."""
    body = _body(entry)
    result = body.get("result")
    if isinstance(body.get("predicate"), dict) and isinstance(result, dict):
        return result.get("state") == PRED_MET
    return (fence.fact_kind(entry) == "structure"
            and str(body.get("verdict") or "") == THESIS_EXIT)


def h2(entries, intents, *, wakes, decision_tf, until=None) -> list:
    """H2, an unacted signpost (module docstring). `until`: the idea's end
    (the earlier of its death and its O arm's exit); a signpost whose bar
    runs past it is not judged. O2d's IdeaFacts.signpost_unacted (D.12)
    is `bool(h2(...))`."""
    since = first_read_at(wakes)
    if since is None:
        return []
    span = bars.span_of(decision_tf)
    acts = sorted(_g(i, "created_at") for i in intents or ()
                  if _g(i, "kind") in ACTS
                  and _g(i, "created_at") is not None)
    out = []
    for sign in _facts(entries):
        if not _signpost(sign):
            continue
        at = _g(sign, "at")
        if at < since:
            continue
        end = at + span
        if until is not None and end > until:
            continue
        if any(at <= t <= end for t in acts):
            continue
        fid = str(_g(sign, "fact_id"))
        out += [{"code": H2, "evidence": [fid], "at": end,
                 "t": (f"Shadow breach H2, {WORDS[H2]}: no exit, trim or "
                       f"tighten was proposed within one {decision_tf} bar "
                       f"of {fid}.")}]
    return out


def h3(o_track, entries=()) -> list:
    """H3, the tripwire (module docstring). The evidence is the arm's exit
    fact (ghost.py journals it) when there is one."""
    if o_track is None or _g(o_track, "open"):
        return []
    state = _g(o_track, "state")
    if not isinstance(state, dict) or state.get("mode") != "would":
        return []
    r = _f(_g(o_track, "exit_r"))
    if r is None or not r < TRIPWIRE_IDEA_R:
        return []
    exits = [e for e in _facts(entries)
             if _body(e).get("arm") == ARM_ORC]
    return [{"code": H3,
             "evidence": [str(_g(exits[-1], "fact_id"))] if exits else [],
             "at": _g(o_track, "exit_at"),
             "t": (f"Shadow breach H3, {WORDS[H3]}: the shadow arm closed at "
                   f"{r:+.2f}R, past the {TRIPWIRE_IDEA_R:+.2f}R tripwire.")}]


def until_of(o_track, died_at=None):
    """The idea's end for H2: the earlier of its death and its O arm's
    exit; None when neither is known."""
    ends = [t for t in (died_at, _g(o_track, "exit_at")
                        if o_track is not None else None) if t is not None]
    return min(ends) if ends else None


def audit(*, entries, intents, wakes, o_track, decision_tf,
          died_at=None) -> list:
    """Every finding of H1-H3 over the idea's shadow record, in time order
    (a finding with no moment last)."""
    found = (h1(entries, wakes=wakes)
             + h2(entries, intents, wakes=wakes, decision_tf=decision_tf,
                  until=until_of(o_track, died_at))
             + h3(o_track, entries))
    return sorted(found, key=lambda f: (f["at"] is None, f["at"] or 0,
                                        f["code"]))
