"""THE THESIS'S PREDICATES (spec §1.4): machine-checkable, written by code at
birth, checked by code on every tick, journaled as FACTS on their
transitions only. "The thesis is dead" never depends on a model remembering.

  time{market_h, min_mfe_r}        the hold spent (position_care.market_hours,
                                   the care's own clock: weekends of a market
                                   that shuts do not count) with the best
                                   excursion still under min_mfe_r
  displaced_bos_against{tf}        a fresh break of structure against the
                                   position, displaced and not reclaimed,
                                   AFTER the birth, as thesis_check reads it
                                   (structure_read on the venue's frame)
  close_beyond{tf, level_id, level, side}
                                   a CLOSED venue bar past a frozen menu
                                   level, opened AFTER the birth

Forward only (§6.2): a bar predicate never reads a bar from before the
Orc's birth, so an adopted row's history meets nothing.

Final bars only (2026-10-22): the bar refresh stores the forming candle
and rewrites it on its next pass, so a bar that just ended is a snapshot
until then (bars.final_bar). A bar predicate reads FINAL bars only, the
structure read included, and is read again only when a new final bar
exists (its end and its close are remembered): a snapshot never writes a
met that stays met, nor hides the final bar for a whole decision bar.

A predicate whose venue bars are missing or older than two bar lengths of
open market is UNCHECKED, and says so once ("a predicate can never be
silently dead", §1.4); it is checked again, and says so, when fresh bars
return. The time predicate is UNCHECKED, past its hours, while the care
has measured no best excursion (the care switched off): an unread
excursion is never read as a small one. A met predicate stays met. Its
state lives in Orc.seen["predicates"], merged with the fact under the
Orc's lock.

O1 writes facts only. THE SEAM: a met predicate is an urgent W8 wake from O2
(`# O2: wake.request(orc, "W8", urgent=True)` below); nothing here wakes,
moves or sends anything.
"""
import logging
from dataclasses import asdict, dataclass
from datetime import timezone as dt_tz

from bot_program.orcs.constants import (DAILY_DECISION_MIN_BARS, PRED_MET,
                                        PRED_UNCHECKED, PRED_UNMET)

logger = logging.getLogger(__name__)

TIME, BOS, CLOSE = "time", "displaced_bos_against", "close_beyond"
#: The bars predicates read when the thesis names none.
DEFAULT_TF = "4h"
#: A hand idea's structure predicate and every bot idea's.
STRUCTURE_KINDS = ("swing", "pool")


@dataclass(frozen=True)
class Result:
    key: str
    kind: str
    state: str
    why: str = ""
    bar_at: object = None

    def as_dict(self) -> dict:
        out = asdict(self)
        at = out.get("bar_at")
        out["bar_at"] = at.isoformat() if hasattr(at, "isoformat") else at
        return out


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def key_of(pred) -> str:
    pred = pred or {}
    return ":".join(str(pred.get(k) or "") for k in ("kind", "tf",
                                                     "level_id"))


def decision_tf(asset_class, army_type, menu=None) -> str:
    """4h; 1d for a stock, an ETF or an Olog-hai idea once the symbol holds
    DAILY_DECISION_MIN_BARS fresh 1d venue bars (§1.6)."""
    daily = (str(asset_class) in ("stock", "etf")
             or str(army_type or "") == "olog_hai")
    if not daily or menu is None:
        return DEFAULT_TF
    n = int((getattr(menu, "n", {}) or {}).get("1d") or 0)
    fresh = bool((getattr(menu, "fresh", {}) or {}).get("1d"))
    return "1d" if fresh and n >= DAILY_DECISION_MIN_BARS else DEFAULT_TF


def code_invalidation(*, side, manual, hold_h, menu=None, entry=None,
                      init_stop=None, tf=DEFAULT_TF) -> list:
    """The predicates code writes at birth, each `"by": "code"`:
    a bot idea's time predicate (`hold_h`: the persona's hold, else the
    care's no-progress clock; the care never cuts a hand ticket on a
    clock), the displaced break against it on the decision timeframe, and
    a close beyond the nearest 4h structure level between the entry and
    the initial stop when the menu holds one."""
    from bot_program.orcs.thesis import TIME_MIN_MFE_R
    out = []
    if not manual and hold_h:
        out.append({"kind": TIME, "market_h": float(hold_h),
                    "min_mfe_r": TIME_MIN_MFE_R, "by": "code"})
    out.append({"kind": BOS, "tf": tf, "by": "code"})
    level = _nearest_inside(menu, side, entry, init_stop)
    if level is not None:
        out.append({"kind": CLOSE, "tf": "4h", "level_id": level.id,
                    "level": level.price,
                    "side": "below" if str(side).upper() == "BUY"
                    else "above", "by": "code"})
    return out


def _nearest_inside(menu, side, entry, init_stop):
    entry, stop = _f(entry), _f(init_stop)
    if menu is None or entry is None or stop is None:
        return None
    lo, hi = sorted((entry, stop))
    inside = [lv for lv in getattr(menu, "levels", []) or []
              if lv.tf == "4h" and lv.kind in STRUCTURE_KINDS
              and lo < lv.price < hi]
    if not inside:
        return None
    return min(inside, key=lambda lv: abs(lv.price - entry))


