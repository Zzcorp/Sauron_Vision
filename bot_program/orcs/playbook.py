"""THE PLAYBOOK (spec §5.4, D2 §7): the deterministic candidates, pure.

It builds the candidate menu a wake will see (O2), and it runs the third
graded arm (P, bot_program/orcs/ghost.py): the care, plus the structure
trail, the draw trim and the thesis exit, as code. The list is UNORDERED:
returned sorted by id, never ranked, so no model is anchored on the policy
it is graded against.

In O1 the playbook lists only what reduces or holds:
  T-STRUCT   tighten/trail: from MFE >= 0.5R (simulate.STRUCTURE_FROM_R),
             the latest untaken swing of the trail timeframe (1h below +2R
             MFE, 4h from +2R), its stop beyond the crowd's levels (the
             menu's), with room >= MIN_STOP_ROOM_ATR x ATR(tf) on p AND m,
             within MAX_LEVEL_DIST_ATR4H x ATR(4h) of m, and only if tighter
             than the effective stop
  T-CARE     adopt the care's lock: always listed, the mechanical answer
  H-HOLD     hold: always
  K-DRAW     trim: the mark within KDRAW_ATR4H x ATR(4h) of the draw on
             liquidity (thesis_check.structure_read, venue bars), on paper
             or with two legs or more
  X-THESIS   exit: a fresh thesis-check "exit" or a met predicate
  P-LOCK / P-TRIM   a high-impact print within PRINT_WITHIN_H
  P-HOLD     the same, only when gaps.waiver_check clears

THE SEAM: the risk-adding candidates (A-CONFIRM, R-RECLAIM, V-REVERSE,
W-WIDEN) need the mandate's officer (orcs/mandate.py, O2) and arrive with
it; none is ever listed here.
"""
from dataclasses import dataclass, field
from datetime import timedelta

from bot_program.orcs.constants import (KDRAW_ATR4H, MAX_LEVEL_DIST_ATR4H,
                                        MIN_STOP_ROOM_ATR, PRED_MET,
                                        PRINT_WITHIN_H, THESIS_FRESH_H,
                                        TSTRUCT_SWITCH_R)

#: simulate.STRUCTURE_FROM_R (backtester/proving/simulate.py:79), copied so
#: this module stays pure; pinned equal by tests/orcs/test_orc_playbook.py.
STRUCTURE_FROM_R = 0.5
#: Never listed in O1 (the seam above).
RISK_ADDING = ("A-CONFIRM", "R-RECLAIM", "V-REVERSE", "W-WIDEN")


@dataclass(frozen=True)
class Candidate:
    id: str
    action: str
    level_ids: tuple = ()
    after: dict = field(default_factory=dict)


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def _d(side) -> int:
    return 1 if str(side or "").upper() == "BUY" else -1


def trail_tf(mfe_r) -> str:
    return "4h" if (mfe_r or 0) >= TSTRUCT_SWITCH_R else "1h"


def t_struct(rows, *, side, mfe_r, p, m, effective, atr):
    """The T-STRUCT level ({id, level_id, stop, tf}) or None."""
    mfe_r = _f(mfe_r)
    if mfe_r is None or mfe_r < STRUCTURE_FROM_R:
        return None
    sign = _d(side)
    tf = trail_tf(mfe_r)
    atr = atr or {}
    a, a4 = _f(atr.get(tf)), _f(atr.get("4h")) or _f(atr.get(tf))
    p, m = _f(p), _f(m)
    if not a or not a4 or p is None or m is None:
        return None
    want = "below" if sign > 0 else "above"
    swings = [r for r in rows or ()
              if r.get("tf") == tf and r.get("kind") == "swing"
              and r.get("side") == want and _f(r.get("stop")) is not None]
    if not swings:
        return None
    latest = max(swings, key=lambda r: (r.get("origin") or 0,
                                        sign * float(r["price"])))
    stop = float(latest["stop"])
    room = MIN_STOP_ROOM_ATR * a
    if sign * (p - stop) < room or sign * (m - stop) < room:
        return None
    if abs(m - stop) > MAX_LEVEL_DIST_ATR4H * a4:
        return None
    eff = _f(effective)
    if eff is not None and sign * (stop - eff) <= 0:
        return None
    return {"id": "T-STRUCT", "level_id": latest["id"], "stop": stop,
            "tf": tf}


