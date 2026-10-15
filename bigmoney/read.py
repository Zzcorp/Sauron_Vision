"""The board's read, and the contract other parts read (spec §2.6, §2.12).

`read_board` makes one deterministic read per market and never raises.
The public contract below it (newest, market, ticket_words, brief_lines,
ahead, blind) is what the page, the brief, the ticket and, later, the Mind
and the five voices read. Nothing on a money path imports any of it
(tests/test_big_money_board.py scans the sources).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from datetime import timezone as dt_tz

from django.utils import timezone

from bigmoney import calendar as bmcal
from bigmoney import cells as C
from bigmoney import words as W
from bigmoney.cells import (ACTIVE_AT, BOND_LEG, COVERAGE_MIN, CROWD_FLAGS,  # noqa: F401
                            CTA_LOOKBACKS, CTA_NEAR, COT_CHANGE_DEAD_ZONE,
                            COT_FRESH_DAYS, COT_FRESH_DAYS_DELAYED, FLOW_BASE_DAYS,
                            FLOW_DAYS, FX_FIX_DAYS, GRADE, LEAN_AT, LOSING_AT,
                            MIN_MONTHS, REBALANCE_DAYS, REVERSAL_DAYS,
                            SIGMA_MONTHS, TIDE_MIN_WEEKS, TIDE_SIGMA_WEEKS,
                            TIDE_WEEKS, VRP_DAYS, VRP_HISTORY_DAYS, VRP_MIN_DAYS)
from bigmoney.inputs import Store
from bigmoney.rows import (COT_FX_PAIRS, FX_FIX_PAIRS, GLOBAL, INSTRUMENTS,
                           ROW_ORDER, ROWS, ticket_target)

logger = logging.getLogger(__name__)
UTC = dt_tz.utc

READ_MAX_AGE_H = 30
NO_READ = W.NO_READ
SCORE_MIN_N = 40
COMPONENT_KEY = "big_money_board"
#: Commodities that are rows already: not repeated under instruments.
ROW_COMMODITIES = ("XAUUSD", "WTIUSD")


# ── the read ─────────────────────────────────────────────────────────────

def _row_cells(ctx, key) -> dict:
    row = ROWS[key]
    graded, cot_sym, etf = row["graded_on"], row["cot"], row["etf"]
    cells = {}
    if key in ("us_equities", "treasuries"):
        cells["rebalance"] = C.rebalance_cell(ctx, key)
        cells["rebalance_reversal"] = C.reversal_cell(ctx, key)
    if key == "us_dollar":
        cells["fx_fix"] = C.fx_fix_row_cell(ctx)
    if cot_sym:
        cells["cot_change"] = C.cot_change_cell(ctx, key, cot_sym, proxy=graded,
                                                title=row["title"])
        cells["crowding"] = C.crowding_cell(ctx, key, cot_sym, proxy=graded)
        cells["crowd_losing"] = C.crowd_losing_cell(ctx, key, cot_sym,
                                                    proxy=graded)
    cells["cta"] = C.cta_cell(ctx, key, graded, title=row["title"])
    if key == "us_equities":
        cells["vrp"] = C.vrp_cell(ctx)
        cells["opex"] = C.opex_cell(ctx)
    cells["flows"] = C.flows_cell(ctx, key, etf)
    return cells


def lean_of(cells: dict) -> dict:
    """The week's lean from the in-season lean cells (spec §2.6)."""
    R = U = acc = 0.0
    contrib, reasons = [], []
    for name, c in cells.items():
        if name.startswith("_") or not isinstance(c, dict):
            continue
        if c.get("role") != "lean" or c.get("state") == "out_of_season":
            continue
        w = float(c.get("weight") or 0.0)
        if w <= 0:
            continue
        if c.get("state") == "read":
            R += w
            s = float(c.get("score") or 0.0)
            acc += w * s
            if w * abs(s) >= 0.1 and c.get("from"):
                contrib.append((w * abs(s), c["from"]))
        else:
            U += w
            if c.get("why"):
                reasons.append(c["why"])
    if R + U == 0:
        return {"lean": None, "label": W.NO_FOOTPRINT, "coverage": None,
                "from": [], "reasons": []}
    coverage = R / (R + U)
    if coverage < COVERAGE_MIN:
        return {"lean": None, "label": W.UNREAD, "coverage": round(coverage, 3),
                "from": [], "reasons": reasons}
    L = acc / R
    label = (W.LEANS_UP if L >= LEAN_AT else W.LEANS_DOWN if L <= -LEAN_AT
             else W.NO_CLEAR_LEAN)
    return {"lean": round(L, 4), "label": label,
            "coverage": round(coverage, 3),
            "from": [f for _v, f in sorted(contrib, key=lambda t: -t[0])],
            "reasons": reasons}


