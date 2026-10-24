"""THE MENU (spec §5.2, §2.2 I11): the levels an Orc may name, each with an
id, built by code from the venue's own bars. Pure apart from the bar read
(bot_program/orcs/bars.py).

  levels    the crowd's levels on both sides of the mark, as the care and
            the chart read them (smart_money.living_levels, on the frame
            this module hands it), per timeframe: 1h and 4h, and 1d (the
            venue's 4h bars by UTC day, orcs/bars.py) only while its venue
            bars are fresh; the swept highs and lows
            (smart_money.sweep_read)
  stops     each level carries the stop that would protect a position on
            its side: just beyond the level, pushed past every crowd level
            in the hunt zone (smart_money.stop_beyond_the_crowd), at the
            instrument's printed precision (core.price_format)
  ids       deterministic, ranked by distance from the frame's last close
            (1 = the nearest): S4h-L1 a swing low, S4h-H2 a swing high,
            P1h-L1 a pool of equal lows, SW4h-H1 a swept high, RC1h-L the
            recent low, RN-1 a round number
  basis     when the venue holds no fresh frame (D2), the platform's levels
            are shifted by the mark less its last 1h close and labelled
            "basis-shifted"; their STRUCTURE levels are dropped, the reason
            said, unless the last BASIS_SAMPLES hourly basis samples stand
            within BASIS_UNSTABLE_ATR1H x ATR(1h). Fewer samples than that
            is unstable: it fails closed.

`for_idea` adds the idea's own rows (pure): BE (the entry plus its round
trip), CARE (the care's soft stop) and EFF (the tighter of the care's soft
stop and the venue's stop), with every row's distance in R and in ATR.
Nothing here is ranked: the playbook lists candidates by id.
"""
import logging
import statistics
from dataclasses import asdict, dataclass, field
from typing import Optional

from bot_program.orcs.constants import (BASIS_SAMPLES, BASIS_UNSTABLE_ATR1H,
                                        MENU_DAILY_TF, MENU_TFS)

logger = logging.getLogger(__name__)

#: The kinds that read the structure (dropped on an unstable basis).
STRUCTURE_KINDS = ("swing", "pool", "sweep", "recent")
BASIS_SHIFTED = "basis-shifted"


@dataclass(frozen=True)
class Level:
    id: str
    kind: str                # swing | pool | sweep | recent | round
    tf: str
    side: str                # below | above the mark
    price: float
    stop: Optional[float]
    pool: bool = False
    touches: Optional[int] = None
    origin: Optional[int] = None
    source: str = ""
    words: str = ""


@dataclass
class Menu:
    symbol: str
    as_of: object
    source: str = ""
    atr: dict = field(default_factory=dict)
    fresh: dict = field(default_factory=dict)
    levels: list = field(default_factory=list)
    why: list = field(default_factory=list)
    tfs: list = field(default_factory=list)
    #: bars in each frame read (the decision timeframe asks 60 fresh 1d)
    n: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        at = self.as_of
        return {"symbol": self.symbol,
                "as_of": at.isoformat() if hasattr(at, "isoformat") else at,
                "source": self.source, "atr": dict(self.atr),
                "fresh": dict(self.fresh), "tfs": list(self.tfs),
                "n": dict(self.n),
                "why": list(self.why),
                "levels": [asdict(lv) for lv in self.levels]}


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def _snap(value, asset_class, symbol):
    from core.price_format import price_decimals
    return round(float(value), price_decimals(value, asset_class, symbol))


def _kind_of(row) -> str:
    kind = str(row.get("kind") or "")
    if kind.startswith("swing"):
        return "swing"
    if row.get("pool") or kind.startswith("equal"):
        return "pool"
    if kind.startswith("recent"):
        return "recent"
    if kind.startswith("round"):
        return "round"
    return kind or "level"


def _stop_for(price, side, mark, atr, crowd, asset_class, symbol):
    """The stop that protects a position whose stop side holds `price`: the
    level less the hunt depth, then beyond every crowd level in the zone."""
    from bot_program import smart_money as sm
    if not atr or atr <= 0:
        return None
    buy = side == "below"
    candidate = price - sm.HUNT_DEPTH_ATR * atr if buy \
        else price + sm.HUNT_DEPTH_ATR * atr
    try:
        moved = sm.stop_beyond_the_crowd("BUY" if buy else "SELL", mark,
                                         candidate, atr, crowd)
        stop = moved["stop"] if not moved.get("crowded") else candidate
    except Exception:  # noqa: BLE001 — the plain stop stands
        stop = candidate
    return _snap(stop, asset_class, symbol)


