"""The /big-money/ page and the ticket-note endpoint (spec §2.11).

Every read is fenced, as on /horizon/ (dashboard/views_horizon.py): a page
that 500s because one table is unreadable hides the board the operator came
to read. The ticket note is its own endpoint, never inside the order
preview: _execute calls _preview (bot_program/manual_trade.py), so a note
there would run inside the order path.
"""
from __future__ import annotations

import logging
from datetime import date

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from bigmoney import words as W

logger = logging.getLogger(__name__)

WHY_ORDER = ("rebalance", "rebalance_reversal", "fx_fix", "cot_change", "opex")


def _cell_view(name, c) -> dict:
    c = c or {}
    state = c.get("state") or "unread"
    return {"name": W.FOOTPRINT_NAMES.get(name, name), "key": name,
            "state": state, "words": c.get("words") or "",
            "dash": state == "unread",
            "title": W.DASH_TITLE.format(reason=c.get("why") or W.UNREAD)
            if state == "unread" else (c.get("why") or ""),
            "grade": W.GRADE_WORDS.get(c.get("grade"), ""),
            "role": W.ROLE_WORDS.get(c.get("role"), ""),
            "zeroed": bool(c.get("zeroed")),
            "score": c.get("score")}


def _record_index(live, replay) -> dict:
    out = {}
    for which, rows in (("live", live), ("replayed", replay)):
        for r in rows:
            slot = out.setdefault((r["footprint"], r["market"]), {
                "footprint": W.FOOTPRINT_NAMES.get(r["footprint"], r["footprint"]),
                "market": r["market"], "claim": _claim_words(r),
                "live": "", "replayed": "", "verdict": "", "cost": ""})
            slot[which] = r["verdict"]
            if which == "live" or not slot["verdict"]:
                slot["verdict"] = r["verdict"]
            if r.get("cost") and (which == "live" or not slot["cost"]):
                slot["cost"] = r["cost"]
    return out


def _claim_words(r) -> str:
    if r["claim"] == "tail":
        return W.CLAIM_TAIL.format(h=r["h"])
    from bigmoney.rows import CRYPTO_SYMBOLS
    if r.get("proxy") in CRYPTO_SYMBOLS:
        return W.CLAIM_DIRECTION_DAYS.format(h=r["h"])
    return W.CLAIM_DIRECTION.format(h=r["h"])


@login_required
def board(request):
    from bigmoney.read import READ_MAX_AGE_H, ahead, is_on, newest
    from bigmoney.rows import GLOBAL, INSTRUMENTS, ROW_ORDER, ROWS

    head = {"ok": False, "reads": {}, "age_h": None}
    try:
        head = newest(max_age_h=None)
    except Exception as e:  # noqa: BLE001
        logger.warning("[big money page] newest unreadable: %s", e)
    reads = head.get("reads") or {}
    on = is_on()
    status = []
    if not reads:
        status.append(W.EMPTY)
    else:
        if not on:
            status.append(W.OFF.format(when=W.day_year(head["as_of"])))
        if head.get("age_h") is not None and head["age_h"] > READ_MAX_AGE_H:
            status.append(W.STALE.format(n=int(head["age_h"])))

    as_of_line = ""
    if reads and head.get("computed_at"):
        comp = head["computed_at"]
        run = {"morning": "Morning", "evening": "Evening"}.get(head.get("run"),
                                                                "Manual")
        as_of_line = W.AS_OF.format(run=run, hhmm=f"{comp:%H:%M}",
                                    day=W.day_year(comp.date()),
                                    market_day=W.day(head["as_of"]))

    live, replay = [], []
    try:
        from bigmoney.score import record
        live = record(replayed=False)
        replay = record(replayed=True)
    except Exception as e:  # noqa: BLE001
        logger.warning("[big money page] record unreadable: %s", e)
    rec = _record_index(live, replay)

    rows = []
    for key in ROW_ORDER:
        r = reads.get(key)
        cells = (r.cells if r is not None else {}) or {}
        why = [_cell_view(n, cells.get(n)) for n in WHY_ORDER if n in cells
               and (cells[n] or {}).get("state") != "out_of_season"]
        seasons = [_cell_view(n, cells.get(n)) for n in WHY_ORDER if n in cells
                   and (cells[n] or {}).get("state") == "out_of_season"]
        current = [_cell_view(n, cells.get(n)) for n in ("cta", "vrp")
                   if n in cells]
        verdicts = [v for (fp, mk), v in rec.items() if mk == key]
        rows.append({
            "key": key, "title": ROWS[key]["title"],
            "label": (r.lean_label if r is not None else "") or W.UNREAD,
            "lean": r.lean if r is not None else None,
            "lean_from": (r.lean_from if r is not None else []) or [],
            "why": why, "seasons": seasons, "current": current,
            "crowding": _cell_view("crowding", cells.get("crowding"))
            if "crowding" in cells else None,
            "losing": _cell_view("crowd_losing", cells.get("crowd_losing"))
            if (cells.get("crowd_losing") or {}).get("state") == "read" else None,
            "flows": _cell_view("flows", cells.get("flows"))
            if "flows" in cells else None,
            "risk": (r.risk if r is not None else []) or [],
            "unread": (r.unread if r is not None else []) or [],
            "record": verdicts,
            "hint": W.DOLLAR_HINT if key == "us_dollar" else "",
            "note": W.CRYPTO_NOTE if key == "crypto" else "",
        })

    instruments = []
    inst = reads.get(INSTRUMENTS)
    for sym, entry in sorted(((inst.cells or {}) if inst else {}).items()):
        lean = (entry or {}).get("_lean") or {}
        instruments.append({
            "symbol": sym, "label": lean.get("label") or W.UNREAD,
            "from": lean.get("from") or [], "risk": lean.get("risk") or [],
            "cells": [_cell_view(n, entry.get(n)) for n in
                      ("fx_fix", "cot_change", "crowding", "crowd_losing")
                      if n in entry and (entry[n] or {}).get("state") != "out_of_season"],
        })

    g = reads.get(GLOBAL)
    g_cells = (g.cells if g is not None else {}) or {}
    calendar = []
    for e in ahead(30, head=head if head.get("ok") else {"ok": False}):
        calendar.append({**e, "day": W.day(date.fromisoformat(e["date"])),
                         "kind_words": W.KIND_WORDS.get(e["kind"], e["kind"])})

    context = {
        "page_id": "big_money", "W": W, "status": status,
        "as_of_line": as_of_line, "rows": rows, "instruments": instruments,
        "calendar": calendar,
        "tide": _cell_view("tide", g_cells.get("tide")) if g_cells else None,
        "stress": _cell_view("stress", g_cells.get("stress")) if g_cells else None,
        "record": sorted(rec.values(), key=lambda r: (r["footprint"], r["market"])),
        "sources": g_cells.get("_sources") or [],
        "global_unread": (g.unread if g is not None else []) or [],
        "has_replay": bool(replay),
    }
    return render(request, "bigmoney/board.html", context)


@login_required
@require_GET
def note(request):
    """{ok, words, as_of}: the ticket note, from one indexed query of the
    newest read. Information, never a gate."""
    from bigmoney.read import ticket_words
    try:
        out = ticket_words(request.GET.get("symbol", ""),
                           request.GET.get("side", ""))
    except Exception as e:  # noqa: BLE001
        out = {"ok": False, "words": W.TICKET_ERROR.format(name=type(e).__name__),
               "as_of": None}
    out["label"] = W.TICKET_LABEL
    out["suffix"] = W.TICKET_SUFFIX
    return JsonResponse(out)
