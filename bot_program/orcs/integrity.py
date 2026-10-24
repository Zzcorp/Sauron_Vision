"""PS13, THE INTEGRITY VERDICT (spec §5.2a "What PS13 does", §7.5.2 F5,
code of honor article VI): pure.

Three CRITICAL items, and only these, set F5:
  the mark        on a real row, the venue's own mark no older than
                  MARK_MAX_AGE_S (I10); on a paper row, its venue's quote
                  no older than that
  the bars        the decision frame's venue bars no older than two bar
                  lengths of open market (§1.4)
  the row         its own state readable

Under F5 the menu holds no discretionary R3-R6 kind: hold, a tighter plan
revision, and a tighten only while the mark is fresh (I11 needs it); the
armed clauses run as code and the care stands in. Every other missing or
stale input (the posture with crisis_mode OFF, a blind analyst, an unread
calendar, an unmeasured correlation) is listed, prints its dash and never
abstains.

# O2: mandate.allowed_actions replaces allowed_actions_l0 (the seat, the
# commission, the switches and the hazards of §3.1); O1 has no seat above
# L0, so every action is shadow.
"""
from bot_program.orcs.constants import MARK_MAX_AGE_S

#: §5.2a: the discretionary kinds F5 removes (the reversibility ranks
#: R3-R6 of §7.5.1).
R3_R6 = ("exit", "trim", "lock_waive", "add", "reenter", "be_swap",
         "widen_with_cut", "reverse")
#: The candidates F5 drops (playbook ids whose action is R3-R6; P-HOLD is
#: a lock waiver though its action reads "hold").
SHRUNK_IDS = ("X-THESIS", "K-DRAW", "P-TRIM", "P-HOLD")
#: The L0 shadow vocabulary of O1: what an Orc may PROPOSE in shadow.
#: Risk-adding kinds wait for the mandate's officer (O2).
L0_ALLOWED = ("hold", "revise_plan", "tighten", "exit", "trim",
              "lock_waive")
L0_WHY_NOT = ("L0: shadow only (no seat has earned authority; every "
              "action is journaled, none binds)",
              "add, re-entry, BE-swap, widen and reverse: the mandate's "
              "officer arrives with O2")
VENUE_SOURCES = ("venue",)
PAPER_SOURCES = ("venue", "quote", "tick")


def _utc(at) -> str:
    try:
        return f"{at:%Y-%m-%d %H:%M} UTC"
    except (TypeError, ValueError):
        return "an unread time"


def verdict(*, mark_source, mark_age_s, real, decision_tf, frame_fresh,
            frame_end, row_ok, contradictions=(), stale=(),
            missing=(), frame_venue=True) -> dict:
    """{critical[], stale[], missing[], contradictions[], flag}: flag is
    critical, contradiction, stale or ok. `frame_fresh` is the caller's:
    fresh, and the venue's own for a real row (a paper row may read the
    platform's bars, §5.2); `frame_venue` False on a real row says the
    frame is the platform's, never "stale"."""
    critical = []
    src = str(mark_source or "none")
    if src not in (PAPER_SOURCES if not real else VENUE_SOURCES):
        critical.append(f"the mark is not the venue's ({src})")
    else:
        try:
            age = float(mark_age_s)
        except (TypeError, ValueError):
            age = None
        if age is None:
            critical.append("the venue mark's age is unread")
        elif age > MARK_MAX_AGE_S:
            critical.append(f"the venue mark is {age:.0f} s old (over "
                            f"{MARK_MAX_AGE_S} s)")
    if not frame_fresh:
        if frame_end is None:
            critical.append(f"the {decision_tf} venue bars are missing")
        elif real and not frame_venue:
            critical.append(f"no {decision_tf} venue bars (platform only)")
        else:
            critical.append(f"the {decision_tf} venue bars are older than "
                            f"two bar lengths (last {_utc(frame_end)})")
    if not row_ok:
        critical.append("the row's state is unreadable")
    out = {"critical": critical, "stale": list(stale or ()),
           "missing": list(missing or ()),
           "contradictions": list(contradictions or ())}
    out["flag"] = ("critical" if critical else
                   "contradiction" if out["contradictions"] else
                   "stale" if out["stale"] or out["missing"] else "ok")
    return out


def words(v) -> str:
    """One line for the card: the flag and its first item."""
    v = v or {}
    for key in ("critical", "contradictions", "stale", "missing"):
        items = v.get(key) or []
        if items:
            return f"{v.get('flag')}: {items[0]}"
    return "ok: the mark, the bars and the row are fresh"


def allowed_actions_l0(*, f5, mark_fresh) -> tuple:
    """(allowed, why_not) at L0 in O1. `f5` is False or the critical
    items. Under F5: hold, a tighter plan revision and a tighten only on a
    fresh mark."""
    why_not = list(L0_WHY_NOT)
    if not f5:
        return list(L0_ALLOWED), why_not
    items = f5 if isinstance(f5, (list, tuple)) else ["a critical input"]
    allowed = ["hold", "revise_plan"] + (["tighten"] if mark_fresh else [])
    for item in items:
        why_not.append(f"F5: {item}: no discretionary exit, trim, waiver or "
                       f"add is on the menu")
    if not mark_fresh:
        why_not.append("F5: no tighten without a fresh venue mark")
    return allowed, why_not


def shrink(candidates, f5, *, mark_fresh=True) -> list:
    """The playbook's candidates under F5: no R3-R6 kind, and a tighten
    only on a fresh mark. Whole without F5."""
    if not f5:
        return list(candidates or ())
    out = []
    for c in candidates or ():
        cid = getattr(c, "id", None) or (c or {}).get("id")
        action = getattr(c, "action", None) or (c or {}).get("action")
        if cid in SHRUNK_IDS or action in R3_R6:
            continue
        if action == "tighten" and not mark_fresh:
            continue
        out.append(c)
    return out