# ── evaluation ───────────────────────────────────────────────────────────

def _closed_bars(frame, now):
    """[(ts, close)] of the frame's FINAL bars, oldest first: a bar that
    just ended counts once the refresh rewrote it (bars.final_bar)."""
    from bot_program.orcs.bars import final_end, span_of
    end = final_end(frame, now)
    if end is None:
        return []
    span = span_of(frame.tf)
    out = []
    for ts, close in zip(frame.df.index, frame.df["close"].values):
        t = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
        if t.tzinfo is None:
            t = t.replace(tzinfo=dt_tz.utc)
        if t + span <= end:
            out.append((t, float(close)))
    return out


def _stale(pred, frame, tf):
    if frame is None:
        return Result(key_of(pred), pred.get("kind"), PRED_UNCHECKED,
                      f"no {tf} venue bars")
    if not frame.venue or not frame.fresh:
        return Result(key_of(pred), pred.get("kind"), PRED_UNCHECKED,
                      f"no fresh {tf} bar", frame.newest_end)
    return None


def evaluate(pred, *, frames, side, asset_class, start, mfe_r, now,
             symbol="", mark=None) -> Result:
    """One predicate's state now. Pure but for the structure read."""
    kind = str((pred or {}).get("kind") or "")
    key = key_of(pred)
    if kind == TIME:
        from bot_program.position_care import market_hours
        hours = market_hours(start, now, asset_class)
        need = _f(pred.get("min_mfe_r")) or 0.0
        best = _f(mfe_r)
        limit = _f(pred.get("market_h")) or 0.0
        if limit and hours >= limit and best is None:
            # the care measured no excursion (switched off): unread is not
            # small, and a met predicate would stay met
            return Result(key, kind, PRED_UNCHECKED,
                          "the care has measured no best excursion")
        if limit and hours >= limit and best < need:
            return Result(key, kind, PRED_MET,
                          f"{hours:.0f} market hours with the best only "
                          f"{best:+.2f}R (needed {need:+.1f}R)")
        return Result(key, kind, PRED_UNMET)
    tf = str(pred.get("tf") or DEFAULT_TF)
    frame = (frames or {}).get(tf)
    stale = _stale(pred, frame, tf)
    if stale is not None:
        return stale
    if kind == CLOSE:
        level = _f(pred.get("level"))
        below = str(pred.get("side") or "below") == "below"
        if level is None:
            return Result(key, kind, PRED_UNCHECKED, "no level")
        for ts, close in _closed_bars(frame, now):
            if start is not None and ts < start:
                continue
            if (close < level) if below else (close > level):
                return Result(key, kind, PRED_MET,
                              f"a {tf} close {'below' if below else 'above'}",
                              ts)
        return Result(key, kind, PRED_UNMET)
    if kind == BOS:
        from bot_program.orcs.bars import _swings, final_df
        from brain.thesis_check import structure_read
        # the structure read sees the FINAL bars only: a break whose
        # trigger is the forming bar's provisional close is no break yet
        df = final_df(frame, now)
        if df is None or not len(df):
            return Result(key, kind, PRED_UNMET)
        px = _f(mark) or float(df["close"].values[-1])
        read = structure_read(symbol, side, px, timeframe=tf, now=now,
                              bars=(df, _swings(df)))
        brk = read.get("break_against") if read.get("ok") else None
        if isinstance(brk, dict) and brk.get("displaced"):
            idx = len(df) - 1 - int(brk.get("bars_ago") or 0)
            ts = df.index[max(0, idx)]
            ts = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=dt_tz.utc)
            if start is None or ts >= start:
                return Result(key, kind, PRED_MET,
                              f"a displaced break against the position on "
                              f"the {tf}", ts)
        return Result(key, kind, PRED_UNMET)
    return Result(key, kind, PRED_UNCHECKED, f"unknown predicate {kind}")


# ── the facts ────────────────────────────────────────────────────────────

def _hhmm(at) -> str:
    from bot_program.orcs.facts import _hhmm as hhmm
    return hhmm(at)


def met_line(pred, res, trade) -> str:
    from bot_program.orcs.facts import px
    kind = pred.get("kind")
    if kind == CLOSE:
        side = "below" if pred.get("side") == "below" else "above"
        return (f"Invalidation met: a {pred.get('tf')} close {side} "
                f"{px(trade, pred.get('level'))} ({pred.get('level_id')}) at "
                f"{_hhmm(res.bar_at)} UTC.")
    if kind == BOS:
        return (f"Invalidation met: a displaced break against the position "
                f"on the {pred.get('tf')} at {_hhmm(res.bar_at)} UTC.")
    return f"Invalidation met: {res.why}."


