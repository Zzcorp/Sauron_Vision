"""THE OFFICER (the O2 spec A.36-A.38; O2a, 2026-11-05), in would-mode:
pure but for one read of the Orc's own arm.

  allowed_actions  what an Orc may propose now (PS1, V3), replacing O1's
                   integrity.allowed_actions_l0 in dossier.context_for:
                   the L0 vocabulary, plus `add` judged as if binding when
                   the army type allows adds, adds remain and F5 is not
                   set; `lock_waive` gone for a type that has no lock
                   waiver; F5 shrinks the list as O1's did. With the
                   why-not lines PS1 prints.
  judge            I2-I12: each proposal judged as if it bound, at the
                   authority its kind needs, against the would-world of the
                   O arm (its open size, its effective stop, its banked R).
                   allow, cut or refuse, with the rule and its words. The
                   seat stays L0: nothing binds.
  accept           seen["officer"] after an ACCEPTED proposal (allowed or
                   cut), never after the care's own acts (A.38).
  ps4              the counters PS4 shows, so a refusal under V2, I5 or I12
                   always names a counter the model was shown.

Every number is in R; no money anywhere. The risk-adding candidates stay
unlisted in O2 (playbook.RISK_ADDING): an add names candidate "none"."""
from bot_program.orcs.constants import (ADD_MIN_SHARE, ADD_SPACING_BARS,
                                        ARM_ORC, GROSS_MAX_R,
                                        OFFICER_ALLOW, OFFICER_CUT,
                                        OFFICER_REFUSE,
                                        PLAN_CHANGES_24H_MAX,
                                        STEPS_PER_DAY_MAX, TRIM_SPACING_BARS)

#: A.36: the why-not lines of O2.
WHY_L0 = ("L0: shadow only: every proposal is journaled and graded, none is "
          "applied")
WHY_ADD = "add: judged by the officer as if binding, never applied in O2"
WHY_NOT_O2 = "re-entry, BE-swap, widen and reverse: not in O2"
WHY_NO_WAIVER = "lock_waive: not for {name}"
WHY_NO_ADDS = "add: not for {name}"
WHY_ADDS_SPENT = "add: no add left ({used} of {max} used or accepted)"
WHY_F5_ADD = "add: not under F5"
#: The L0 vocabulary (integrity.L0_ALLOWED).
L0 = ("hold", "revise_plan", "tighten", "exit", "trim", "lock_waive")
#: The officer's words, rule by rule (A.37).
WORDS = {
    "I2": "the gross risk after the add would pass 2R",
    "I3": "an add needs a structure or bar fact on this symbol, and the "
          "root's stop at or beyond break-even",
    "I3c": "the root's stop is not beyond break-even with its costs",
    "I3h": "the gap behind it is unmeasured, or past the type's floor",
    "I4_cut": "the add's share is cut to fit",
    "I4": "the add's share would be under a quarter",
    "I5": "no add left for this type",
    "I5_exotic": "an exotic pair never adds for this type",
    "I6": "no add this close to a shut",
    "I12_steps": "four tightens a trading day at most",
    "I12_add": "too few decision bars since the last add",
    "I12_trim": "too few decision bars since the last trim",
}


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and v not in (float("inf"), float("-inf")) else None


def _sign(side) -> int:
    return 1 if str(side or "").upper() == "BUY" else -1


# ── the army type's flags (army.py: the mandate parameters act from O2) ──

def army_of(orc) -> dict:
    """The parameters the Orc's type sets, the Corsair overlay applied
    where it is tighter: no flag is ever looser than the base type."""
    from bot_program.orcs.army import ARMY_TYPES, CORSAIRS, LINE
    base = ARMY_TYPES.get(str(getattr(orc, "army_type", "") or "")) or LINE
    why = orc.army_why if isinstance(getattr(orc, "army_why", None),
                                     dict) else {}
    over = CORSAIRS if why.get("overlay") else None
    out = {"key": base.key, "name": base.name, "adds": base.adds,
           "lock_waiver": base.lock_waiver, "max_adds": base.max_adds,
           "risk_share_max": base.risk_share_max,
           "waiver_floor_r": base.waiver_floor_r,
           "gap_min_samples": base.gap_min_samples,
           "add_pre_shut_h": base.add_pre_shut_h,
           "exotic_adds": base.exotic_adds}
    if over is not None:
        out["name"] = f"{base.name} + Corsairs"
        out["adds"] = out["adds"] and over.adds
        out["lock_waiver"] = out["lock_waiver"] and over.lock_waiver
        out["max_adds"] = min(out["max_adds"], over.max_adds)
        out["risk_share_max"] = min(out["risk_share_max"],
                                    over.risk_share_max)
        out["waiver_floor_r"] = max(out["waiver_floor_r"],
                                    over.waiver_floor_r)
        out["gap_min_samples"] = max(out["gap_min_samples"],
                                     over.gap_min_samples)
        out["add_pre_shut_h"] = max(out["add_pre_shut_h"],
                                    over.add_pre_shut_h)
        out["exotic_adds"] = out["exotic_adds"] and over.exotic_adds
    return out


