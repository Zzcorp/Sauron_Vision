"""IN, THE INSTRUMENT (spec §5.2a "IN: the instrument"), shared by the Orcs
on one symbol.

  IN-slow   per (symbol, newest final 1h bar, model), built on a miss and
            pre-built hourly (orc-hourly), cut at its moment (no bar after
            it): IN1 the frames (1h for 5 days, 4h for 10 days, 1d for 60
            sessions) as integer rows in 0.1 x ATR(1h) around an anchor,
            one source per frame; IN2 the structure per frame; IN3 the
            menu's levels with their ids and the classic floor pivots;
            IN5 the positioning; IN6 the COT; IN10 the gap model. Its 1h
            rows beyond 3 days are cut AT BUILD when the model's dossier
            would not fit (the last step of TRIM_ORDER), so every Orc on the
            symbol shares the same bytes.
  IN-today  per wake, in the tail: IN4 PO3 today, IN7 the mark (source and
            age) and the spread in ATR(1h), IN8 the correlated instruments'
            moves with their measured rho, IN9 the instrument's headlines
            (24 h, 8 at most, fenced), IN11 the next print, IN12 today's
            tape (15m since the Asia open, 5m for the last 2 h; a frame
            whose last bar is older than one bar is under `last_known`,
            never `now`).

`signals/smc/pivots.py` reads fractal swings, not floor pivots: the floor
pivots here are a new pure function of yesterday's high, low and close.
"""
import logging
from datetime import timedelta

from bot_program.orcs import dossier, fence, sources
from bot_program.orcs.constants import (DOSSIER_MAX_TOKENS, IN_HEADLINES,
                                        S_TOKENS_RESERVE)

logger = logging.getLogger(__name__)

#: IN1's frames: (timeframe, bars, row label).
IN1_FRAMES = (("1h", 120, "%m%d %H%M"), ("4h", 60, "%m%d %H%M"),
              ("1d", 60, "%m%d"))
#: 1h rows kept when IN-slow is cut for size (3 days).
IN1_1H_KEEP = 72
#: What PS and the tail take in the cap (§5.2a: PS about 2,900, the tail
#: about 3,700 tokens).
PS_TAIL_RESERVE = 6600
#: IN12: the 5m rows' window.
TAPE_5M_H = 2


def floor_pivots(h, l, c) -> dict:
    """The classic floor pivots of one session's high, low and close."""
    h, l, c = float(h), float(l), float(c)
    p = (h + l + c) / 3.0
    return {"P": p, "R1": 2 * p - l, "S1": 2 * p - h,
            "R2": p + (h - l), "S2": p - (h - l)}


def _px(value, asset_class, symbol) -> str:
    from core.price_format import format_price
    try:
        return format_price(value, asset_class, symbol)
    except Exception:  # noqa: BLE001
        return f"{float(value):g}"


def _utc(at) -> str:
    try:
        return f"{at:%Y-%m-%d %H:%M} UTC"
    except (TypeError, ValueError):
        return "an unread time"


def _rows(df, n, fmt, anchor, unit) -> list:
    out = []
    tail = df.iloc[-int(n):]
    for ts, r in zip(tail.index, tail.itertuples(index=False)):
        label = ts.strftime(fmt) if hasattr(ts, "strftime") else str(ts)

        def q(x):
            return int(round((float(x) - anchor) / unit))
        out.append(f"{label} {q(r.open):+d} {q(r.high):+d} {q(r.low):+d} "
                   f"{q(r.close):+d}")
    return out


def _frame_block(f, tf, n, fmt, anchor, unit, asset_class, symbol):
    if f is None:
        return f"— (no {tf} bars)", 0
    if not f.fresh:
        return (f"— (no fresh {tf} venue bars since "
                f"{_utc(f.newest_end)})"), 0
    rows = _rows(f.df, n, fmt, anchor, unit)
    return {"source": f.label, "last_bar": _utc(f.newest_end),
            "rows": rows}, len(rows)