def _risk_flags(cells, lean, stress_flags, forced) -> list:
    flags = []
    crowding = cells.get("crowding") or {}
    if crowding.get("state") == "read" and crowding.get("flag"):
        flags.append(crowding["flag"])
        side = crowding.get("side")
        if lean is not None and ((lean >= LEAN_AT and side == "long")
                                 or (lean <= -LEAN_AT and side == "short")):
            flags.append(W.FLAG_LEAN_CROWDED)
    if (cells.get("crowd_losing") or {}).get("state") == "read":
        flags.append(W.FLAG_CROWD_LOSING)
    flags.extend(stress_flags)
    if forced:
        flags.append(W.FLAG_FORCED_SOON.format(events=", ".join(forced)))
    return flags


def _forced_soon(events, key, today, cal) -> list:
    horizon = cal.add_business_days(today, 2)
    return [e["event"] for e in events
            if e.get("forced") and key in e.get("rows", ())
            and today.isoformat() <= e["date"] <= horizon.isoformat()]


def _instrument_symbols(ctx) -> list:
    """The four fix pairs, every other FX pair the COT reader maps, and every
    commodity with at least 52 weeks of COT (spec §2.3)."""
    out = []
    for s in list(FX_FIX_PAIRS) + [p for p in COT_FX_PAIRS if p not in FX_FIX_PAIRS]:
        if ctx.store.instrument(s) is not None and s not in out:
            out.append(s)
    try:
        from django.db.models import Count

        from scraping.models import COTReport
        qs = (COTReport.objects.filter(instrument__asset_class="commodity",
                                       report_date__lte=ctx.as_of)
              .values("instrument__symbol").annotate(n=Count("id")))
        commodities = sorted(r["instrument__symbol"] for r in qs
                             if r["n"] >= C.COT_MIN_WEEKS)
    except Exception:  # noqa: BLE001
        commodities = []
    for s in commodities:
        if s not in ROW_COMMODITIES and s not in out:
            out.append(s)
    return out


def _instrument_cells(ctx, symbol) -> dict:
    commodity = ctx.store.asset_class(symbol) == "commodity"
    cells = {}
    if symbol in FX_FIX_PAIRS:
        cells["fx_fix"] = C.fx_fix_pair_cell(ctx, symbol)
    cells["cot_change"] = C.cot_change_cell(ctx, symbol, symbol, proxy=symbol,
                                            title=symbol, commodity=commodity)
    cells["crowding"] = C.crowding_cell(ctx, symbol, symbol, proxy=symbol)
    cells["crowd_losing"] = C.crowd_losing_cell(ctx, symbol, symbol,
                                                proxy=symbol)
    return cells


def _unread_of(cells) -> list:
    out = []
    for name, c in cells.items():
        if isinstance(c, dict) and c.get("state") == "unread" and c.get("why"):
            if c["why"] not in out:
                out.append(c["why"])
    return out


def _count(cells) -> tuple:
    m = n = 0
    for name, c in cells.items():
        if not isinstance(c, dict) or name.startswith("_"):
            continue
        if c.get("state") in ("read", "unread"):
            m += 1
            n += c.get("state") == "unread"
    return m, n


