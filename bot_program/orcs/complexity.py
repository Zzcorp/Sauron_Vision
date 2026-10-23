"""THE COMPLEXITY SCORE (spec §7.5.1-7.5.2): pure.

    score = sum(w_i x s_i) + stakes, clamped to 0..100, then the floors

Each s_i runs 0..100 through piecewise-linear breakpoints, the house form
of market_stress.COMPONENTS. The market terms (vol, regime, prints, news,
stress, gap) are the class's hourly complexity; the position and decision
terms (stop, decision_point, size, disagreement, reversibility) are read
on every wake. O1 journals the vector, the score, the band and the day's
class on every detected wake and routes NOTHING (the router is O2's).

A missing input is a dash with its reason and adds nothing (a stale
posture zeroes `stress`, a blind analyst zeroes `news`, an unread calendar
zeroes `prints`), and never abstains: only the three critical items of
PS13 set F5 (bot_program/orcs/integrity.py). The spec's §7.5.1 table says
"analyst blind -> 50"; its revision of 2026-10-15 (§7.5.2 F5) zeroes
`news` and prints the dash. The revision wins here.

The day score (§7.5.3) renormalises the six market terms over their own
weights (0.58), so a day can reach 100: the spec is silent, and without it
a day could read stormy only near the maximum of every term.

Nothing here reads a lineage's standing, a fault mark, a probationary
period or the operator's privileges (§7.5.1): no consequence lowers the
tier of a live decision.
"""
from bot_program.orcs.constants import (BAND_COMPLEX_MAX, BAND_HYSTERESIS,
                                        BAND_MATERIAL_MAX,
                                        BAND_ROUTINE_MAX,
                                        COMPLEXITY_BREAKPOINTS,
                                        COMPLEXITY_WEIGHTS, REVERSIBILITY,
                                        STAKES_HAND, STAKES_L3, STAKES_REAL,
                                        STAKES_WOUND)

BANDS = ("routine", "material", "complex", "extreme")
MARKET_KEYS = ("vol", "regime", "prints", "news", "stress", "gap")
#: The prints that count double (§7.5.1).
MAJOR_PRINTS = ("FOMC", "NON-FARM", "NFP", "CPI", "FEDERAL FUNDS")
STRESS_NOT_MEASURED = "— (not measured: crisis_mode off)"
CALENDAR_UNREAD = "— (calendar unread)"


def piecewise(x, points) -> float:
    """Linear between the breakpoints, flat beyond them (x ascending)."""
    pts = sorted((float(a), float(b)) for a, b in points)
    x = float(x)
    if x <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0) if x1 > x0 else y1
    return pts[-1][1]


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def _c(s, x=None, why="", dash="") -> dict:
    return {"s": round(float(s), 2), "x": x, "why": str(why or ""),
            "dash": str(dash or "")}


def _vol(x):
    x = _f(x)
    if x is None:
        return _c(0, dash="— (no ATR(1h) history)")
    return _c(piecewise(x, COMPLEXITY_BREAKPOINTS["vol"]), round(x, 3),
              f"ATR(1h) at {x:.2f} x its median")


def _regime(r):
    r = r if isinstance(r, dict) else {}
    parts = []
    h = _f(r.get("posture_changed_h"))
    if h is not None and 0 <= h < 4:
        parts.append((100.0 * (1 - h / 4.0), "the posture changed today"))
    if r.get("symbol_flip"):
        parts.append((70.0, "the symbol's regime flipped within 6 bars"))
    if r.get("brain_changed"):
        parts.append((50.0, "the Mind's label changed since the roll"))
    conf = _f(r.get("brain_conf"))
    if conf is not None and conf < 0.5:
        parts.append((30.0, f"the Mind's confidence {conf:.2f}"))
    if not parts:
        return _c(0, why="no regime change")
    s, why = max(parts)
    return _c(s, why=why)


def _prints(p):
    p = p if isinstance(p, dict) else {}
    if p.get("unread"):
        return _c(0, dash=CALENDAR_UNREAD)
    within = int(p.get("within_3h") or 0)
    if p.get("major") and within:
        within += 1                      # FOMC, NFP and CPI count double
    in_24h = int(p.get("in_24h") or 0)
    if within >= 2:
        return _c(100, within, "two or more high-impact prints within 3 h")
    if p.get("in_window"):
        return _c(80, within, "inside an event window")
    if within == 1:
        return _c(50, within, "a high-impact print within 3 h")
    if in_24h >= 1:
        return _c(20, in_24h, "a high-impact print within 24 h")
    return _c(0, 0, "no high-impact print within 24 h")