def _structure(symbol, f, now) -> object:
    if f is None or not len(f.df):
        return "— (too few bars)"
    try:
        from brain.thesis_check import structure_read
        read = structure_read(symbol, "BUY", float(f.last_close),
                              timeframe=f.tf, now=now, bars=(f.df, f.swings))
        if not read.get("ok"):
            return f"— ({fence.sanitize(read.get('why') or 'unread', 60)})"
        brk = read.get("break_against")
        conf = read.get("confidence")
        return {"bias": str(read.get("bias") or "—"),
                "conf": f"{float(conf):.2f}" if conf is not None else "—",
                "zone": str(read.get("zone") or "—"),
                "last_break_down": (
                    f"{int(brk.get('bars_ago') or 0)} bars ago"
                    + (", displaced" if brk.get("displaced") else "")
                    if isinstance(brk, dict) else "—"),
                "swept": "yes" if read.get("sweep_against") or
                read.get("sweep_with") else "no"}
    except Exception as e:  # noqa: BLE001
        return f"— (structure unread: {type(e).__name__})"


def _levels(symbol, asset_class, now, cache, frames) -> dict:
    from bot_program.orcs import menu
    out = {}
    try:
        mn = menu.symbol_levels(symbol, asset_class, now=now, cache=cache,
                                until=now)
        out["levels"] = [{"id": lv.id, "kind": lv.kind, "tf": lv.tf,
                          "side": lv.side,
                          "price": _px(lv.price, asset_class, symbol)}
                         for lv in mn.levels[:30]] or "— (no level: " + \
            ("; ".join(mn.why) or "no fresh frame") + ")"
    except Exception as e:  # noqa: BLE001
        out["levels"] = f"— (levels unread: {type(e).__name__})"
    f1d = frames.get("1d")
    try:
        if f1d is not None and len(f1d.df) >= 2:
            day = f1d.df.iloc[-2]
            piv = floor_pivots(day["high"], day["low"], day["close"])
            out["pivots"] = {k: _px(v, asset_class, symbol)
                             for k, v in piv.items()}
        else:
            out["pivots"] = "— (no completed daily bar)"
    except Exception:  # noqa: BLE001
        out["pivots"] = "— (no completed daily bar)"
    return out


def _positioning(symbol, asset_class, now) -> object:
    try:
        from bot_program.positioning import positioning_map
        pm = positioning_map(symbol, asset_class=asset_class, now=now)
        if not pm.get("ok"):
            return f"unread: {fence.sanitize(pm.get('why') or '', 60)}"
        crowd = pm.get("crowd") or {}
        return {"score": (f"{float(crowd.get('score')):+.2f}"
                          if crowd.get("score") is not None else "—"),
                "label": str(crowd.get("label") or "—"),
                "bias": str(pm.get("bias") or "—"),
                "words": fence.sanitize(pm.get("words"), 240)}
    except Exception as e:  # noqa: BLE001
        return f"unread: {type(e).__name__}"


def _cot(symbol, now) -> object:
    try:
        from bot_program.smart_money import cot_read
        c = cot_read(symbol, "BUY", now=now)
        if c.get("spec_index") is None:
            return f"— ({fence.sanitize(c.get('why') or 'no report', 80)})"
        return {"speculators": f"{float(c['spec_index']):.0f}",
                "commercials": (f"{float(c['comm_index']):.0f}"
                                if c.get("comm_index") is not None else "—"),
                "weeks": int(c.get("weeks") or 0)}
    except Exception as e:  # noqa: BLE001
        return f"— (COT unread: {type(e).__name__})"