def read_time_for(as_of: date) -> datetime:
    """A replay's read time: the first morning run after the as-of close."""
    return datetime.combine(as_of + timedelta(days=1), time(5, 20), tzinfo=UTC)


def read_board(as_of=None, *, replayed=False, run="morning", store=None,
               cal=None, now=None, weights=None) -> dict:
    """One read per market. Never raises: an exception anywhere is a board
    whose every market says why it could not be read."""
    now = now or timezone.now()
    try:
        cal = cal or bmcal.BusinessCalendar.from_db()
        if as_of is None:
            as_of = bmcal.as_of_for(now, cal)
        read_time = read_time_for(as_of) if replayed else now
        store = store or Store(upto=as_of if replayed else None)
        if weights is None:
            weights = {}
            if not replayed:
                try:
                    from bigmoney.score import effective_weights
                    weights = effective_weights(cal=cal)
                except Exception as e:  # noqa: BLE001
                    logger.warning("[big money] weights unreadable: %s", e)
        ctx = C.Ctx(store, cal, as_of, run=run, replayed=replayed,
                    read_time=read_time, now=now, weights=weights)
        return _read(ctx)
    except Exception as e:  # noqa: BLE001
        logger.exception("[big money] read failed")
        reason = W.R_UNREADABLE.format(name=type(e).__name__)
        if not isinstance(as_of, date):
            # The as-of day could not even be computed: the board is dated
            # the day before the run so it keeps its shape. It is never
            # stored ("failed"): it would overwrite a good read of that day
            # and its pending claims, or outrank Friday's read all weekend.
            as_of = (now - timedelta(days=1)).date()
        return {"as_of": as_of.isoformat(), "failed": True,
                "run": run, "replayed": replayed, "computed_at": now.isoformat(),
                "rows": {k: {"title": ROWS[k]["title"], "lean": None,
                             "lean_label": W.UNREAD, "lean_from": [],
                             "coverage": None, "current": [], "risk": [],
                             "cells": {}, "unread": [reason]}
                         for k in ROW_ORDER},
                "global": {"cells": {}, "current": [], "risk": [],
                           "unread": [reason], "sources": []},
                "instruments": {"cells": {}, "unread": [reason]},
                "footprints": 1, "unread_count": 1, "reasons": [reason]}


