"""THE ROUTER (the O2 spec B.1, B.5, B.6, B.9-B.11; O2b, 2026-11-06): pure.

    route(band, world, kind, day_class, frontier_left, gate, effort_mode,
          *, score, raw_band)
      -> {rung, would_rung, why, escalated, probes, twin, routing_version}

It chooses the rung a model would read one wake on, from what the render
already computed: the band, with the floors F1-F4 in it (complexity.py),
and the band with no floor; the money world; the day's class; the
frontier quota left; the Fable gate's verdict; the effort map. It reads
no seat level, scar, probation or privilege, so no consequence lowers a
tier (complexity.py), and it names no model: the effort map
(`effort_mode`, {rung: the rung that answers it}) is the caller's, built
from the gateway's ladder and the smoke's verdicts (mind.answering_map).
This module holds rung names only and imports the constants alone.

TABLE V1 (ROUTING_VERSION "table-v1", the notes of the catalog's ladder):

    routine    r0
    material   r1 on paper and demo; r2 on real money
    complex    r3
    extreme    r5 when the Fable gate passes (B.9); else r4, with the
               failing clause in `why`

h0 is never routed: it is a paper probe's rung only. Real money is the
budget's world (scheduler.is_real: the seat AND the row's own world
live), which the caller reads and hands on as "live"; demo, and a row
that states no money world, route as paper (§4 Q6).

  would_rung  the table's pick
  rung        the answering rung: would_rung through the effort map (B.5,
              one effort per model until the smoke's PASS for its family)
  why         code's own words, never a model's
  escalated   a floor raised the band: `raw_band` is the band with no
              floor (B.6). No wake is ever asked again on a higher rung
  probes      the probes the wake is eligible for (B.11), paper and demo
              only, on calm and eventful days (weather.caps_for: none on
              a stormy day): h0, and the boundary probe when `score` is
              within BAND_HYSTERESIS of 30, 55 or 75, on the rung across
              that boundary after the map, dropped when it is the wake's
              own answering rung. Each {kind, rung, would_rung, boundary}
  twin        r5 answers, so its r4 blind twin runs beside it (B.10)

The Fable gate (B.9) holds when every clause does. `gate` is the caller's
verdict on the clauses only it can read (the switch, the money, the
render): "" when they pass, else the failing clause in words; anything
else reads closed. The router adds its own two: real money, and a
frontier quota left today.

FABLE'S GATE (O2b's frontier, 2026-11-06, B.9; `fable_gate`, pure): its
clauses in their order, each read only when every clause before it holds,
the first that fails being the gate's verdict: real money; the band
extreme; a frontier quota left today (OrcSetting frontier_per_day, 0 by
default, less the user's r5 calls today: mind.frontier_left, never the day
row); the frontier switch (orcs_frontier) ON; the pair (r5 and its r4
blind twin, priced at the dossier's size cap) under the wake's class's
ceiling and the deep tiers' share; the pair within the money the Orcs may
hold in flight (scheduler.fable_money); the Fable render within its size
cap. The caller (wake._fable_gate, at the render) reads them and hands the
verdict on as `gate`, its quota left as `frontier_left`. The pair is about
$3.57 at the cap, above the $3.00 the Orcs may hold in flight, so in O2
the gate cannot open: an extreme wake routes r4, the clause in `why`.

O2b's first commit (2026-11-06) records the route in shadow; its second
lets the route's rung answer behind the router's switch (orcs_router, OFF
as it ships: r0 answers every wake a model reads), which the scheduler
reads, never this module. The probes listed here are sent by
bot_program/orcs/probes.py behind the probes' switch (orcs_probes, OFF as
it ships; O2b's third commit), never by this module; r5's twin is sent by
mind.think beside its r5 wake, behind the frontier's switch (orcs_frontier,
OFF as it ships; O2b's fourth commit).

B.1's signature has neither `score` nor `raw_band`: B.11's boundary
probe needs the score, and B.6's escalated the band with no floor.
"""
from bot_program.orcs.constants import (BAND_COMPLEX_MAX, BAND_HYSTERESIS,
                                        BAND_MATERIAL_MAX, BAND_ROUTINE_MAX,
                                        ROUTING_VERSION, RUNG_LIMITS,
                                        VENUE_DEMO, VENUE_LIVE, VENUE_PAPER)