def _gaps(symbol, asset_class, now, atr1h) -> dict:
    from bot_program.orcs import gaps
    out = {}
    try:
        g = gaps.next_shut_gap(symbol, asset_class, now=now)
        if gaps.measured(g):
            out["next_shut"] = {"kind": g.kind, "n": g.n,
                                "p90": _px(g.p90, asset_class, symbol),
                                "p90_atr1h": (f"{float(g.p90) / atr1h:.1f}"
                                              if atr1h else "—")}
        else:
            out["next_shut"] = (f"unmeasured (< 8 samples: "
                                f"{g.n if g else 0})")
    except Exception as e:  # noqa: BLE001
        out["next_shut"] = f"— (gap unread: {type(e).__name__})"
    return out


def _in_slow_body(symbol, asset_class, *, now, cache) -> tuple:
    """(body, bar rows): IN-slow's content, the same for every model (read
    once per pass when `cache` is shared, as the hourly beat shares it)."""
    import copy
    memo = ("orcs:in_body", symbol, now.isoformat())
    if isinstance(cache, dict) and memo in cache:
        body, rows = cache[memo]
        return copy.deepcopy(body), rows
    body, rows = _read_in_slow(symbol, asset_class, now=now, cache=cache)
    if isinstance(cache, dict):
        cache[memo] = (copy.deepcopy(body), rows)
    return body, rows


def build_in_slow(symbol, asset_class, model, *, now, cache, key):
    model = dossier.family_of(model)
    body, rows = _in_slow_body(symbol, asset_class, now=now, cache=cache)
    in1 = body.get("in1")
    header = (f"IN-slow {symbol} | to {_utc(now)} | {model} | sources: "
              f"the venue's bars (one source per frame), the menu, the "
              f"positioning map, the COT, the gap model")
    text = dossier.text_for(header, body)
    trimmed = []
    mk_tokens = _mk_tokens(now, model)
    budget = DOSSIER_MAX_TOKENS - S_TOKENS_RESERVE - mk_tokens - \
        PS_TAIL_RESERVE
    if isinstance(in1, dict) and isinstance(in1.get("1h"), dict) and \
            dossier.estimate_tokens(text, rows, model) > budget:
        cut = in1["1h"]["rows"][:-IN1_1H_KEEP]
        in1["1h"]["rows"] = in1["1h"]["rows"][-IN1_1H_KEEP:]
        rows -= len(cut)
        trimmed.append("in1_1h_old")
        body["trimmed"] = trimmed
        text = dossier.text_for(header, body)
    return dossier.block("in_slow", key, text,
                         {"symbol": symbol, "trimmed": trimmed}, model,
                         bar_rows=rows, at=now)


def _read_in_slow(symbol, asset_class, *, now, cache) -> tuple:
    from bot_program.orcs import bars
    frames = {tf: bars.frame(symbol, tf, asset_class=asset_class, now=now,
                             cache=cache, n=n, until=now)
              for tf, n, _fmt in IN1_FRAMES}
    f1h = frames.get("1h")
    atr = f1h.atr if f1h is not None else None
    anchor = f1h.last_close if f1h is not None else None
    in1, rows = {}, 0
    if not atr or anchor is None:
        in1 = "— (no ATR)"
    else:
        unit = 0.1 * atr
        in1 = {"anchor": _px(anchor, asset_class, symbol),
               "unit": f"0.1 x ATR(1h) = {_px(unit, asset_class, symbol)}"}
        for tf, n, fmt in IN1_FRAMES:
            in1[tf], k = _frame_block(frames.get(tf), tf, n, fmt, anchor,
                                      unit, asset_class, symbol)
            rows += k
    body = {"symbol": symbol, "in1": in1,
            "in2": {tf: _structure(symbol, frames.get(tf), now)
                    for tf in ("1h", "4h", "1d")},
            "in3": _levels(symbol, asset_class, now, cache, frames),
            "in5": _positioning(symbol, asset_class, now),
            "in6": _cot(symbol, now),
            "in10": _gaps(symbol, asset_class, now, atr)}
    return body, rows


