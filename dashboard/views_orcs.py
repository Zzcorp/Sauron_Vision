"""THE ORCS' PAGES (spec §9.2, O1d): /orcs/, /orcs/<id>/ and /orcs/seats/.

Read by code from the Orc tables; nothing here calls a model, a broker or
an order path. The one write is the operator's own thesis on his Orc's
page (`orc_thesis`): a journal entry of kind `thesis`, author `operator`,
through journal.append, only while the `orcs` switch is ON. It is his
text (never a fact the model may cite: no F-id) and it is kept beside the
entry's thesis: Orc.thesis is never rewritten, and nothing the care does
changes.

OFF IS TODAY (spec §11 O1). The pages exist only while the `orcs` switch
is ON: OFF, every URL here answers the plain 404 it answered before the
Orcs, before any login redirect (`_while_on`, the outermost decorator).
The record stays in the tables and reads again when the switch is ON.

An Orc's number is its idea's root trade id, as its label says ("Orc
#12"); a leg's number redirects to its idea. Another user's number is a
404 that names nobody. /orcs/seats/ and the AI spend lines pool every
user's ideas or the platform's spend, so they are staff only. The pages
cost a constant number of queries whatever the number of Orcs.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from functools import wraps

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

logger = logging.getLogger(__name__)

NO_INTENTS = "No intents: an Orc proposes nothing until it reasons."
SEATS_NOTE = ("In this release no Orc takes a step, so Δ measures the care "
              "ghost against the care, not an Orc's skill. No seat holds any "
              "power.")
THESIS_FORM = ("State your thesis in your own words. It is kept beside the "
               "entry's, never replaces it, and changes nothing the care "
               "does.")
THESIS_SAVED = "Your thesis is kept beside the entry's."
THESIS_OFF = "The Orcs are switched off: nothing was written."
THESIS_EMPTY = "Write your thesis first: nothing was written."
THESIS_SAME = "That is already your thesis: nothing was written."
THESIS_ENDED = "This idea has ended: nothing was written."
NOT_FOUND = "No Orc by that number in your book."
#: How an author's entries are drawn: code facts, the Orc's notes, yours.
AUTHOR_STYLE = {"code": "fact", "care": "fact", "reconcile": "fact",
                "morgul": "fact", "orc": "note", "captain": "note",
                "operator": "yours"}


def _r(x):
    return "—" if x is None else f"{x:+.2f}R"


def _orcs_gate() -> bool:
    from bot_program.orcs.switches import orcs_on
    return bool(orcs_on())


def _while_on(view):
    """The page exists only while the `orcs` switch is ON. OFF (or
    unreadable), it raises the bare Http404 an unknown URL raises, so the
    answer is the one before the Orcs, whoever asks. `switch_gate` tells
    the route probe (core/management/commands/probe_routes.py) that this
    404 is the design while the switch is OFF, never a missing page."""
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not _orcs_gate():
            raise Http404()
        return view(request, *args, **kwargs)
    wrapped.switch_gate = _orcs_gate
    return wrapped


def _grade_t(g):
    if g is None:
        return ""
    return (f"the position {_r(g.orc_r_gross)}, the care ghost "
            f"{_r(g.ghost_r)}, Δ {_r(g.delta_care)}"
            + (f" ({g.exit_label})" if g.exit_label else ""))


def _tracks(orc_ids, arms=None) -> dict:
    from bot_program.orcs.models import OrcTrack
    qs = OrcTrack.objects.filter(orc_id__in=list(orc_ids))
    if arms:
        qs = qs.filter(arm__in=arms)
    out = {}
    for t in qs:
        out.setdefault(t.orc_id, []).append(t)
    return out


def _grade(orc):
    return getattr(orc, "grade", None)


@_while_on
@login_required
def orcs_list(request):
    """The viewer's Orcs: those on watch first, then the ones that ended in
    the last 30 days with their grade, and the seats they sit on."""
    from django.db.models import Q

    from bot_program.orcs import notes
    from bot_program.orcs.constants import (ARM_CARE, ARM_ORC,
                                            PAGE_DEAD_DAYS, STATE_DEAD)
    from bot_program.orcs.models import Orc

    now = timezone.now()
    since = now - timedelta(days=PAGE_DEAD_DAYS)
    orcs = list(Orc.objects.select_related("seat", "root_trade", "grade")
                .filter(user=request.user)
                .filter(~Q(state=STATE_DEAD)
                        | Q(state=STATE_DEAD, died_at__gte=since)))
    tracks = _tracks([o.pk for o in orcs], (ARM_CARE, ARM_ORC))
    rows = []
    for orc in orcs:
        sl = notes.slot(orc, trade=orc.root_trade,
                        tracks=tracks.get(orc.pk, ()), now=now)
        rows.append({"orc": orc, "slot": sl, "line": notes.line(sl),
                     "dead": orc.state == STATE_DEAD,
                     "grade_t": _grade_t(_grade(orc))})
    alive = sorted((r for r in rows if not r["dead"]),
                   key=lambda r: r["orc"].born_at, reverse=True)
    dead = sorted((r for r in rows if r["dead"]),
                  key=lambda r: r["orc"].died_at or now, reverse=True)
    seats = {}
    for orc in orcs:
        seat = orc.seat
        seats[seat.pk] = {"seat": seat, "level_t": notes.ranks.level_t(
            notes.effective_level(orc)),
            "n": int((seat.stats or {}).get("n") or 0)
            if isinstance(seat.stats, dict) else 0}
    spend = None
    if request.user.is_staff:
        # the AI budget lines (the platform's, every user's): staff only,
        # read here because the Orc package imports nothing of ai_agents
        try:
            from ai_agents.spend import lines_summary
            spend = lines_summary()
        except Exception:  # noqa: BLE001 — an unread ledger is no line
            logger.warning("[orcs] the spend lines could not be read",
                           exc_info=True)
    return render(request, "dashboard/orcs_list.html", {
        "page_id": "orcs", "alive": alive, "dead": dead, "dead_days": PAGE_DEAD_DAYS,
        "seats": sorted(seats.values(), key=lambda s: (
            s["seat"].venue, s["seat"].asset_class, s["seat"].rule_key)),
        "spend": spend, "is_staff": request.user.is_staff,
    })


def _owned(request, trade_id):
    """The viewer's Orc numbered `trade_id` (its root trade), or a
    redirect for a leg's number; Http404 for anything else."""
    from bot_program.orcs.models import Orc, OrcLeg
    orc = (Orc.objects.select_related("seat", "root_trade", "grade")
           .filter(user=request.user, root_trade_id=trade_id).first())
    if orc is not None:
        return orc, None
    leg = (OrcLeg.objects.select_related("orc")
           .filter(trade_id=trade_id, orc__user=request.user).first())
    if leg is not None:
        return None, redirect("orc_detail", trade_id=leg.orc.root_trade_id)
    raise Http404(NOT_FOUND)