def k_draw(*, side, m, draw, atr4h, paper, legs=1, done=()):
    """The K-DRAW trim ({id, level_id, draw}) or None: the mark within
    KDRAW_ATR4H x ATR(4h) of the draw on liquidity, on paper or with two
    legs, once per draw."""
    m, a4 = _f(m), _f(atr4h)
    price = _f((draw or {}).get("price")) if isinstance(draw, dict) \
        else _f(draw)
    if m is None or not a4 or price is None:
        return None
    if not (paper or int(legs or 1) >= 2):
        return None
    if abs(m - price) > KDRAW_ATR4H * a4:
        return None
    level_id = f"DRAW-{price:g}"
    if level_id in set(done or ()):
        return None
    return {"id": "K-DRAW", "level_id": level_id, "draw": price}


def x_thesis(thesis_meta, predicate_results, now):
    """{why} when the thesis check reads exit within THESIS_FRESH_H, or a
    predicate is met; else None."""
    th = thesis_meta if isinstance(thesis_meta, dict) else {}
    if th.get("verdict") == "exit":
        from django.utils.dateparse import parse_datetime
        at = parse_datetime(str(th.get("at") or "")) if th.get("at") else None
        if at is not None:
            if at.tzinfo is None:
                from datetime import timezone as dt_tz
                at = at.replace(tzinfo=dt_tz.utc)
            if now - at <= timedelta(hours=THESIS_FRESH_H):
                return {"why": "the thesis check reads exit"}
    for res in predicate_results or ():
        state = res.get("state") if isinstance(res, dict) \
            else getattr(res, "state", None)
        if state == PRED_MET:
            kind = res.get("kind") if isinstance(res, dict) \
                else getattr(res, "kind", "")
            return {"why": f"invalidation met ({kind})"}
    return None


def candidates(rows, ctx) -> list:
    """The unordered candidate list (sorted by id): T-STRUCT, T-CARE,
    H-HOLD, K-DRAW, X-THESIS and the print set. `ctx`: side, mfe_r, p, m,
    effective, atr, draw, paper, legs, kdraw_done, thesis, predicates, now,
    print ({title, minutes} of the next high-impact print, or None),
    waiver ((ok, why, gap_r) from gaps.waiver_check, or None)."""
    ctx = ctx or {}
    out = [Candidate("H-HOLD", "hold")]
    ids = {r.get("id") for r in rows or ()}
    if "CARE" in ids:
        out.append(Candidate("T-CARE", "tighten", ("CARE",)))
    else:
        out.append(Candidate("T-CARE", "tighten"))
    ts = t_struct(rows, side=ctx.get("side"), mfe_r=ctx.get("mfe_r"),
                  p=ctx.get("p"), m=ctx.get("m"),
                  effective=ctx.get("effective"), atr=ctx.get("atr"))
    if ts:
        out.append(Candidate("T-STRUCT", "tighten", (ts["level_id"],),
                             {"stop": ts["stop"], "tf": ts["tf"]}))
    kd = k_draw(side=ctx.get("side"), m=ctx.get("m"), draw=ctx.get("draw"),
                atr4h=(ctx.get("atr") or {}).get("4h"),
                paper=ctx.get("paper"), legs=ctx.get("legs") or 1,
                done=ctx.get("kdraw_done") or ())
    if kd:
        out.append(Candidate("K-DRAW", "trim", (kd["level_id"],),
                             {"draw": kd["draw"]}))
    if ctx.get("now") is not None:
        xt = x_thesis(ctx.get("thesis"), ctx.get("predicates"), ctx["now"])
        if xt:
            out.append(Candidate("X-THESIS", "exit", (), {"why": xt["why"]}))
    pr = ctx.get("print")
    if isinstance(pr, dict) and pr.get("minutes") is not None \
            and 0 <= float(pr["minutes"]) <= PRINT_WITHIN_H * 60:
        out.append(Candidate("P-LOCK", "tighten", ("BE",)))
        out.append(Candidate("P-TRIM", "trim"))
        waiver = ctx.get("waiver")
        if waiver and waiver[0]:
            out.append(Candidate("P-HOLD", "hold", (),
                                 {"gap_r": waiver[2]}))
    return sorted(out, key=lambda c: c.id)