def _read(ctx) -> dict:
    rows, all_m, all_n, reasons = {}, 0, 0, []
    for key in ROW_ORDER:
        rows[key] = _row_cells(ctx, key)

    # The global row: the tide, the stress, and the calendar (with the
    # trend followers' triggers within one daily move).
    triggers = []
    for key in ROW_ORDER:
        trig = (rows[key].get("cta") or {}).get("trigger")
        if trig:
            triggers.append((date.fromisoformat(trig["date"]), key,
                             ROWS[key]["title"]))
    g_cells = {"tide": C.tide_cell(ctx), "stress": C.stress_cell(ctx),
               "calendar": C.calendar_cell(ctx, triggers)}
    events = g_cells["calendar"].get("events") or []
    stress_flags = []
    st = g_cells["stress"]
    if st.get("state") == "read":
        # From the cell's own level (market_stress.raw_level), so the flag
        # and the words come from one judgement: a score past the crisis
        # line with no index read and the VIX under 35 is "Stressed" in
        # both, never "market in crisis" beside "Stressed".
        level = st.get("level")
        if level == "crisis":
            stress_flags.append(W.FLAG_CRISIS)
        elif level in ("stressed", "recovery"):
            stress_flags.append(W.FLAG_STRESSED)

    today = ctx.read_time.date()
    out_rows = {}
    for key in ROW_ORDER:
        cells = rows[key]
        lean = lean_of(cells)
        current = [cells[k]["words"] for k in ("cta", "vrp")
                   if (cells.get(k) or {}).get("state") == "read"]
        risk = _risk_flags(cells, lean["lean"], stress_flags,
                           _forced_soon(events, key, today, ctx.cal))
        unread = _unread_of(cells)
        m, n = _count(cells)
        all_m, all_n = all_m + m, all_n + n
        reasons.extend(r for r in unread if r not in reasons)
        out_rows[key] = {"title": ROWS[key]["title"], "lean": lean["lean"],
                         "lean_label": lean["label"], "lean_from": lean["from"],
                         "coverage": lean["coverage"], "current": current,
                         "risk": risk, "cells": cells, "unread": unread}

    inst = {}
    inst_unread = []
    for sym in _instrument_symbols(ctx):
        cells = _instrument_cells(ctx, sym)
        lean = lean_of(cells)
        cells["_lean"] = {"lean": lean["lean"], "label": lean["label"],
                          "from": lean["from"], "coverage": lean["coverage"],
                          "risk": _risk_flags(cells, lean["lean"], [], [])}
        inst[sym] = cells
        m, n = _count(cells)
        all_m, all_n = all_m + m, all_n + n
        for r in _unread_of(cells):
            if r not in inst_unread:
                inst_unread.append(r)
    reasons.extend(r for r in inst_unread if r not in reasons)

    g_unread = _unread_of(g_cells)
    m, n = _count({k: v for k, v in g_cells.items() if k != "calendar"})
    all_m, all_n = all_m + m, all_n + n
    notes = list(g_cells["calendar"].get("notes") or [])
    notes.extend(sorted(ctx.cal.reasons))
    reasons.extend(r for r in g_unread if r not in reasons)
    g_unread.extend(r for r in notes if r not in g_unread)

    sources = sorted(ctx.sources.values(), key=lambda s: s["input"])
    gaps = ctx.cal.gaps(since=ctx.as_of - timedelta(days=3 * 366))
    if gaps:
        a, b, n_days = gaps[-1]
        sources.insert(0, {"input": "SPX500 tape", "newest": b.isoformat(),
                           "age": None, "bound": bmcal.TAPE_GAP_DAYS,
                           "state": "gap in the tape",
                           "why": W.R_GAP.format(n=n_days, day=W.day_year(b))})
    g_cells["_sources"] = sources
    current = [g_cells["tide"]["words"]] if g_cells["tide"].get("state") == "read" else []

    return {"as_of": ctx.as_of.isoformat(), "run": ctx.run,
            "replayed": ctx.replayed, "computed_at": ctx.now.isoformat(),
            "read_time": ctx.read_time.isoformat(),
            "rows": out_rows,
            "global": {"cells": g_cells, "current": current,
                       "risk": stress_flags, "unread": g_unread,
                       "sources": sources},
            "instruments": {"cells": inst, "unread": inst_unread},
            "footprints": all_m, "unread_count": all_n, "reasons": reasons}


# ── the contract (never raises) ──────────────────────────────────────────

def is_on() -> bool:
    try:
        from core.platform_control import is_component_enabled
        return is_component_enabled(COMPONENT_KEY)
    except Exception:  # noqa: BLE001
        return False


def newest(max_age_h=READ_MAX_AGE_H, *, now=None) -> dict:
    """{"ok", "reason", "reads": {row: BigMoneyRead}, "as_of", "computed_at",
    "run", "age_h"}: the newest live read, refused (ok False, with the
    reason) when none exists or it is older than `max_age_h`."""
    out = {"ok": False, "reason": NO_READ, "reads": {},
           "as_of": None, "computed_at": None, "run": None, "age_h": None}
    try:
        from bigmoney.models import BigMoneyRead
        head = (BigMoneyRead.objects.filter(replayed=False)
                .order_by("-as_of", "-computed_at").first())
        if head is None:
            return out
        reads = {r.row: r for r in BigMoneyRead.objects.filter(
            replayed=False, as_of=head.as_of)}
        computed = max(r.computed_at for r in reads.values())
        age_h = ((now or timezone.now()) - computed).total_seconds() / 3600.0
        out.update({"reads": reads, "as_of": head.as_of,
                    "computed_at": computed, "run": head.run,
                    "age_h": age_h})
        if max_age_h is not None and age_h > max_age_h:
            out["reason"] = W.TICKET_STALE.format(n=int(age_h))
            return out
        out.update({"ok": True, "reason": ""})
    except Exception as e:  # noqa: BLE001
        out["reason"] = W.TICKET_ERROR.format(name=type(e).__name__)
    return out