def _arm_rows(tracks, orc):
    from bot_program.orcs.constants import ARM_ORC
    from bot_program.orcs.ghost import ARM_NAMES, ORDER
    from bot_program.orcs.notes import _px
    rank = {a: i for i, a in enumerate(ORDER)}
    out = []
    for t in sorted(tracks, key=lambda t: rank.get(t.arm, 99)):
        st = t.state if isinstance(t.state, dict) else {}
        stop = st.get("soft_stop") if st.get("soft_stop") is not None \
            else st.get("venue_stop") if st.get("venue_stop") is not None \
            else st.get("soft")
        path = []
        if t.arm == ARM_ORC:
            for p in (st.get("path") or [])[-10:]:
                if isinstance(p, (list, tuple)) and len(p) >= 3:
                    path.append({"at": p[0], "soft": _px(orc, p[1])
                                 if p[1] is not None else "—",
                                 "stop": _px(orc, p[2])
                                 if p[2] is not None else "—"})
        out.append({"name": ARM_NAMES.get(t.arm, t.arm), "open": t.open,
                    "stop_t": _px(orc, stop) if stop is not None else "—",
                    "exit_t": (_px(orc, t.exit_price)
                               if t.exit_price is not None else ""),
                    "exit_r_t": _r(t.exit_r) if not t.open else "",
                    "why": t.exit_why, "capped": t.tail_capped,
                    "path": path})
    return out


@_while_on
@login_required
def orc_detail(request, trade_id):
    """One Orc: its thesis (the entry's, or reconstructed, and the
    operator's beside it) with its predicates, the plan, the journal (facts
    and notes drawn apart), the intents, the arms, the wakes and the
    grade."""
    from bot_program.orcs import notes
    from bot_program.orcs.constants import (ARM_CARE, ARM_ORC,
                                            PAGE_JOURNAL_MAX, PAGE_WAKES_MAX,
                                            STATE_DEAD, THESIS_OPERATOR_MAX)
    from bot_program.orcs.models import OrcJournal, OrcWake

    orc, moved = _owned(request, trade_id)
    if moved is not None:
        return moved
    now = timezone.now()
    tracks = _tracks([orc.pk]).get(orc.pk, [])
    pair = [t for t in tracks if t.arm in (ARM_CARE, ARM_ORC)]
    sl = notes.slot(orc, trade=orc.root_trade, tracks=pair, now=now)
    entries = [{"at": e.at, "kind": e.kind, "author": e.author,
                "fact_id": e.fact_id, "t": e.headline,
                "style": AUTHOR_STYLE.get(e.author, "fact")}
               for e in (OrcJournal.objects.filter(orc=orc)
                         .order_by("-at", "-id")[:PAGE_JOURNAL_MAX])]
    wakes = list(OrcWake.objects.filter(orc=orc)
                 .order_by("-created_at", "-id")[:PAGE_WAKES_MAX])
    th = orc.thesis if isinstance(orc.thesis, dict) else {}
    rec = th.get("reconstructed_from") if isinstance(
        th.get("reconstructed_from"), dict) else None
    mine = (orc.card or {}).get("thesis_operator") if isinstance(
        orc.card, dict) else None
    mine = mine if isinstance(mine, dict) and mine.get("t") else None
    return render(request, "dashboard/orc_detail.html", {
        "page_id": "orcs", "orc": orc,
        "slot": sl, "thesis": th, "reconstructed": rec,
        "source_t": notes.SOURCE_WORDS.get(th.get("source") or "entry",
                                           notes.SOURCE_WORDS["entry"]),
        "mine": mine,
        "mine_at": notes._when(mine.get("at")) if mine else None,
        "can_write": orc.state != STATE_DEAD,
        "thesis_form": THESIS_FORM, "thesis_max": THESIS_OPERATOR_MAX,
        "journal": entries, "intents_none": NO_INTENTS,
        "arms": _arm_rows(tracks, orc), "wakes": wakes,
        "grade": _grade(orc), "grade_t": _grade_t(_grade(orc)),
    })