#: The bands, lowest first (complexity.BANDS).
BANDS = ("routine", "material", "complex", "extreme")
#: Table v1: each band's rung (paper, real money). Extreme's r4 is the
#: rung when the Fable gate fails; r5 only through it.
TABLE_V1 = {"routine": ("r0", "r0"), "material": ("r1", "r2"),
            "complex": ("r3", "r3"), "extreme": ("r4", "r4")}
#: Fable's rung, its blind twin's (B.10) and the probe that never decides.
FRONTIER, TWIN, PROBE_H0 = "r5", "r4", "h0"
#: The ladder's rung names (RUNG_LIMITS): what a map may answer with.
RUNGS = tuple(sorted(RUNG_LIMITS))
#: The bands' boundaries (B.11), each with the two bands it parts.
BOUNDARIES = ((BAND_ROUTINE_MAX, "routine", "material"),
              (BAND_MATERIAL_MAX, "material", "complex"),
              (BAND_COMPLEX_MAX, "complex", "extreme"))
#: The days a probe may run on (B.11; weather.caps_for: none on a stormy
#: day). An unknown day lists none.
PROBE_DAYS = ("calm", "eventful")
#: The Fable gate as the caller hands it while it is not evaluated (O2b's
#: first commit): closed, in its own words.
GATE_CLOSED = "the Fable gate is closed"
#: The router's own clauses of the gate (B.9).
NOT_REAL = "Fable answers real money only"
NO_QUOTA = "no frontier quota is left today"
#: The rest of Fable's gate, in its order (B.9; O2b's frontier,
#: 2026-11-06): the band; the switch; the pair's money, by its code
#: (scheduler.class_money_code's triage, deep_share, inflight); the Fable
#: render, after it is written (B.4b), or its absence.
NOT_EXTREME = "the band is not extreme"
FRONTIER_OFF = "the frontier switch (orcs_frontier) is off"
PAIR_CLASS = "the pair does not fit under its class's ceiling"
PAIR_DEEP = "the pair does not fit under the deep tiers' share"
PAIR_INFLIGHT = "the pair is above the money the Orcs may hold in flight"
PAIR_MONEY = {"triage": PAIR_CLASS, "deep_share": PAIR_DEEP,
              "inflight": PAIR_INFLIGHT}
FABLE_OVER = "its Fable dossier is over the size cap"
NO_FABLE_DOSSIER = ("no Fable dossier is written while the router's switch "
                    "(orcs_router) is off")
NOT_FABLE_STORED = "its stored dossier was not written for Fable"
#: The world's words when it is not plainly real money or paper.
DEMO_AS_PAPER = "demo routes as paper"
NO_WORLD_AS_PAPER = "a row that states no money world routes as paper"
UNKNOWN_BAND = "an unknown band routes as routine"


def _rank(band) -> int:
    return BANDS.index(band) if band in BANDS else -1


def _count(n) -> int:
    try:
        return int(n)
    except (TypeError, ValueError):
        return 0