def _mk_tokens(now, model) -> int:
    from bot_program.orcs.models import OrcDossierBlock
    from bot_program.orcs.sessions import trading_day
    td = trading_day(now).isoformat()
    model = dossier.family_of(model)
    return sum(OrcDossierBlock.objects.filter(
        kind__in=("mk0", "mk_session", "mk_e"),
        key__startswith=f"{td}|").filter(model__in=(model, ""))
        .values_list("tokens_est", flat=True))


def in_slow(symbol, asset_class, model, *, now, cache=None):
    """IN-slow's hash for the newest FINAL 1h bar at `now`: found, else
    built."""
    from bot_program.orcs import bars
    f = bars.frame(symbol, "1h", asset_class=asset_class, now=now,
                   cache=cache)
    end = bars.final_end(f, now) if f is not None else None
    key = (f"{symbol}|{end.isoformat() if end else 'none'}|"
           f"{dossier.family_of(model)}")
    b = dossier.find("in_slow", key)
    if b is not None:
        return b.hash
    return build_in_slow(symbol, asset_class, model, now=now, cache=cache,
                         key=key)


# ── IN-today ─────────────────────────────────────────────────────────────

def _tape_slot(symbol, tf, start, now, unit_atr):
    from market_data.models import PriceData
    from bot_program.orcs.bars import span_of
    span = span_of(tf)
    rows = list(PriceData.objects
                .filter(instrument__symbol=symbol, timeframe=tf,
                        source="etoro", timestamp__gte=start,
                        timestamp__lte=now - span)
                .order_by("timestamp")
                .values_list("timestamp", "open", "high", "low", "close"))
    if not rows:
        return f"— (no {tf} venue bars)", []
    last_end = rows[-1][0] + span
    age = (now - last_end).total_seconds() / 60.0
    anchor = float(rows[-1][4])
    unit = 0.1 * unit_atr if unit_atr else anchor * 0.001
    unit_t = ("0.1 x ATR(1h)" if unit_atr else "0.1% of the anchor")
    out = []
    for ts, o, h, lo, c in rows:
        def q(x):
            return int(round((float(x) - anchor) / unit))
        out.append(f"{ts:%H%M} {q(o):+d} {q(h):+d} {q(lo):+d} {q(c):+d}")
    frame = {"anchor": f"{anchor:g}", "unit": unit_t,
             "last_bar": f"{last_end:%H:%M} UTC", "age_min": round(age),
             "rows": out}
    state = "now" if (now - last_end) <= span else "last_known"
    return {state: frame}, out


def in12(symbol, asset_class, now, *, atr1h=None) -> dict:
    """IN12: 15m since the trading day's Asia open, 5m for the last 2 h,
    from the venue's candles only; a frame older than one bar is
    `last_known`."""
    from bot_program.orcs.sessions import session_windows, trading_day
    asia = session_windows(trading_day(now))[0][1]
    s15, rows15 = _tape_slot(symbol, "15m", asia, now, atr1h)
    s5, rows5 = _tape_slot(symbol, "5m", now - timedelta(hours=TAPE_5M_H),
                           now, atr1h)
    return {"15m": s15, "5m": s5, "_rows15": rows15, "_rows5": rows5}


def _print_gap(symbol, asset_class, event, now, atr1h) -> object:
    """IN10's per-print gap for the next print: the p90 of the 1h range at
    its title's past prints, in ATR(1h); unmeasured under 8 samples."""
    try:
        from bot_program.orcs import gaps
        g = gaps.print_gap(symbol, asset_class, event["title"],
                           event.get("ccy") or None, now=now)
        if not gaps.measured(g):
            return f"unmeasured (< 8 samples: {g.n})"
        return {"n": g.n, "p90_atr1h": (f"{float(g.p90) / atr1h:.1f}"
                                        if atr1h else "—")}
    except Exception as e:  # noqa: BLE001
        return f"— (gap unread: {type(e).__name__})"