@_while_on
@login_required
@require_POST
def orc_thesis(request, trade_id):
    """POST — the operator's own thesis, kept beside the entry's (a journal
    entry of kind `thesis`, author `operator`, no fact id). Refused while
    the orcs switch is OFF (a 404, and read again here before the write),
    on an ended idea, empty or repeated."""
    from bot_program.orcs import journal
    from bot_program.orcs.constants import STATE_DEAD, THESIS_OPERATOR_MAX
    from bot_program.orcs.switches import orcs_on

    orc, moved = _owned(request, trade_id)
    if moved is not None:
        return moved
    back = redirect("orc_detail", trade_id=orc.root_trade_id)
    if not orcs_on():
        messages.error(request, THESIS_OFF)
        return back
    if orc.state == STATE_DEAD:
        messages.error(request, THESIS_ENDED)
        return back
    text = " ".join(str(request.POST.get("thesis") or "").split())
    text = text[:THESIS_OPERATOR_MAX]
    if not text:
        messages.error(request, THESIS_EMPTY)
        return back
    mine = (orc.card or {}).get("thesis_operator") if isinstance(
        orc.card, dict) else None
    if isinstance(mine, dict) and mine.get("t") == text:
        messages.info(request, THESIS_SAME)
        return back
    journal.append(orc, "thesis", "Your thesis: " + text[:160],
                   author="operator",
                   body={"thesis": {"source": "operator", "text": text}})
    messages.success(request, THESIS_SAVED)
    return back


def _mean(xs):
    xs = [float(x) for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _venue(g) -> str:
    seat = getattr(g.orc, "seat", None)
    return str(getattr(seat, "venue", "") or "—")


@_while_on
@staff_member_required
def orcs_seats(request):
    """Every seat (venue, class, rule key) by bar source, never pooled: its
    level, the graded ideas, the Δ against the care with its 80% bounds
    (tribunal.block_stats) and the capture means; and per army type, venue,
    class and bar source (§6.4: venues and bar sources are never pooled)
    the counted n, the mean Δ and its 80% bounds. Only the grades that
    count for their seat enter a statistic. Two queries."""
    from bot_program.orcs import ranks
    from bot_program.orcs.army import name_of
    from bot_program.orcs.models import OrcGrade, OrcSeat
    from bot_program.orcs.tribunal import block_stats

    seats = list(OrcSeat.objects.order_by("venue", "asset_class",
                                          "rule_key"))
    grades = list(OrcGrade.objects.select_related("orc", "orc__seat"))
    groups = {}
    for g in grades:
        seat = g.orc.seat
        key = (seat.pk, g.bar_source or "—")
        groups.setdefault(key, []).append(g)
    rows = []
    for seat in seats:
        sources = sorted({k[1] for k in groups if k[0] == seat.pk}) or ["—"]
        for src in sources:
            gs = groups.get((seat.pk, src), [])
            st = block_stats([g.delta_care for g in gs
                              if g.counts_for_seat])
            rows.append({
                "seat": seat, "source": src,
                "level_t": ranks.level_t(seat.level),
                "graded": len(gs), "n": st["n"],
                "mean": _r(st["mean"]), "se": ("—" if st["se"] is None
                                               else f"{st['se']:.2f}R"),
                "lb80": _r(st["lb80"]), "ub80": _r(st["ub80"]),
                "cap_orc": _mean(g.capture_orc for g in gs),
                "cap_ghost": _mean(g.capture_ghost for g in gs)})
    armies = {}
    for g in grades:
        key = (g.army_type or "—", _venue(g), g.orc.asset_class,
               g.bar_source or "—")
        armies.setdefault(key, []).append(g)
    army_rows = []
    for (t, venue, cls, src), gs in sorted(armies.items()):
        st = block_stats([g.delta_care for g in gs if g.counts_for_seat])
        army_rows.append({
            "type_t": name_of(t) if t != "—" else "—", "venue": venue,
            "cls": cls, "source": src, "graded": len(gs), "n": st["n"],
            "delta": _r(st["mean"]), "lb80": _r(st["lb80"]),
            "ub80": _r(st["ub80"]), "vs_line": "—"})
    return render(request, "dashboard/orcs_seats.html", {
        "page_id": "orcs", "rows": rows, "army_rows": army_rows,
        "note": SEATS_NOTE,
    })