def _float(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and v not in (float("inf"), float("-inf")) else None


def answering(rung, effort_mode) -> str:
    """The rung that answers `rung` under the effort map (B.5). `rung`
    itself when the map names no ladder rung for it; a routed rung never
    answers as h0, and h0 never as a routed rung."""
    got = effort_mode.get(rung) if isinstance(effort_mode, dict) else None
    if got not in RUNGS or (got == PROBE_H0) != (rung == PROBE_H0):
        return rung
    return got


def fable_clause(real, frontier_left, gate) -> str:
    """The Fable gate's failing clause (B.9), "" when every clause holds:
    the caller's verdict first (`gate`: "" passes, else its clause; not a
    text reads closed), then the router's own: real money, a frontier
    quota left today."""
    clause = gate if isinstance(gate, str) else GATE_CLOSED
    if clause:
        return clause
    if not real:
        return NOT_REAL
    if _count(frontier_left) <= 0:
        return NO_QUOTA
    return ""


def fable_gate(*, real, band, quota, switch, money, render="") -> str:
    """Fable's gate (B.9): the first clause that fails, in words; "" when
    every clause holds. In this order, each read only when every clause
    before it holds (`quota`, `switch`, `money` and `render` may be the
    caller's callables, so nothing is read for a gate that already
    failed): real money (`real`); the band extreme; a frontier quota left
    today (`quota`, the count left); the frontier switch ON (`switch`);
    the pair's money (`money`, class_money_code's code: "" when the pair
    fits under its class's ceiling, the deep tiers' share and the money
    the Orcs may hold in flight; another code is its words, an unknown one
    reads closed); the Fable render within its cap (`render`: "" when it
    is, else its clause). Pure: the reads are the caller's."""
    def read(x):
        return x() if callable(x) else x
    if not real:
        return NOT_REAL
    if band != "extreme":
        return NOT_EXTREME
    if _count(read(quota)) <= 0:
        return NO_QUOTA
    if not read(switch):
        return FRONTIER_OFF
    code = read(money)
    if code:
        return PAIR_MONEY.get(str(code), GATE_CLOSED)
    clause = read(render)
    return clause if isinstance(clause, str) else GATE_CLOSED


def table(band, real, clause) -> tuple:
    """(rung, its words) of table v1 for a known band, the Fable gate's
    failing clause beside an extreme band ("" lets r5 answer)."""
    if band == "extreme":
        if clause:
            return TABLE_V1[band][1], f"extreme: r4, {clause}"
        return FRONTIER, "extreme, every clause of the Fable gate holds: r5"
    rung = TABLE_V1[band][1 if real else 0]
    if band == "material":
        return rung, (f"material on real money: {rung}" if real
                      else f"material on paper: {rung}")
    return rung, f"{band}: {rung}"


def _probes(band, real, day_class, score, effort_mode, rung) -> list:
    """B.11: the probes a paper or demo wake is eligible for, none on real
    money or on a stormy day: h0; the rung across a boundary within
    BAND_HYSTERESIS of the score, after the map, unless it is the wake's
    own answering rung. A band its score does not border (a held band)
    has no boundary probe."""
    if real or day_class not in PROBE_DAYS:
        return []
    out = [{"kind": "h0", "rung": answering(PROBE_H0, effort_mode),
            "would_rung": PROBE_H0, "boundary": None}]
    s = _float(score)
    if s is None:
        return out
    for edge, lo, hi in BOUNDARIES:
        if abs(s - edge) > BAND_HYSTERESIS:
            continue
        across = hi if band == lo else lo if band == hi else None
        if across is None:
            continue
        would, _words = table(across, False, NOT_REAL)
        probe = answering(would, effort_mode)
        if probe == rung:
            continue
        out.append({"kind": "boundary", "rung": probe, "would_rung": would,
                    "boundary": int(edge)})
    return out


def route(band, world, kind, day_class, frontier_left, gate, effort_mode,
          *, score, raw_band) -> dict:
    """The route of one wake (table v1). `world` is the budget's money
    world: "live" is real money, anything else routes as paper. `kind`
    (the wake's: birth, routine, material) is read by no rule of table v1:
    F1 and F2 are already in the band. Never raises."""
    why = []
    if band not in BANDS:
        why.append(UNKNOWN_BAND)
        band = "routine"
    real = world == VENUE_LIVE
    clause = fable_clause(real, frontier_left, gate) \
        if band == "extreme" else ""
    would, words = table(band, real, clause)
    why.append(words)
    if world == VENUE_DEMO:
        why.append(DEMO_AS_PAPER)
    elif world not in (VENUE_LIVE, VENUE_PAPER):
        why.append(NO_WORLD_AS_PAPER)
    escalated = _rank(raw_band) >= 0 and _rank(band) > _rank(raw_band)
    if escalated:
        why.append(f"a floor raised the band from {raw_band}")
    rung = answering(would, effort_mode)
    if rung != would:
        why.append(f"one effort per model until the smoke's PASS: {would} "
                   f"answers as {rung}")
    return {"rung": rung, "would_rung": would, "why": why,
            "escalated": bool(escalated),
            "probes": _probes(band, real, day_class, score, effort_mode,
                              rung),
            "twin": rung == FRONTIER, "routing_version": ROUTING_VERSION}