def unchecked_line(pred, res) -> str:
    if pred.get("kind") == TIME:
        return ("Invalidation unchecked: the care has measured no best "
                "excursion, so the time predicate cannot be read.")
    tf = pred.get("tf") or DEFAULT_TF
    at = res.bar_at
    if hasattr(at, "strftime"):
        return (f"Invalidation unchecked: no fresh {tf} bar since "
                f"{at.astimezone(dt_tz.utc):%H:%M} UTC "
                f"{at.astimezone(dt_tz.utc):%Y-%m-%d}.")
    return f"Invalidation unchecked: no fresh {tf} bar."


def _closed_end(pred, frames, now):
    """The newest FINAL bar a bar predicate reads, as text (its end and its
    close, so a bar rewritten after it was read is read again), or None (a
    time predicate, or a frame that is missing, stale or holds no final
    bar)."""
    if pred.get("kind") not in (BOS, CLOSE):
        return None
    frame = (frames or {}).get(str(pred.get("tf") or DEFAULT_TF))
    if frame is None or not frame.venue or not frame.fresh \
            or frame.newest_end is None:
        return None
    from bot_program.orcs.bars import final_bar
    got = final_bar(frame, now)
    if got is None:
        return None
    end, close = got
    return f"{end.isoformat()} close {close!r}"


def frames_for(orc, row, *, now, cache=None) -> dict:
    """The frames the thesis's predicates read, once per tick."""
    from bot_program.orcs import bars
    tfs = {str(p.get("tf") or DEFAULT_TF)
           for p in (orc.thesis or {}).get("invalidation") or []
           if p.get("kind") in (BOS, CLOSE)}
    return {tf: bars.frame(row.symbol, tf, asset_class=row.asset_class,
                           now=now, cache=cache) for tf in sorted(tfs)}


def check(orc, row, *, now, frames=None, mfe_r=None, mark=None,
          cache=None) -> list:
    """Evaluate every predicate of the thesis; write a fact on each
    transition (met, unchecked, checked again) and remember the states.
    Returns the Results. A met predicate stays met."""
    from bot_program.orcs import journal
    preds = [p for p in (orc.thesis or {}).get("invalidation") or []
             if isinstance(p, dict)]
    if not preds:
        return []
    if frames is None:
        frames = frames_for(orc, row, now=now, cache=cache)
    seen = dict((orc.seen or {}).get("predicates") or {})
    opened = getattr(row, "opened_at", None) or orc.born_at
    # FORWARD ONLY (§6.2): a bar predicate reads the bars that open at
    # or after the Orc's birth, never the history of an adopted row (a dump
    # two days before the Orc existed met its close_beyond at adoption).
    # The time predicate counts the position's own hold from its open, as
    # the care's clock and the best excursion it is read with both do.
    born = getattr(orc, "born_at", None)
    since_birth = max(t for t in (opened, born) if t is not None) \
        if (opened or born) else None
    out, changed = [], False
    for pred in preds:
        key = key_of(pred)
        was = seen.get(key) or {}
        if was.get("state") == PRED_MET:
            out.append(Result(key, pred.get("kind"), PRED_MET,
                              str(was.get("why") or "")))
            continue
        # a bar predicate is read again only when a new FINAL bar exists
        # (or the one read was rewritten): the structure read is not paid
        # for on every tick
        bar_end = _closed_end(pred, frames, now)
        if bar_end is not None and was.get("state") == PRED_UNMET \
                and was.get("bar_end") == bar_end:
            out.append(Result(key, pred.get("kind"), PRED_UNMET))
            continue
        try:
            res = evaluate(pred, frames=frames, side=row.side,
                           asset_class=row.asset_class,
                           start=opened if pred.get("kind") == TIME
                           else since_birth,
                           mfe_r=mfe_r, now=now, symbol=row.symbol,
                           mark=mark)
        except Exception as e:  # noqa: BLE001 — one predicate never stops it
            logger.info("[orcs] Orc %s: predicate %s unread: %s", orc.pk,
                        key, e)
            continue
        out.append(res)
        prior = was.get("state")
        if prior == res.state:
            if bar_end is not None and was.get("bar_end") != bar_end:
                seen[key] = {**was, "bar_end": bar_end}
                changed = True
            continue
        seen[key] = {"state": res.state, "why": res.why,
                     "at": now.isoformat(), "bar_end": bar_end}
        changed = True
        if res.state == PRED_MET:
            # O2: wake.request(orc, "W8", urgent=True)
            journal.append(orc, "fact", met_line(pred, res, row),
                           body={"predicate": pred, "result": res.as_dict()},
                           fact=True, remember={"predicates": dict(seen)})
            changed = False
        elif res.state == PRED_UNCHECKED:
            journal.append(orc, "fact", unchecked_line(pred, res),
                           body={"predicate": pred, "result": res.as_dict()},
                           fact=True, remember={"predicates": dict(seen)})
            changed = False
        elif prior == PRED_UNCHECKED:
            journal.append(orc, "fact",
                           "Invalidation checked again: the care measures "
                           "the best excursion again."
                           if pred.get("kind") == TIME else
                           f"Invalidation checked again: fresh "
                           f"{pred.get('tf') or DEFAULT_TF} bars.",
                           body={"predicate": pred}, fact=True,
                           remember={"predicates": dict(seen)})
            changed = False
    if changed:
        journal.remember(orc, predicates=dict(seen))
    return out
