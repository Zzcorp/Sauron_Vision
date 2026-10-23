"""THE WAR DRUMS' ROUTING (spec §4.7), pure.

A drum is a fact written by code; its payload carries PRICE LEVELS AND
ATR ONLY, never another idea's R, money or note ("a stop at 1.0832 was
hit on EURUSD at 14:05; price is 0.6 x ATR(1h) beyond it", never "Orc #140
lost 1R").

`reach(drum, open_ideas, matrix, factor_map)` -> [(orc_id, relation)], in
this order, each idea once, the first relation winning:
  1. the same symbol;
  2. a measured correlate: |rho| >= DRUM_RHO_MIN on the platform's matrix
     (capital_desk.correlation_matrix); an UNMEASURED pair reads 0.0 there
     and never routes;
  3. a shared currency leg (risk_gate._currency_legs) or the same
     commodity complex (risk_gate.COMMODITY_THEMES);
  4. a declared factor (DRUM_FACTOR_MAP, versioned in OrcSetting).
The origin idea is excluded, and a drum at hop >= DRUM_MAX_HOP is
recorded but never routed.
"""
from datetime import datetime

from bot_program.orcs.constants import DRUM_JOIN_MIN, DRUM_MAX_HOP, DRUM_RHO_MIN

KIND_WORDS = {"stop_hit": "stop_hit", "sweep": "sweep",
              "thesis_turned": "thesis_turned", "level_break": "level_break",
              "news_shock": "news_shock", "print_surprise": "print_surprise",
              "fill": "fill", "lock": "lock"}


def _legs(symbol, asset_class) -> set:
    from portfolio.risk_gate import COMMODITY_THEMES, _currency_legs
    sym = str(symbol or "").upper()
    if str(asset_class) == "currency":
        return {("leg", sym)}           # a print surprise: the currency
    if str(asset_class) == "commodity":
        c = COMMODITY_THEMES.get(sym)
        return {("complex", c)} if c else set()
    if str(asset_class) == "forex":
        return {("leg", ccy) for ccy in _currency_legs(sym, "BUY")}
    return set()


def _rho(matrix, a, b):
    """rho of a measured pair, else None (never the 0.0 of an unmeasured
    one)."""
    if a == b:
        return 1.0
    pair = (a, b) if a < b else (b, a)
    measured = (matrix or {}).get("measured") or set()
    if pair not in measured:
        return None
    try:
        return float(((matrix or {}).get("rho") or {}).get(pair))
    except (TypeError, ValueError):
        return None


def _factors(symbol, factor_map) -> set:
    fm = factor_map or {}
    fm = fm.get("map", fm) if isinstance(fm, dict) else {}
    return {f for f, syms in fm.items() if symbol in (syms or ())
            or symbol == f}


def reach(drum, open_ideas, matrix, factor_map) -> list:
    if int(drum.get("hop") or 0) >= DRUM_MAX_HOP:
        return []
    sym = str(drum.get("symbol") or "")
    cls = str(drum.get("asset_class") or "")
    origin = drum.get("orc_id")
    legs = _legs(sym, cls)
    factors = _factors(sym, factor_map)
    out, seen = [], set()
    for idea in open_ideas or ():
        oid = idea.get("orc_id")
        if oid is None or oid == origin or oid in seen:
            continue
        other = str(idea.get("symbol") or "")
        relation = None
        if other == sym:
            relation = "same symbol"
        else:
            rho = _rho(matrix, sym, other)
            if rho is not None and abs(rho) >= DRUM_RHO_MIN:
                relation = f"correlate, rho {rho:+.2f}"
        if relation is None:
            shared = sorted(legs & _legs(other, idea.get("asset_class")))
            if shared:
                kind, name = shared[0]
                relation = (f"the {name} leg" if kind == "leg"
                            else f"the {name} complex")
        if relation is None:
            common = sorted(factors & _factors(other, factor_map))
            if common:
                relation = f"the {common[0]} factor"
        if relation is not None:
            seen.add(oid)
            out.append((oid, relation))
    return out