def officer_state(orc, day=None) -> dict:
    """seen["officer"], with steps_today read for `day` (the trading day:
    it resets at the roll, A.38)."""
    seen = orc.seen if isinstance(getattr(orc, "seen", None), dict) else {}
    st = dict(seen.get("officer") or {})
    st.setdefault("would_adds", 0)
    if day is not None and st.get("day") != str(day):
        st["day"], st["steps_today"] = str(day), 0
    st.setdefault("steps_today", 0)
    return st


def adds_left(orc) -> int:
    t = army_of(orc)
    st = officer_state(orc)
    return max(0, int(t["max_adds"]) - int(getattr(orc, "adds_used", 0) or 0)
               - int(st.get("would_adds") or 0))


def allowed_actions(orc, ctx) -> tuple:
    """(allowed, why_not) for PS1 and V3 (A.36). `ctx`: f5 (False or the
    critical items) and mark_fresh."""
    ctx = ctx if isinstance(ctx, dict) else {}
    f5 = ctx.get("f5") or False
    t = army_of(orc)
    allowed = list(L0)
    why_not = [WHY_L0]
    if not t["lock_waiver"]:
        allowed.remove("lock_waive")
        why_not.append(WHY_NO_WAIVER.format(name=t["name"]))
    left = adds_left(orc)
    if not t["adds"]:
        why_not.append(WHY_NO_ADDS.format(name=t["name"]))
    elif left <= 0:
        st = officer_state(orc)
        why_not.append(WHY_ADDS_SPENT.format(
            used=int(getattr(orc, "adds_used", 0) or 0)
            + int(st.get("would_adds") or 0), max=t["max_adds"]))
    elif f5:
        why_not.append(WHY_F5_ADD)
    else:
        allowed.append("add")
    why_not.append(WHY_ADD)
    why_not.append(WHY_NOT_O2)
    if f5:
        mark_fresh = bool(ctx.get("mark_fresh"))
        items = f5 if isinstance(f5, (list, tuple)) else ["a critical input"]
        allowed = [a for a in allowed if a in ("hold", "revise_plan")] + (
            ["tighten"] if mark_fresh and "tighten" in allowed else [])
        for item in items:
            why_not.append(f"F5: {item}: no discretionary exit, trim, waiver "
                           f"or add is on the menu")
        if not mark_fresh:
            why_not.append("F5: no tighten without a fresh venue mark")
    return allowed, why_not


# ── the would-world (one OrcTrack read) ─────────────────────────────────

def arm_world(orc, vctx=None) -> dict:
    """The O arm as the officer reads it (A.37): its open share of the
    birth size, its effective stop (the tighter of the care's soft stop,
    the venue's and its own would-stop), its banked R and the negative
    part of it, its cost fraction. With no arm, the dossier's own."""
    from bot_program.orcs.models import OrcTrack
    vctx = vctx if isinstance(vctx, dict) else {}
    track = OrcTrack.objects.filter(orc_id=orc.pk, arm=ARM_ORC).only(
        "state", "open").first()
    state = dict(track.state or {}) if track is not None else {}
    side = str(state.get("side") or vctx.get("side") or orc.side)
    sign = _sign(side)
    entry = _f(state.get("entry")) or _f(vctx.get("entry"))
    rpu = _f(state.get("rpu")) or _f(vctx.get("rpu"))
    qty, qty_open = _f(state.get("qty")), _f(state.get("qty_open"))
    open_frac = (qty_open / qty) if qty and qty_open is not None else 1.0
    eff = None
    for lv in (_f(state.get("soft_stop")), _f(state.get("venue_stop")),
               _f(state.get("orc_stop")), _f(vctx.get("effective"))):
        if lv is not None and (eff is None or sign * (lv - eff) > 0):
            eff = lv
    banked = 0.0
    for b in state.get("banked") or []:
        q, px = _f((b or {}).get("qty")), _f((b or {}).get("px"))
        if q and px and entry and rpu and qty:
            banked += q * sign * (px - entry) / (qty * rpu)
    cf = _f(state.get("cf"))
    return {"side": side, "entry": entry, "rpu": rpu,
            "open_frac": max(0.0, open_frac), "eff_stop": eff,
            "banked_r": banked, "losses_r": max(0.0, -banked),
            "cf": cf if cf is not None else (_f(vctx.get("cf")) or 0.0),
            "mode": str(state.get("mode") or ""),
            "open": bool(track.open) if track is not None else True}