def _instrument_entry(reads, symbol):
    r = reads.get(INSTRUMENTS)
    return ((r.cells or {}).get(symbol) if r is not None else None) or None


def market(row_or_symbol, *, head=None) -> dict:
    """Lean, from, current, risk, record and unread for one row or
    instrument, from the newest read."""
    head = head or newest()
    out = {"ok": False, "lean": None, "label": W.UNREAD, "from": [],
           "current": [], "risk": [], "record": [], "unread": [],
           "reason": head.get("reason", "")}
    try:
        reads = head.get("reads") or {}
        if not head.get("ok"):
            return out
        key = row_or_symbol
        if key in reads and key in ROWS:
            r = reads[key]
            out.update({"ok": True, "lean": r.lean, "label": r.lean_label,
                        "from": list(r.lean_from or []),
                        "current": list(r.current or []),
                        "risk": list(r.risk or []),
                        "unread": list(r.unread or []), "cells": r.cells})
        else:
            entry = _instrument_entry(reads, key)
            if entry:
                lean = entry.get("_lean") or {}
                out.update({"ok": True, "lean": lean.get("lean"),
                            "label": lean.get("label", W.UNREAD),
                            "from": lean.get("from") or [],
                            "risk": lean.get("risk") or [],
                            "unread": _unread_of(entry), "cells": entry})
        if out["ok"]:
            try:
                from bigmoney.score import record
                out["record"] = [r for r in record(replayed=False)
                                 if r["market"] == key]
            except Exception:  # noqa: BLE001
                out["record"] = []
    except Exception as e:  # noqa: BLE001
        out["reason"] = W.TICKET_ERROR.format(name=type(e).__name__)
    return out


def _side(side) -> str:
    return "buy" if str(side or "").upper() in ("BUY", "LONG") else "sell"


def _when(dt) -> str:
    return f"{W.WEEKDAYS[dt.weekday()]} {dt:%H:%M}"


def _next_event(head, row) -> str:
    g = (head.get("reads") or {}).get(GLOBAL)
    events = (((g.cells or {}).get("calendar") or {}).get("events") or []) if g else []
    today = timezone.now().date().isoformat()
    for e in events:
        if row in e.get("rows", ()) and e["date"] >= today and (
                e.get("forced") or e.get("directional")):
            return W.TICKET_AHEAD.format(event=e["event"],
                                         day=W.day(date.fromisoformat(e["date"])))
    return ""


def _extras(cells, head, row) -> str:
    text = ""
    crowding = (cells or {}).get("crowding") or {}
    if crowding.get("state") == "read" and crowding.get("degree"):
        text += W.TICKET_CROWDING.format(words=crowding["words"])
    cta = (cells or {}).get("cta") or {}
    if cta.get("state") == "read" and cta.get("short"):
        text += W.TICKET_TREND.format(words=cta["short"])
    if row:
        text += _next_event(head, row)
    if head.get("computed_at"):
        text += W.TICKET_READ_AT.format(when=_when(head["computed_at"]))
    return text


