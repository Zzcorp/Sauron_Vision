"""THE COUNCIL OF WAR'S CLASS (spec §6.10), pure: code sets the class from
the graded arms, never a model. It imports nothing from ai_agents; the
council's words (the model call) arrive with O2.

  FAULT       only a decision code can PROVE was available and wrong: a
              binding code-of-honor breach in the idea's life (an audit or
              G13, never a refused proposal), or a signpost (a met
              predicate, a thesis-check exit, the Orc's own "dead") left
              unacted while an exit sat in the menu. At L0-L1 no exit is in
              the menu: no fault.
  WON         the Orc arm closed at or above 0R
  HONOURABLE  below 0R with no fault cause

Labels, never a penalty: "victory_in_defeat" (an honourable defeat that
lost less than the care), "costly_early" and "costly_late" (more than
HONOUR_TOLERANCE_R worse than the care, by the first divergence: a reduce,
or a hold). Early and late hands are judged alike, by the block statistic
(`block_faults`): one threshold on both sides, UB80 < 0 of the attributed
delta over a block, so the code can never push a lineage toward cutting
winners early or holding late.

In O1 the classifier runs on graded arms with breaches=0 and
exit_available=False (every seat is L0): every idea is won or honourable.
"""
import math
from dataclasses import dataclass, field

from bot_program.orcs.constants import (BLOCK_FAULT_MIN_N, DIVERGE_HOLD,
                                        DIVERGE_REDUCE, FELL_FAULT,
                                        FELL_HONOURABLE, FELL_WON,
                                        HONOUR_TOLERANCE_R, PROMOTE_Z)

VICTORY_IN_DEFEAT = "victory_in_defeat"
COSTLY_EARLY = "costly_early"
COSTLY_LATE = "costly_late"
#: The per-block faults (§6.10), each on UB80 < 0 of its group's delta.
BLOCK_LATE, BLOCK_EARLY, BLOCK_GAVE_BACK = ("late hands", "early hands",
                                            "gave back")


@dataclass(frozen=True)
class IdeaFacts:
    orc_r_gross: object = None
    ghost_r: object = None
    delta_care: object = None
    first_divergence: str = ""
    #: binding breaches written by the audits or G13 (O2), never refusals
    breaches: int = 0
    #: a signpost left unacted past one decision bar
    signpost_unacted: bool = False
    #: a discretionary exit sat in allowed_actions (L2+), or a clause could
    #: have been armed
    exit_available: bool = False
    #: validator refusals: counted elsewhere, never a fault
    refusals: int = 0
    gave_back: bool = False


@dataclass(frozen=True)
class Verdict:
    fell: str
    sub_label: str = ""
    causes: tuple = field(default_factory=tuple)


def classify(facts: IdeaFacts) -> Verdict:
    causes = []
    if int(facts.breaches or 0) > 0:
        causes.append("a binding breach of the code of honor")
    if facts.signpost_unacted and facts.exit_available:
        causes.append("a signpost left unacted while an exit was in the menu")
    if causes:
        return Verdict(FELL_FAULT, "", tuple(causes))
    o = facts.orc_r_gross
    if o is None:
        return Verdict("", "", ("no R: nothing to grade",))
    fell = FELL_WON if float(o) >= 0 else FELL_HONOURABLE
    d = facts.delta_care
    sub = ""
    if d is not None:
        d = float(d)
        if fell == FELL_HONOURABLE and d > 0:
            sub = VICTORY_IN_DEFEAT
        elif d < -HONOUR_TOLERANCE_R:
            if facts.first_divergence == DIVERGE_REDUCE:
                sub = COSTLY_EARLY
            elif facts.first_divergence == DIVERGE_HOLD:
                sub = COSTLY_LATE
    return Verdict(fell, sub, ())


def block_stats(values) -> dict:
    """{n, mean, sd, se, lb80, ub80} of a block's deltas (PROMOTE_Z, the
    one-sided 80% bound aragorn.py:83 promotes on)."""
    xs = [float(x) for x in values if x is not None]
    n = len(xs)
    if not n:
        return {"n": 0, "mean": None, "sd": None, "se": None, "lb80": None,
                "ub80": None}
    mean = sum(xs) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in xs) / (n - 1)) if n > 1 \
        else 0.0
    se = sd / math.sqrt(n)
    return {"n": n, "mean": mean, "sd": sd, "se": se,
            "lb80": mean - PROMOTE_Z * se, "ub80": mean + PROMOTE_Z * se}


def block_faults(rows, *, min_n=BLOCK_FAULT_MIN_N) -> list:
    """At most ONE block fault: the group (late hands: the first divergence
    a hold; early hands: a reduce; gave back: tagged) whose attributed delta
    reads UB80 < 0 with at least `min_n` ideas, the worst if several.
    `rows`: [{delta_care, first_divergence, gave_back}]."""
    groups = {
        BLOCK_LATE: [r.get("delta_care") for r in rows
                     if r.get("first_divergence") == DIVERGE_HOLD],
        BLOCK_EARLY: [r.get("delta_care") for r in rows
                      if r.get("first_divergence") == DIVERGE_REDUCE],
        BLOCK_GAVE_BACK: [r.get("delta_care") for r in rows
                          if r.get("gave_back")],
    }
    found = []
    for kind, deltas in groups.items():
        st = block_stats(deltas)
        if st["n"] >= int(min_n) and st["ub80"] is not None \
                and st["ub80"] < 0:
            found.append({"kind": kind, **st})
    if not found:
        return []
    return [min(found, key=lambda f: f["ub80"])]