def root_risk_r(world) -> float:
    """The open risk at the arm's effective stop, in R, the exit's half
    spread counted at the stop (P31.3)."""
    from bot_program.orcs.pricing import half_spread
    entry, rpu, eff = world.get("entry"), world.get("rpu"), \
        world.get("eff_stop")
    if not entry or not rpu or eff is None:
        return 1.0 * world.get("open_frac", 1.0)
    sign = _sign(world.get("side"))
    at_stop = max(0.0, sign * (entry - eff)) / rpu
    cost = half_spread(eff, world.get("cf") or 0.0) / rpu
    return world.get("open_frac", 1.0) * (at_stop + cost)


def break_even(vctx, world) -> object:
    """I3c's break-even: the BE row (the entry plus its round trip, built
    with the row's cost fraction) plus the exit's half spread at the
    tick, never the raw entry (P31.1). None with no BE row."""
    from bot_program.orcs.pricing import half_spread
    be = None
    for lv in (vctx or {}).get("menu") or []:
        if isinstance(lv, dict) and lv.get("id") == "BE":
            be = _f(lv.get("price"))
    if be is None:
        return None
    m = _f((vctx or {}).get("m")) or be
    return be + _sign(world.get("side")) * half_spread(m, world.get("cf")
                                                       or 0.0)


def _bars_since(last, vctx) -> object:
    """The decision frame's final bars since `last` (an end), or None."""
    if not last:
        return None
    ends = [str(e) for e in (vctx or {}).get("decision_bars") or []]
    return sum(1 for e in ends if e > str(last))


def _verdict(verdict, rule="", words="", share=None, **extra) -> dict:
    return {"verdict": verdict, "rule": rule, "words": words,
            "share": share, **extra}