def ticket_words(symbol, side) -> dict:
    """{ok, words, as_of}: the ticket note for `symbol` and `side`. Never
    raises; no quantity, stop, leverage or button reads it."""
    out = {"ok": False, "words": "", "as_of": None}
    try:
        if not is_on():
            out["words"] = W.TICKET_OFF
            return out
        sym = str(symbol or "").upper()
        mine = _side(side)
        try:
            from instruments.models import Instrument
            inst = Instrument.objects.filter(symbol=sym).first()
        except Exception:  # noqa: BLE001
            inst = None
        target = ticket_target(sym, inst)
        head = newest()
        if not head.get("ok"):
            reason = head.get("reason") or NO_READ
            out["words"] = W.TICKET_NONE if reason == NO_READ else reason
            return out
        out["as_of"] = head["as_of"].isoformat() if head.get("as_of") else None
        reads = head["reads"]
        if target is None:
            out["words"] = W.TICKET_OUTSIDE
            return out

        # A fix pair in season reads its own fix first.
        if target["kind"] == "fix_pair":
            entry = _instrument_entry(reads, sym) or {}
            fix = entry.get("fx_fix") or {}
            if fix.get("state") == "read" and abs(fix.get("score") or 0) >= ACTIVE_AT:
                favour = (fix.get("foreign") or 0) > 0
                with_it = (fix["score"] > 0) == (mine == "buy")
                out["words"] = W.TICKET_FIX_PAIR.format(
                    pair=sym, verb="favours" if favour else "leans against",
                    ccy=fix.get("ccy", ""), z=W.z(fix.get("z") or 0),
                    side=mine, way="with it" if with_it else "against it")
                out["words"] += _extras(entry, head, None)
                out["ok"] = True
                return out

        if target["kind"] == "instrument":
            entry = _instrument_entry(reads, sym)
            if not entry:
                out["words"] = W.TICKET_OUTSIDE
                return out
            lean = entry.get("_lean") or {}
            out["words"] = _lean_words(lean.get("label"), lean.get("lean"),
                                       lean.get("from") or [], sym, mine,
                                       entry, commodity=True)
            out["words"] += _extras(entry, head, None)
            out["ok"] = True
            return out

        row = target["row"]
        r = reads.get(row)
        if r is None:
            out["words"] = W.TICKET_NONE
            return out
        title = ROWS[row]["title"]
        if target["kind"] in ("pair", "fix_pair"):
            buys = target["usd"] == 1 if mine == "buy" else target["usd"] == -1
            if r.lean_label in (W.LEANS_UP, W.LEANS_DOWN):
                with_it = (r.lean > 0) == buys
                out["words"] = W.TICKET_PAIR.format(
                    label=r.lean_label.lower(), from_words=", ".join(r.lean_from),
                    side=mine, pair=sym, buys="buys" if buys else "sells",
                    way="with it" if with_it else "against it")
            else:
                out["words"] = _lean_words(r.lean_label, r.lean, r.lean_from,
                                           title, mine, r.cells)
        else:
            out["words"] = _lean_words(r.lean_label, r.lean, r.lean_from, title,
                                       mine, r.cells)
        out["words"] += _extras(r.cells, head, row)
        out["ok"] = True
    except Exception as e:  # noqa: BLE001
        out["words"] = W.TICKET_ERROR.format(name=type(e).__name__)
    return out


def _lean_words(label, lean, lean_from, market_name, mine, cells,
                commodity=False) -> str:
    if label in (W.LEANS_UP, W.LEANS_DOWN):
        with_it = (lean > 0) == (mine == "buy")
        way = "with it" if with_it else "against it"
        if commodity:
            return W.TICKET_COMMODITY.format(symbol=market_name,
                                             label=label.lower(), side=mine,
                                             way=way)
        return W.TICKET_ROW.format(market=market_name, label=label,
                                   from_words=", ".join(lean_from), side=mine,
                                   way=way)
    if label == W.NO_CLEAR_LEAN:
        return W.TICKET_NO_CLEAR.format(market=market_name, side=mine)
    if label == W.UNREAD:
        reasons = _unread_of(cells or {})
        return W.TICKET_UNREAD.format(reason=reasons[0] if reasons else W.UNREAD)
    return W.TICKET_NO_FOOTPRINT.format(market=market_name)


