"""THE ARMY TYPES (spec §1.6), pure: no database, no model, no clock.

The operator asked for "different army types for different situations ...
or is it just fugazi?". A type is real only where the job differs, so each
one below names what it changes against Line (`differs_by`, a declared
step per parameter), each is tighter than the mandate (§2), never looser,
and the type is ASSIGNED by the measured situation at birth, never chosen.
The base type is fixed for life so its record is clean; only the Corsair
overlay moves (re-assessed at each trading-day roll from O1c).

O1 assigns and journals the type. Its cadence, dossier focus, model ladder
and mandate parameters act from O2 (shadow) and O3 (paper).

The situation is a plain dict built by bot_program/orcs/situation.py:
    asset_class, manual, persona, hold_h, stop_distance (|entry - initial
    stop|, or None), atr {1h, 4h, 1d} (None when unmeasured), spread,
    shuts [{at, words, kind, hours}] inside the hold, crypto_weekend,
    prints (high-impact, its currencies, inside the hold), exotic_legs,
    gap_p90_r (the next shut's measured gap in R, orcs/gaps.py; None
    while unmeasured),
    operator_horizon_h (None until the operator writes a thesis, O1d).
"""
from dataclasses import dataclass
from typing import ClassVar

from bot_program.orcs.constants import (
    ADD_PRE_SHUT_H, CORSAIR_ADD_PRE_SHUT_H, CORSAIR_EVENT_WAIVER_FLOOR_R,
    CORSAIR_GAP_MIN_SAMPLES, CORSAIR_GAP_P90_R, CORSAIR_MIN_PRINTS,
    EVENT_WAIVER_FLOOR_R, GAP_MIN_SAMPLES, LINE_RISK_SHARE_MAX,
    LINE_STOP_ATR4H, MAX_ADDS, MAX_REENTRIES, MERC_SPREAD_MAX_ATR1H,
    MERC_STOP_MAX_ATR1H, OLOG_HORIZON_H, OLOG_STOP_MIN_ATR1D, URUK_MIN_AVG_R,
    URUK_MIN_LEVEL, URUK_MIN_N, URUK_MIN_WIN_RATE, URUK_PRIVILEGE)


@dataclass(frozen=True)
class ArmyType:
    """One type: its name, what it changes, and its parameters. Line is the
    reference and changes nothing."""
    key: str
    name: str
    differs_by: tuple = ()
    overlay: bool = False
    metronome_h: float = 4.0
    decision_tf: str = "4h"
    adds: bool = True
    reentry: bool = True
    lock_waiver: bool = True
    max_adds: int = MAX_ADDS
    max_reentries: int = MAX_REENTRIES
    risk_share_max: float = LINE_RISK_SHARE_MAX
    waiver_floor_r: float = EVENT_WAIVER_FLOOR_R
    gap_min_samples: int = GAP_MIN_SAMPLES
    add_pre_shut_h: float = ADD_PRE_SHUT_H
    exotic_adds: bool = True

    #: The parameters a type's vector is made of: two types with equal
    #: vectors are one type under two names, and are merged.
    VECTOR: ClassVar[tuple] = (
        "overlay", "metronome_h", "decision_tf", "adds", "reentry",
        "lock_waiver", "max_adds", "max_reentries", "risk_share_max",
        "waiver_floor_r", "gap_min_samples", "add_pre_shut_h", "exotic_adds")

    def vector(self) -> tuple:
        return tuple(getattr(self, f) for f in self.VECTOR)


ARMY_TYPES: dict = {}


def register(t: ArmyType, *, registry=None) -> ArmyType:
    """Add a type. Refused (ValueError) when a type other than Line names
    no step it changes, or when its parameters equal another type's."""
    reg = ARMY_TYPES if registry is None else registry
    if t.key != "line" and not t.differs_by:
        raise ValueError(f"{t.key}: a type that changes nothing is a name, "
                         f"not a type (declare differs_by)")
    for other in reg.values():
        if other.key != t.key and other.vector() == t.vector():
            raise ValueError(f"{t.key} has the same parameters as "
                             f"{other.key}: one type, merge them")
    reg[t.key] = t
    return t