def _news(n):
    n = n if isinstance(n, dict) else {}
    if n.get("blind"):
        since = str(n.get("since") or "the analyst's last run: never")
        if since[:2].isdigit():
            since = f"{since} UTC"
        return _c(0, dash=f"— (tags blind since {since})")
    ratio = _f(n.get("ratio"))
    if ratio is None:
        return _c(0, dash="— (no 30-day median of urgent items)")
    return _c(piecewise(ratio, COMPLEXITY_BREAKPOINTS["news"]),
              round(ratio, 2), f"urgent items at {ratio:.1f} x the median")


def _stress(st):
    st = st if isinstance(st, dict) else {}
    score = _f(st.get("score"))
    if not st.get("fresh") or score is None:
        return _c(0, dash=STRESS_NOT_MEASURED)
    s = score
    term = _f(st.get("vix_term"))
    why = f"stress score {score:.0f}"
    if term is not None and term >= 1.0:
        s += 20
        why += f", VIX/VIX3M {term:.2f} inverted"
    return _c(min(100.0, s), round(score, 1), why)


def _gap(g):
    g = g if isinstance(g, dict) else {}
    if g.get("unread"):
        return _c(0, dash=CALENDAR_UNREAD)
    if not g.get("shut_within_6h"):
        return _c(0, why="no shut within 6 market hours")
    r = _f(g.get("gap_r"))
    if r is None:
        return _c(60, why="a shut within 6 market hours, its gap unmeasured")
    return _c(piecewise(r, COMPLEXITY_BREAKPOINTS["gap"]), round(r, 3),
              f"a shut within 6 market hours, gap p90 {r:.2f}R")


def _stop(x):
    """x: the SIGNED distance from the closing-side mark to the effective
    stop on the side it protects, in ATR(1h) (wake._position_inputs). At or
    under 0.5 scores 100, a mark already through the stop (x <= 0)
    included."""
    x = _f(x)
    if x is None:
        return _c(0, dash="— (no stop or no ATR(1h))")
    why = (f"the stop {x:.1f} x ATR(1h) away" if x > 0 else
           f"the mark is through the stop ({-x:.1f} x ATR(1h) beyond it)")
    return _c(piecewise(x, COMPLEXITY_BREAKPOINTS["stop"]), round(x, 3),
              why)


def _decision(n):
    n = int(n or 0)
    s = 0 if n <= 0 else (60 if n == 1 else 100)
    return _c(s, n, f"{n} decision point(s)" if n else "no decision point")


def _size(x):
    x = _f(x)
    if x is None:
        return _c(0, dash="— (the open-risk limit is unread)")
    return _c(piecewise(x, COMPLEXITY_BREAKPOINTS["size"]), round(x, 3),
              f"{x:.0%} of the open-risk limit at its stops")


def _disagreement(d):
    d = d if isinstance(d, dict) else {}
    flags = [str(f) for f in d.get("flags") or ()]
    disp = _f(d.get("dispersion"))
    base = (piecewise(disp, COMPLEXITY_BREAKPOINTS["disagreement"])
            if disp is not None else 0.0)
    s = min(100.0, base + 20.0 * len(flags))
    dash = "" if disp is not None else "— (no council stance recorded)"
    return _c(s, disp, "; ".join(flags), dash)


def _reversibility(rv):
    rv = rv if isinstance(rv, dict) else {}
    key = str(rv.get("r") or "R0")
    s = float(REVERSIBILITY.get(key, 0))
    if rv.get("shadow"):
        s /= 2.0                          # a shadow-only candidate: half
    return _c(s, key, f"{key} on the table"
              + (" (shadow)" if rv.get("shadow") else ""))


_BUILDERS = {
    "vol": ("atr_ratio", _vol), "regime": ("regime", _regime),
    "prints": ("prints", _prints), "news": ("news", _news),
    "stress": ("stress", _stress), "gap": ("gap", _gap),
    "stop": ("stop_atr", _stop), "decision_point": ("decision_points",
                                                    _decision),
    "size": ("size_share", _size), "disagreement": ("disagreement",
                                                    _disagreement),
    "reversibility": ("reversibility", _reversibility),
}