def tape_rows(today) -> int:
    tape = (today or {}).get("in12") if isinstance(today, dict) else None
    n = 0
    for slot in (tape or {}).values() if isinstance(tape, dict) else ():
        if isinstance(slot, dict):
            for inner in slot.values():
                if isinstance(inner, dict):
                    n += len(inner.get("rows") or [])
    return n


def in_today(row, now, ctx) -> dict:
    """IN-today's sections; the lists the per-wake trim may empty are
    returned beside them (in12_5m, in12_15m_old, in9)."""
    symbol, cls = row.symbol, row.asset_class
    atr1h = (ctx or {}).get("atr1h")
    out = {}
    try:
        from bot_program.power_of_three import power_of_three
        day = power_of_three(symbol, now=now)
        out["in4"] = ({"phase": str(day.get("phase")),
                       "direction": str(day.get("direction") or "—"),
                       "session": str(day.get("session") or "—"),
                       "timeframe": str(day.get("timeframe") or "1h")}
                      if day.get("ok") else
                      f"unread: {fence.sanitize(day.get('why') or '', 80)}")
    except Exception as e:  # noqa: BLE001
        out["in4"] = f"unread: {type(e).__name__}"
    if isinstance(ctx, dict):
        ctx["po3"] = out["in4"]          # the facts hash reads the phase
    q = sources.quote(symbol)
    spread = None
    if not q.get("dash"):
        b, a = q["value"].get("bid"), q["value"].get("ask")
        if b is not None and a is not None and a >= b:
            spread = a - b
    age = (ctx or {}).get("mark_age_s")
    out["in7"] = {"source": str((ctx or {}).get("mark_source") or "none"),
                  "age_s": int(age) if age is not None else "—",
                  "counts_as_venue": bool(
                      (ctx or {}).get("mark_source") == "venue" and age is
                      not None and age <= 120),
                  "spread_atr1h": (f"{spread / atr1h:.2f}"
                                   if spread is not None and atr1h else "—")}
    held = [s for s in (ctx or {}).get("held") or [] if s != symbol]
    corr = sources.correlation(getattr(row.config, "user", None),
                               [symbol] + held) if held else None
    moves = {}
    live = sources.quotes(held[:8])
    for s in held[:8]:
        rho = "—"
        if corr is not None and not corr.get("dash"):
            a, b = sorted((symbol, s))
            rho = corr["value"]["pairs"].get(f"{a}/{b}", "—")
        qq = live[s]
        ch = None if qq.get("dash") else qq["value"].get("change_pct")
        moves[s] = {"rho": rho, "today": f"{ch:+.2f}%" if ch is not None
                    else "—"}
    out["in8"] = moves or "— (no other position held)"
    blind = ((ctx or {}).get("blind") or (False, ""))[0]
    news = sources.headlines(now - timedelta(hours=24), now,
                             symbols=[symbol], n=IN_HEADLINES, blind=blind)
    out["in9"] = news["value"] if not news.get("dash") else news["dash"]
    cal = (ctx or {}).get("calendar") or {}
    nxt = (ctx or {}).get("next_event")
    if cal.get("dash"):
        out["in11"] = cal["dash"]
    elif nxt:
        out["in11"] = {"title": nxt["t"], "ccy": nxt["ccy"],
                       "in_min": int(round((nxt["at"] - now)
                                           .total_seconds() / 60.0)),
                       "gap": _print_gap(symbol, cls, nxt, now, atr1h)}
    else:
        out["in11"] = "— (no high-impact print within 72 h)"
    tape = in12(symbol, cls, now, atr1h=atr1h)
    rows15, rows5 = tape.pop("_rows15"), tape.pop("_rows5")
    out["in12"] = tape
    old15 = rows15[:-8] if len(rows15) > 8 else []
    out["in12_5m"] = list(rows5)
    out["in12_15m_old"] = list(old15)
    out["in9"] = out["in9"] if isinstance(out["in9"], list) else out["in9"]
    return out