def basis_stable(samples, atr_1h) -> tuple:
    """(stable, why) for the last BASIS_SAMPLES basis samples."""
    xs = [x for x in (_f(s) for s in (samples or [])) if x is not None]
    xs = xs[-BASIS_SAMPLES:]
    if len(xs) < BASIS_SAMPLES:
        return False, (f"the basis is unmeasured ({len(xs)} of "
                       f"{BASIS_SAMPLES} hourly samples)")
    if not atr_1h or atr_1h <= 0:
        return False, "the basis cannot be judged: no ATR(1h)"
    sd = statistics.pstdev(xs)
    if sd > BASIS_UNSTABLE_ATR1H * atr_1h:
        return False, (f"the basis is unstable ({sd / atr_1h:.2f} x ATR(1h) "
                       f"over {BASIS_SAMPLES} hours)")
    return True, ""


def _ranked(rows, close):
    return sorted(rows, key=lambda r: (abs(r["price"] - close), r["price"]))


def _frame_levels(f, *, symbol, asset_class, mark, shift, structure=True):
    """([Level], living rows) from one frame (living levels and sweeps),
    shifted by `shift` (the basis) and ranked per group by distance. The
    rows feed the round numbers; `structure` False keeps none of the
    frame's own levels."""
    from bot_program import smart_money as sm
    close = f.last_close
    atr = f.atr
    if not close or not atr:
        return [], []
    px = (mark - shift) if mark else close
    living = sm.living_levels(symbol, px, timeframe=f.tf,
                              bars=(f.df, f.swings)) or {}
    rows = list(living.get("levels") or [])
    try:
        sw = sm.sweep_read(f.df, f.swings, "BUY", atr, entry=px)
        for key, side in (("against", "above"), ("with", "below")):
            hit = sw.get(key)
            if isinstance(hit, dict) and _f(hit.get("level")):
                rows.append({"price": float(hit["level"]), "kind": "sweep",
                             "side": side, "pool": False})
    except Exception as e:  # noqa: BLE001 — no sweep read is no sweep
        logger.debug("[orcs] %s %s: sweeps unread: %s", symbol, f.tf, e)
    crowd = {"below": [(r["price"], r["kind"]) for r in rows
                       if r.get("side") == "below"],
             "above": [(r["price"], r["kind"]) for r in rows
                       if r.get("side") == "above"]}
    groups = {}
    for r in rows:
        kind = _kind_of(r)
        if kind == "round":
            continue                     # the round numbers: one list
        groups.setdefault((kind, r.get("side")), []).append(r)
    prefix = {"swing": "S", "pool": "P", "sweep": "SW", "recent": "RC"}
    out = []
    if not structure:
        return out, rows
    for (kind, side), members in sorted(groups.items()):
        letter = "L" if side == "below" else "H"
        for k, r in enumerate(_ranked(members, close), start=1):
            price = float(r["price"])
            lid = (f"RC{f.tf}-{letter}" if kind == "recent"
                   else f"{prefix.get(kind, 'X')}{f.tf}-{letter}{k}")
            if kind == "recent" and k > 1:
                continue
            stop = _stop_for(price, side, px, atr, crowd.get(side) or [],
                             asset_class, symbol)
            out.append(Level(
                id=lid, kind=kind, tf=f.tf, side=side,
                price=_snap(price + shift, asset_class, symbol),
                stop=(_snap(stop + shift, asset_class, symbol)
                      if stop is not None else None),
                pool=bool(r.get("pool")), touches=r.get("touches"),
                origin=r.get("origin"), source=f.label,
                words=str(r.get("kind") or kind)))
    return out, rows


def _round_levels(rows_by_tf, mark, asset_class, symbol, atr):
    """RN-k: the round numbers the frames named, once, ranked by distance
    from the mark, with their stops."""
    seen = {}
    for f, rows in rows_by_tf:
        for r in rows:
            if _kind_of(r) == "round":
                seen.setdefault(round(float(r["price"]), 10), r)
    out = []
    for k, (price, r) in enumerate(sorted(
            seen.items(), key=lambda kv: (abs(kv[0] - mark), kv[0])),
            start=1):
        side = "below" if price < mark else "above"
        out.append(Level(id=f"RN-{k}", kind="round", tf="", side=side,
                         price=_snap(price, asset_class, symbol),
                         stop=_stop_for(price, side, mark, atr, [],
                                        asset_class, symbol),
                         source="", words="round number"))
    return out