LINE = register(ArmyType("line", "Line Orcs"))
MERCENARIES = register(ArmyType(
    "mercenaries", "Mercenaries",
    differs_by=(("adds", "none"), ("max_adds", "0"), ("reentry", "none"),
                ("max_reentries", "0"), ("lock_waiver", "none"),
                ("metronome_h", "every hour")),
    metronome_h=1.0, adds=False, max_adds=0, reentry=False, max_reentries=0,
    lock_waiver=False))
OLOG_HAI = register(ArmyType(
    "olog_hai", "Olog-hai",
    differs_by=(("decision_tf", "1d, 4h until the symbol holds 60 fresh 1d "
                               "venue bars"),
                ("metronome_h", "once a day at the session open")),
    decision_tf="1d", metronome_h=24.0))
URUK_HAI = register(ArmyType(
    "uruk_hai", "Uruk-hai",
    differs_by=(("risk_share_max", "a full-size add (1.0) under the "
                                   "operator's PIN-granted privilege"),),
    risk_share_max=1.0))
CORSAIRS = register(ArmyType(
    "corsairs", "Corsairs of Umbar", overlay=True,
    differs_by=(("waiver_floor_r", "-0.3R"),
                ("gap_min_samples", "12 measured past prints"),
                ("add_pre_shut_h", "no add within 12 market hours of a shut"),
                ("exotic_adds", "an exotic pair never adds")),
    waiver_floor_r=CORSAIR_EVENT_WAIVER_FLOOR_R,
    gap_min_samples=CORSAIR_GAP_MIN_SAMPLES,
    add_pre_shut_h=CORSAIR_ADD_PRE_SHUT_H, exotic_adds=False))


def _ratio(stop, atr):
    try:
        stop, atr = float(stop), float(atr)
    except (TypeError, ValueError):
        return None
    if stop <= 0 or atr <= 0:
        return None
    return stop / atr


def _uruk_bar(record) -> bool:
    """The elite exception's evidence bar (portfolio/risk_gate.py:243-245),
    the lineage at Warg-rider (L2) or above, no fault in its block."""
    if not isinstance(record, dict):
        return False
    try:
        return (int(record.get("n") or 0) >= URUK_MIN_N
                and float(record.get("win_rate") or 0) >= URUK_MIN_WIN_RATE
                and float(record.get("avg_r") or 0) >= URUK_MIN_AVG_R
                and int(record.get("level") or 0) >= URUK_MIN_LEVEL
                and int(record.get("faults_in_block") or 0) == 0)
    except (TypeError, ValueError):
        return False