def brief_lines(*, head=None) -> list:
    """The morning brief's section: at most 9 lines, no decimals, no
    percentages, no currency figures, no levels."""
    try:
        head = head or newest()
        if not head.get("ok"):
            if head.get("reads") and head.get("age_h") is not None:
                return [W.BRIEF_STALE.format(n=int(head["age_h"]))]
            return [W.BRIEF_NONE]
        reads = head["reads"]
        markets = []
        for key in ROW_ORDER:
            r = reads.get(key)
            if r is None:
                continue
            label = (r.lean_label or W.UNREAD).lower()
            from_part = (f" ({', '.join(r.lean_from)})"
                         if r.lean_label in (W.LEANS_UP, W.LEANS_DOWN)
                         and r.lean_from else "")
            flags = [f for f in (r.risk or []) if not f.startswith(
                W.FLAG_FORCED_SOON.split("{")[0])]
            flag_part = f" · {flags[0]}" if flags else ""
            markets.append(W.BRIEF_MARKET.format(market=ROWS[key]["title"],
                                                 label=label, from_part=from_part,
                                                 flag_part=flag_part))
        optional = []
        inst = reads.get(INSTRUMENTS)
        n_comm = 0
        for sym, entry in sorted(((inst.cells or {}) if inst else {}).items()):
            lean = (entry or {}).get("_lean") or {}
            if lean.get("label") in (W.LEANS_UP, W.LEANS_DOWN) and \
                    ((entry.get("cot_change") or {}).get("role") == "lean") and \
                    n_comm < 2:
                optional.append(W.BRIEF_COMMODITY.format(
                    symbol=sym, label=lean["label"].lower()))
                n_comm += 1
        near = [ROWS[k]["title"] for k in ROW_ORDER
                if reads.get(k) is not None
                and (((reads[k].cells or {}).get("cta") or {}).get("trigger"))]
        if near:
            optional.append(W.BRIEF_TREND.format(markets=", ".join(near)))
        g = reads.get(GLOBAL)
        tide = ((g.cells or {}).get("tide") or {}) if g else {}
        if tide.get("state") == "read":
            optional.append(W.BRIEF_TIDE.format(state=tide.get("tide_state")))
        tail = []
        events = ahead(30, head=head)[:3]
        if events:
            tail.append(W.BRIEF_AHEAD.format(events=" · ".join(
                f"{e['event']} {W.day(date.fromisoformat(e['date']))}"
                for e in events)))
        unread = blind(head=head)
        if unread:
            more = (f" and {len(unread) - 2} more" if len(unread) > 2 else "")
            tail.append(W.BRIEF_UNREAD.format(
                reasons="; ".join(u["reason"] for u in unread[:2]), more=more))
        room = 9 - len(markets) - len(tail)
        return markets + optional[:max(0, room)] + tail
    except Exception as e:  # noqa: BLE001
        logger.warning("[big money] brief unreadable: %s", e)
        return [W.TICKET_ERROR.format(name=type(e).__name__)]


def ahead(days=30, *, head=None) -> list:
    """The calendar rows from today through `days` ahead: the newest read's
    when it is current, else computed now from the rules."""
    try:
        head = head or newest()
        today = timezone.now().date()
        end = (today + timedelta(days=days)).isoformat()
        g = (head.get("reads") or {}).get(GLOBAL) if head.get("ok") else None
        events = (((g.cells or {}).get("calendar") or {}).get("events")
                  if g else None)
        if events is None:
            cal = bmcal.BusinessCalendar.from_db()
            events, _ = bmcal.events(today, days, cal)
        return [e for e in events if today.isoformat() <= e["date"] <= end]
    except Exception as e:  # noqa: BLE001
        logger.warning("[big money] calendar unreadable: %s", e)
        return []


def blind(*, head=None) -> list:
    """[{"where", "reason"}]: every unread input of the newest read, each
    reason carrying its remedy."""
    out, seen = [], set()
    try:
        head = head or newest(max_age_h=None)
        for row, r in sorted((head.get("reads") or {}).items()):
            for reason in (r.unread or []):
                if reason not in seen:
                    seen.add(reason)
                    out.append({"where": row, "reason": reason})
    except Exception as e:  # noqa: BLE001
        out.append({"where": "board",
                    "reason": W.TICKET_ERROR.format(name=type(e).__name__)})
    return out