def symbol_levels(symbol, asset_class, *, now=None, mark=None, cache=None,
                  basis_samples=None, exchange="", until=None) -> Menu:
    """The symbol's menu at `now` (`mark`: the closing-side mark, else the
    frame's last close). `until` builds it as it stood at a past moment:
    every frame cut there, only its bars complete then (the playbook arm's
    tail, no look-ahead). Never raises: a frame that cannot be read is a
    reason in `why`."""
    from django.utils import timezone

    from bot_program.orcs import bars
    now = now or timezone.now()
    menu = Menu(symbol=str(symbol), as_of=now)
    frames = []
    for tf in MENU_TFS + (MENU_DAILY_TF,):
        f = bars.frame(symbol, tf, asset_class=asset_class, now=now,
                       cache=cache, exchange=exchange, until=until)
        if f is None:
            if tf != MENU_DAILY_TF:
                menu.why.append(f"no {tf} bars")
            continue
        menu.atr[tf] = f.atr
        menu.fresh[tf] = bool(f.fresh)
        menu.n[tf] = int(f.n) if f.venue else 0
        if not f.fresh:
            menu.why.append(f"no fresh {tf} bars since "
                            f"{f.newest_end:%Y-%m-%d %H:%M} UTC")
            continue
        if tf == MENU_DAILY_TF and not f.venue:
            menu.why.append("1d: no venue bars")
            continue
        frames.append(f)
    if not frames:
        menu.source = ""
        return menu
    venue = all(f.venue for f in frames)
    menu.source = "etoro" if venue else BASIS_SHIFTED
    shift = 0.0
    keep_structure = True
    if not venue:
        f1h = next((f for f in frames if f.tf == "1h"), frames[0])
        if mark:
            shift = float(mark) - float(f1h.last_close or mark)
        stable, why = basis_stable(basis_samples, menu.atr.get("1h"))
        if not stable:
            keep_structure = False
            menu.why.append(f"structure levels dropped: {why}")
    mark_px = float(mark) if mark else float(frames[0].last_close)
    rows_by_tf = []
    for f in frames:
        try:
            lv, rows = _frame_levels(
                f, symbol=symbol, asset_class=asset_class, mark=mark,
                shift=0.0 if f.venue else shift,
                structure=f.venue or keep_structure)
            rows_by_tf.append((f, rows))
            menu.levels.extend(lv)
            menu.tfs.append(f.tf)
        except Exception as e:  # noqa: BLE001 — one frame never stops it
            menu.why.append(f"{f.tf}: levels unread ({type(e).__name__})")
    menu.levels.extend(_round_levels(rows_by_tf, mark_px, asset_class,
                                     symbol, menu.atr.get("4h")
                                     or menu.atr.get("1h")))
    return menu


def level_by_id(rows, level_id):
    """The menu level (or for_idea row) named `level_id`, or None."""
    items = rows.levels if isinstance(rows, Menu) else rows
    for lv in items or ():
        lid = lv.id if isinstance(lv, Level) else (lv or {}).get("id")
        if lid == level_id:
            return lv
    return None


def for_idea(menu, *, side, entry, risk_per_unit, mark, care_state=None,
             cf=0.0) -> list:
    """The menu as the idea reads it (pure): every level with its distance
    in R and in ATR of its timeframe, plus BE, CARE and EFF."""
    from bot_program.orcs.pricing import d
    sign = d(side)
    rpu = _f(risk_per_unit)
    mark = _f(mark)
    atr = dict(getattr(menu, "atr", {}) or {})
    out = []

    def row(lid, kind, tf, price, *, stop=None, extra=None):
        price = _f(price)
        if price is None:
            return
        r_away = (round(sign * (price - mark) / rpu, 3)
                  if rpu and mark is not None else None)
        a = atr.get(tf) or atr.get("4h")
        atr_away = (round(sign * (price - mark) / a, 3)
                    if a and mark is not None else None)
        out.append({"id": lid, "kind": kind, "tf": tf, "price": price,
                    "stop": stop, "r_away": r_away, "atr_away": atr_away,
                    **(extra or {})})

    for lv in getattr(menu, "levels", None) or []:
        row(lv.id, lv.kind, lv.tf, lv.price, stop=lv.stop,
            extra={"side": lv.side, "pool": lv.pool, "origin": lv.origin,
                   "source": lv.source})
    e = _f(entry)
    if e:
        row("BE", "breakeven_plus_cost", "4h", e + sign * e * float(cf or 0))
    care = care_state if isinstance(care_state, dict) else {}
    soft = _f(care.get("soft_stop"))
    if soft is not None:
        row("CARE", "care_soft_stop", "4h", soft,
            extra={"why": str(care.get("soft_why") or "")})
    venue = _f(care.get("venue_stop"))
    eff = soft
    if venue is not None and (eff is None or sign * (venue - eff) > 0):
        eff = venue
    if eff is not None:
        row("EFF", "effective_stop", "4h", eff)
    return out