def wave_of(kind, symbol, at, open_drums) -> str:
    """The wave a drum joins: a drum of the same kind and symbol within
    DRUM_JOIN_MIN of an open one, else a new wave."""
    for d in open_drums or ():
        dat = d.get("at")
        if d.get("kind") == kind and d.get("symbol") == symbol and \
                isinstance(dat, datetime) and \
                abs((at - dat).total_seconds()) <= DRUM_JOIN_MIN * 60:
            return str(d.get("wave_id"))
    return f"{kind}:{symbol}:{at:%Y%m%d%H%M%S}"


# ── the payloads: prices and ATR only ────────────────────────────────────

def payload_stop_hit(*, stop, at, beyond_atr) -> dict:
    return {"stop": stop, "at": at.isoformat() if hasattr(at, "isoformat")
            else str(at), "beyond_atr": beyond_atr}


def payload_lock(*, what, price) -> dict:
    return {"what": str(what), "price": price}


def payload_level_break(*, symbols, bar_end) -> dict:
    return {"symbols": list(symbols), "bar_end": bar_end.isoformat()
            if hasattr(bar_end, "isoformat") else str(bar_end)}


def payload_news_shock(*, move_atr, minutes, article, corroborated) -> dict:
    return {"move_atr": move_atr, "minutes": minutes, "article": article,
            "corroborated": bool(corroborated)}


def payload_print(*, title, ccy, x) -> dict:
    return {"title": str(title), "ccy": str(ccy), "x_median": x}


def payload_sweep(*, tf, side, price, reclaimed) -> dict:
    return {"tf": str(tf), "side": str(side), "price": price,
            "reclaimed": bool(reclaimed)}


def payload_thesis(*, why) -> dict:
    return {"why": str(why)}


# ── the journal line ─────────────────────────────────────────────────────

def _hhmm(at) -> str:
    try:
        if isinstance(at, str):
            at = datetime.fromisoformat(at)
        return f"{at:%H:%M}"
    except (TypeError, ValueError):
        return "--:--"


def _x(v) -> str:
    try:
        return f"{float(v):.1f}"
    except (TypeError, ValueError):
        return "—"


def line(drum, relation, dr_id) -> str:
    """The receiver's journal line (§5.2a, the DR-n fact)."""
    kind = drum.get("kind")
    sym = drum.get("symbol")
    p = drum.get("payload") or {}
    hop = int(drum.get("hop") or 0)
    if kind == "stop_hit":
        beyond = (f"the price is {_x(p.get('beyond_atr'))} x ATR(1h) beyond "
                  f"it" if p.get("beyond_atr") is not None else
                  "its distance in ATR(1h) is not measured")
        return (f"{dr_id}: a stop at {p.get('stop')} was hit on {sym} at "
                f"{_hhmm(p.get('at'))} UTC; {beyond} ({relation}, hop "
                f"{hop}).")
    if kind == "lock":
        return f"{dr_id}: {sym}: {p.get('what')} at {p.get('price')} " \
               f"({relation})."
    if kind == "level_break":
        return (f"{dr_id}: a 4h close beyond a structure level on "
                f"{', '.join(p.get('symbols') or [sym])} ({relation}).")
    if kind == "news_shock":
        return (f"{dr_id}: {sym} moved {_x(p.get('move_atr'))} x ATR(1h) in "
                f"{p.get('minutes')} min after an urgent headline "
                f"(N{p.get('article')}, untrusted) ({relation}).")
    if kind == "print_surprise":
        return (f"{dr_id}: {p.get('title')} printed {_x(p.get('x_median'))} "
                f"x its median surprise ({p.get('ccy')}) ({relation}).")
    if kind == "sweep":
        back = ", then reclaimed" if p.get("reclaimed") else ""
        return (f"{dr_id}: {sym}: the {p.get('tf')} {p.get('side')} at "
                f"{p.get('price')} was swept{back} ({relation}).")
    if kind == "thesis_turned":
        return f"{dr_id}: {sym}: a thesis turned ({p.get('why')}) " \
               f"({relation})."
    return f"{dr_id}: {sym}: a {kind} drum ({relation})."