def judge(orc, *, action, vctx, facts=None, cited=(), share=None,
          event_id="", world=None, day=None, exotic_legs=()) -> dict:
    """The would-verdict of one proposal (A.37): {verdict (allow, cut or
    refuse), rule, words, share, gross_r?}. `world` is arm_world's;
    `share` an add's asked risk share. Pure."""
    from bot_program.orcs import fence, gaps
    vctx = vctx if isinstance(vctx, dict) else {}
    world = world if isinstance(world, dict) else arm_world(orc, vctx)
    t = army_of(orc)
    st = officer_state(orc, day)
    if action == "tighten":
        if int(st.get("steps_today") or 0) >= STEPS_PER_DAY_MAX:
            return _verdict(OFFICER_REFUSE, "I12", WORDS["I12_steps"])
        return _verdict(OFFICER_ALLOW)
    if action == "trim":
        since = _bars_since(st.get("last_trim_bar"), vctx)
        if since is not None and since < TRIM_SPACING_BARS:
            return _verdict(OFFICER_REFUSE, "I12", WORDS["I12_trim"])
        return _verdict(OFFICER_ALLOW)
    if action == "lock_waive":
        gap = ((vctx.get("gaps") or {}).get(str(event_id)) or {})
        rpu = world.get("rpu")
        p90_r = _f(gap.get("p90_r"))
        n = int(gap.get("n") or 0)
        g = gaps.Gap(str(gap.get("kind") or ""), str(event_id), n,
                     (p90_r * rpu) if p90_r is not None and rpu else None)
        entry, eff = world.get("entry"), world.get("eff_stop")
        wc_r = (world.get("open_frac", 1.0) * _sign(world.get("side"))
                * (eff - entry) / rpu + world.get("banked_r", 0.0)
                if entry and rpu and eff is not None else None)
        ok, _why, _gr = gaps.waiver_check(wc_r, g, rpu,
                                          floor=t["waiver_floor_r"],
                                          min_n=t["gap_min_samples"])
        if not ok:
            return _verdict(OFFICER_REFUSE, "I3h", WORDS["I3h"])
        return _verdict(OFFICER_ALLOW)
    if action != "add":
        return _verdict(OFFICER_ALLOW)
    # an add, judged as if it bound
    used = int(getattr(orc, "adds_used", 0) or 0) + int(
        st.get("would_adds") or 0)
    if not t["adds"] or used >= int(t["max_adds"]):
        return _verdict(OFFICER_REFUSE, "I5", WORDS["I5"])
    if exotic_legs and not t["exotic_adds"]:
        return _verdict(OFFICER_REFUSE, "I5", WORDS["I5_exotic"])
    events = vctx.get("events") or {}
    if any((ev or {}).get("kind") == "shut" for ev in events.values()):
        return _verdict(OFFICER_REFUSE, "I6", WORDS["I6"])
    since = _bars_since(st.get("last_add_bar"), vctx)
    if since is not None and since < ADD_SPACING_BARS:
        return _verdict(OFFICER_REFUSE, "I12", WORDS["I12_add"])
    ok, _w = fence.v10_satisfied("add", list(cited or ()), facts or {},
                                 orc.symbol)
    be_raw = None
    for lv in vctx.get("menu") or []:
        if isinstance(lv, dict) and lv.get("id") == "BE":
            be_raw = _f(lv.get("price"))
    eff = world.get("eff_stop")
    sign = _sign(world.get("side"))
    if not ok or be_raw is None or eff is None or sign * (eff - be_raw) < 0:
        return _verdict(OFFICER_REFUSE, "I3", WORDS["I3"])
    be = break_even(vctx, world)
    if be is None or sign * (eff - be) < 0:
        return _verdict(OFFICER_REFUSE, "I3c", WORDS["I3c"])
    for code, ev in events.items():
        g = (vctx.get("gaps") or {}).get(code) or {}
        if not g.get("measured"):
            return _verdict(OFFICER_REFUSE, "I3h", WORDS["I3h"])
    base = root_risk_r(world) + world.get("losses_r", 0.0)
    if base >= GROSS_MAX_R:
        return _verdict(OFFICER_REFUSE, "I2", WORDS["I2"], gross_r=base)
    asked = _f(share) or 0.0
    room = GROSS_MAX_R - base
    fit = min(asked, float(t["risk_share_max"]), room)
    if fit < ADD_MIN_SHARE:
        return _verdict(OFFICER_REFUSE, "I4", WORDS["I4"], gross_r=base)
    if fit < asked:
        return _verdict(OFFICER_CUT, "I4", WORDS["I4_cut"],
                        share=round(fit, 4), gross_r=base + fit)
    return _verdict(OFFICER_ALLOW, share=asked, gross_r=base + asked)


def accept(state, *, action, day, bar) -> dict:
    """seen["officer"] after an accepted proposal (A.38): a tighten
    counts a step of the trading day, a trim and an add stamp the decision
    frame's newest final bar, an add counts a would-add. Pure."""
    st = dict(state or {})
    if st.get("day") != str(day):
        st["day"], st["steps_today"] = str(day), 0
    if action == "tighten":
        st["steps_today"] = int(st.get("steps_today") or 0) + 1
    elif action == "trim":
        st["last_trim_bar"] = bar
    elif action == "add":
        st["last_add_bar"] = bar
        st["would_adds"] = int(st.get("would_adds") or 0) + 1
    return st


def ps4(orc, vctx=None, *, day=None, now=None) -> dict:
    """PS4's mandate counters (A.47): the adds left by the type, the plan
    changes left in 24 hours (V2), the steps left today and the decision
    bars since the last accepted add and trim (I12)."""
    from django.utils import timezone

    from bot_program.orcs.validator import plan_window
    now = now or timezone.now()
    st = officer_state(orc, day)
    changes = plan_window(getattr(orc, "plan_changes_24h", None) or [], now)
    first = int(getattr(orc, "plan_version", 0) or 0) == 0

    def bars(key):
        n = _bars_since(st.get(key), vctx)
        return "— (none yet)" if n is None else n
    return {"adds_left": adds_left(orc),
            "plan_changes_left": (PLAN_CHANGES_24H_MAX if first else max(
                0, PLAN_CHANGES_24H_MAX - len(changes))),
            "steps_left_today": max(0, STEPS_PER_DAY_MAX - int(
                st.get("steps_today") or 0)),
            "bars_since_add": bars("last_add_bar"),
            "bars_since_trim": bars("last_trim_bar")}