def _base(situation, lineage_record, privileges):
    """(key, why[]) in §1.6's order: Uruk-hai, Mercenaries, Olog-hai, Line."""
    if URUK_PRIVILEGE in (privileges or ()) and _uruk_bar(lineage_record):
        return "uruk_hai", ["the lineage clears the elite bar at Warg-rider "
                            "rank, and the operator granted the privilege"]
    persona = str(situation.get("persona") or "")
    horizon = situation.get("operator_horizon_h")
    long_horizon = horizon is not None and float(horizon) >= OLOG_HORIZON_H
    if not situation.get("manual"):
        if persona == "scalp":
            return "mercenaries", ["the config wears the scalp persona"]
        if persona == "position":
            return "olog_hai", ["the config wears the position persona"]
        if long_horizon:
            return "olog_hai", [f"the operator's thesis horizon is "
                                f"{float(horizon):.0f} market hours"]
        if persona:
            return "line", [f"the config wears the {persona} persona"]
        return "line", ["the config wears no persona"]
    # the operator's hand ticket: by its stop against the ATRs
    atr = situation.get("atr") or {}
    stop = situation.get("stop_distance")
    if stop is None or float(stop or 0) <= 0:
        if long_horizon:
            return "olog_hai", [f"the operator's thesis horizon is "
                                f"{float(horizon):.0f} market hours"]
        return "line", ["a hand ticket with no stop: nothing to measure"]
    if all(atr.get(tf) is None for tf in ("1h", "4h", "1d")):
        if long_horizon:
            return "olog_hai", [f"the operator's thesis horizon is "
                                f"{float(horizon):.0f} market hours"]
        return "line", ["no ATR is measured for this symbol: no venue or "
                        "platform bars"]
    r1h = _ratio(stop, atr.get("1h"))
    spread = _ratio(situation.get("spread"), atr.get("1h"))
    if (r1h is not None and spread is not None
            and r1h <= MERC_STOP_MAX_ATR1H and spread <= MERC_SPREAD_MAX_ATR1H):
        return "mercenaries", [f"a hand ticket with a stop of {r1h:.1f} x "
                               f"ATR(1h) and a spread of {spread:.2f} x "
                               f"ATR(1h)"]
    r1d = _ratio(stop, atr.get("1d"))
    if r1d is not None and r1d >= OLOG_STOP_MIN_ATR1D:
        return "olog_hai", [f"a hand ticket with a stop of {r1d:.1f} x "
                            f"ATR(1d)"]
    if long_horizon:
        return "olog_hai", [f"the operator's thesis horizon is "
                            f"{float(horizon):.0f} market hours"]
    r4h = _ratio(stop, atr.get("4h"))
    if r4h is None:
        return "line", ["a hand ticket: ATR(4h) is not measured for this "
                        "symbol"]
    lo, hi = LINE_STOP_ATR4H
    if lo <= r4h <= hi:
        return "line", [f"a hand ticket with a stop of {r4h:.1f} x ATR(4h)"]
    return "line", [f"a hand ticket with a stop of {r4h:.1f} x ATR(4h), "
                    f"outside every other type's band"]


def corsair_overlay(situation) -> tuple:
    """(on, why[]): the deep-water overlay. A weekend, overnight or holiday
    shut inside the expected hold (a short daily break is not one), a 24/7
    crypto weekend inside it, two or more high-impact prints on its
    currencies, an exotic pair, or a measured gap p90 of 0.5R or more. An
    unmeasured gap adds nothing."""
    why = []
    seen = set()
    for s in situation.get("shuts") or ():
        kind = str((s or {}).get("kind") or "")
        if kind not in ("weekend", "overnight", "holiday") or kind in seen:
            continue
        seen.add(kind)
        article = "an" if kind[:1] in "aeiou" else "a"
        why.append(f"{article} {kind} shut inside the expected hold "
                   f"({s.get('words') or s.get('at')})")
    if situation.get("crypto_weekend"):
        why.append("a crypto weekend inside the expected hold: thin books, "
                   "no shut to wait behind")
    prints = int(situation.get("prints") or 0)
    if prints >= CORSAIR_MIN_PRINTS:
        why.append(f"{prints} high-impact prints on its currencies inside "
                   f"the expected hold")
    legs = [str(x) for x in situation.get("exotic_legs") or ()]
    if legs:
        why.append(f"an exotic pair: {', '.join(legs)} "
                   f"{'is' if len(legs) == 1 else 'are'} outside the theme "
                   f"currencies")
    gap = situation.get("gap_p90_r")
    if gap is not None:
        try:
            if float(gap) >= CORSAIR_GAP_P90_R:
                why.append(f"a measured gap p90 of {float(gap):.2f}R")
        except (TypeError, ValueError):
            pass
    return bool(why), why


def assign(situation, *, lineage_record=None, privileges=frozenset()) -> dict:
    """{"base", "why", "overlay", "overlay_why"} at birth. O1 passes no
    lineage record and no privilege, so Uruk-hai is unreachable until the
    ranks (O2) and the operator's PIN exist."""
    base, why = _base(situation or {}, lineage_record, privileges)
    on, overlay_why = corsair_overlay(situation or {})
    return {"base": base, "why": why,
            "overlay": CORSAIRS.key if on else "", "overlay_why": overlay_why}


def name_of(key) -> str:
    t = ARMY_TYPES.get(str(key or ""))
    return t.name if t is not None else str(key or "")