def components(inputs) -> dict:
    """{key: {s, x, why, dash}} for every weighted key."""
    inputs = inputs if isinstance(inputs, dict) else {}
    return {key: build(inputs.get(src))
            for key, (src, build) in _BUILDERS.items()}


def score(comps, stakes_=0) -> float:
    total = sum(COMPLEXITY_WEIGHTS[k] * float((comps.get(k) or {}).get("s")
                                              or 0.0)
                for k in COMPLEXITY_WEIGHTS)
    return round(max(0.0, min(100.0, total + float(stakes_ or 0))), 2)


def stakes(*, real, hand, wounded=False, level=0) -> int:
    return ((STAKES_REAL if real else 0) + (STAKES_HAND if hand else 0)
            + (STAKES_WOUND if wounded else 0)
            + (STAKES_L3 if int(level or 0) >= 3 else 0))


def f5(integrity) -> tuple:
    """(on, items): F5 is the integrity verdict's CRITICAL items only."""
    items = list((integrity or {}).get("critical") or [])
    return bool(items), items


def f6(reasons, facts_hash, last_answered_hash) -> bool:
    """Quiet: every reason a W2 or W11, the facts unchanged since the last
    answered wake."""
    codes = [r.get("code") if isinstance(r, dict) else r
             for r in reasons or ()]
    return (bool(codes) and all(c in ("W2", "W11") for c in codes)
            and bool(last_answered_hash)
            and str(facts_hash) == str(last_answered_hash))


def _rank(b) -> int:
    return BANDS.index(b) if b in BANDS else 0


def floors(*, kind, real, binding_on_table, day_class, birth) -> object:
    """The lowest band the floors allow (F1-F4), or None. In O1 every Orc
    is at L0, so nothing binds and F3/F4 never apply; F2 (a real-money
    birth) does."""
    out = None

    def at_least(b):
        nonlocal out
        if out is None or _rank(b) > _rank(out):
            out = b
    if kind == "confirm":
        at_least("complex" if real else "material")          # F1
    if birth and real:
        at_least("complex")                                  # F2
    if binding_on_table and real:
        at_least("material")                                 # F3
        if day_class == "stormy":
            at_least("material")                             # F4
    return out


def _raw(sc) -> str:
    if sc < BAND_ROUTINE_MAX:
        return "routine"
    if sc < BAND_MATERIAL_MAX:
        return "material"
    if sc < BAND_COMPLEX_MAX:
        return "complex"
    return "extreme"


def band(sc, *, prev_band=None, hold_until=None, now=None, floor=None) -> str:
    """The band, with BAND_HYSTERESIS points to cross a boundary, held
    until `hold_until` (BAND_HOLD_AFTER_URGENT_MIN after an urgent wake,
    set by bot_program/orcs/wake.py: it may rise, never fall, while held),
    then raised to `floor`."""
    sc = float(sc or 0.0)
    if prev_band not in BANDS:
        out = _raw(sc)
    else:
        up, down = _raw(sc - BAND_HYSTERESIS), _raw(sc + BAND_HYSTERESIS)
        if _rank(up) > _rank(prev_band):
            out = up
        elif _rank(down) < _rank(prev_band):
            out = down
        else:
            out = prev_band
        if hold_until is not None and now is not None and now < hold_until \
                and _rank(out) < _rank(prev_band):
            out = prev_band
    if floor in BANDS and _rank(floor) > _rank(out):
        out = floor
    return out


def day_score(market) -> float:
    """The day's score: the market terms over their own weights."""
    w = sum(COMPLEXITY_WEIGHTS[k] for k in MARKET_KEYS)
    total = sum(COMPLEXITY_WEIGHTS[k] * float((market.get(k) or {}).get("s")
                                              or 0.0)
                for k in MARKET_KEYS)
    return round(max(0.0, min(100.0, total / w)), 2) if w else 0.0


def day_class(sc, *, posture_level, posture_fresh, prints_today) -> str:
    """calm < 30, eventful 30 to < 55, stormy >= 55, or on a stressed,
    crisis or recovery posture (only while measured), or on three
    high-impact prints today on the class's currencies."""
    if (posture_fresh and str(posture_level) in ("stressed", "crisis",
                                                 "recovery")) \
            or int(prints_today or 0) >= 3 or float(sc or 0) >= \
            BAND_MATERIAL_MAX:
        return "stormy"
    if float(sc or 0) >= BAND_ROUTINE_MAX:
        return "eventful"
    return "calm"
