"""PS, THE POSITION (spec §5.2a "PS: the position"), one Orc's, per wake,
uncached, from code. Every figure in R from the frozen risk (§1.2); no
money anywhere; a model's words (the debate's killer and edge, the
reviewer's reasoning) only as views, labelled "may be wrong; facts win",
and only under PR68's plain words (bot_program/orcs/plain.py): kept as
written, or withheld whole when they name an exception or may name an
amount of money, read against the row's own amounts by value. A debate
line is never cut (its view holds plain_words.LINE_MAX, the length the
debate stores).

  PS1  you: L0 shadow, the commission, the allowed actions and why not
       (the officer's, O2a: mandate.allowed_actions), the events a lock
       waiver may name, by code id, the army type (never a rank)
  PS2  the thesis and its provenance (money-free, thesis.provenance), the
       debate's sides, and the operator's own thesis (O1d) as a view: his
       words, never a fact
  PS3  "no plan yet: the Orc writes one from O2"; from O2a, once a model
       answered: the plan drawn by code, its version, and the LAST
       decision's expectation with its result (hit, missed or pending)
  PS4  the mandate: worst case, gross, the realized loss in R, the adds
       left by the army type (less the officer's would-adds), re-entry
       left, the book's headroom in R; from O2a the counters V2 and I12
       read (plan changes left, steps left today, bars since the last
       add and trim)
  PS5  the journal digest: the last 12 facts since birth with their ids,
       the takeover pinned while the care holds the position; from O2a its
       notes: the last decisions and the refusals since the last model
       answer, each a T1 view written through the validator's filter
  PS6  the care: its stops, peak and worst, the scale-out, the venue's
       stop and any refusal, the last 10 stop moves, Aragorn's actions
  PS7  the reviewer's verdicts of 24 h, the reasoning as a view
  PS8  the war drums heard since the last wake
  PS9-PS11  dashes until O2
  PS12 (tail) the menu, each row with its `watch` (O2a: may a plan clause
       watch it, at least PLAN_WATCH_MIN_ATR1H x ATR(1h) from the mark) and
       BE with its cost, the candidates (unordered, after the F5 shrink),
       the recovery odds while under water (continuation odds: later)
  PS13 (tail) the integrity verdict
"""
import logging
from datetime import timedelta

from bot_program.orcs import fence
from bot_program.orcs.constants import (FENCE_CAPS, MAX_REENTRIES,
                                        PS5_DECISIONS)
from bot_program.orcs.plain import row_marks, voice

logger = logging.getLogger(__name__)

PS3_WORDS = "no plan yet: the Orc writes one from O2"
PS5_FACTS = 12
PS6_MOVES = 10


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def _r(x) -> str:
    v = _f(x)
    return f"{v:+.2f}R" if v is not None else "—"


def held_symbols(orc) -> list:
    """The symbols of the user's other living ideas (IN8, MK-now)."""
    try:
        from bot_program.orcs.constants import STATE_DEAD
        from bot_program.orcs.models import Orc
        return sorted(set(Orc.objects.filter(user_id=orc.user_id)
                          .exclude(state=STATE_DEAD)
                          .values_list("symbol", flat=True)))
    except Exception:  # noqa: BLE001
        return [orc.symbol]


def _ps1(orc, ctx) -> dict:
    from bot_program.orcs.army import name_of
    overlay = (orc.army_why or {}).get("overlay") if isinstance(
        orc.army_why, dict) else None
    events = ctx.get("events") if isinstance(ctx.get("events"), dict) else {}
    return {"level": "L0 shadow", "commission": str(orc.commission or ""),
            "allowed_actions": list(ctx.get("allowed") or ["hold"]),
            "why_not": list(ctx.get("why_not") or []),
            "events": [event_words(code, ev) for code, ev in
                       sorted(events.items())] or NO_EVENT,
            "army": name_of(orc.army_type) + (" + Corsairs" if overlay
                                              else "")}


#: PS1 when no print or shut is near (O2a).
NO_EVENT = "— (no print or shut near)"


def event_words(code, ev) -> str:
    """An event by its code id, in fixed words (O2a, A.47): "C3: a USD
    print in 2 h 10 min". Never a calendar title."""
    ev = ev if isinstance(ev, dict) else {}
    mins = max(0, int(round(_f(ev.get("minutes")) or 0)))
    h, m = divmod(mins, 60)
    when = f"{h} h {m} min" if h else f"{m} min"
    if ev.get("kind") == "print":
        ccy = fence.sanitize(ev.get("ccy"), 6) or "a"
        return f"{code}: a {ccy} print in {when}"
    return f"{code}: a market shut in {when}"


def _decisions(orc, ctx, n=1) -> list:
    """The Orc's last `n` decision entries, newest first, read up to the
    re-render's journal_as_of when there is one (A.24)."""
    from bot_program.orcs.models import OrcJournal
    qs = OrcJournal.objects.filter(orc_id=orc.pk, kind="decision")
    upto = (ctx or {}).get("journal_as_of")
    if upto is not None:
        qs = qs.filter(at__lte=upto)
    return list(qs.order_by("-at", "-id")[:n])


def _ps3(orc, ctx):
    """PS3 [P25]: the plan drawn by code, its version, and the expectation
    of the LAST decision with its result. O1's words while no model has
    answered and no plan exists."""
    from bot_program.orcs.notes import plan_line
    last = _decisions(orc, ctx)
    plan = orc.plan if isinstance(orc.plan, dict) else {}
    if not plan and not last:
        return PS3_WORDS
    return {"plan": plan_line(orc), "version": int(orc.plan_version or 0),
            "last_expectation": _last_expectation(orc, last[0] if last
                                                  else None, ctx)}


def _last_expectation(orc, decision, ctx):
    from bot_program.orcs.evidence import expectation_words
    from bot_program.orcs.models import OrcJournal
    body = decision.body if decision is not None and isinstance(
        decision.body, dict) else {}
    exp = body.get("expectation")
    if not isinstance(exp, dict) or exp.get("kind") in (None, "", "none"):
        return "— (none set)"
    qs = OrcJournal.objects.filter(orc_id=orc.pk, kind="fact",
                                   body__fk="expectation",
                                   body__decision=decision.pk)
    upto = (ctx or {}).get("journal_as_of")
    if upto is not None:
        qs = qs.filter(at__lte=upto)
    graded = qs.order_by("-at", "-id").first()
    result = ((graded.body or {}).get("result") if graded is not None
              else "pending")
    return {"set_at": f"{decision.at:%m-%d %H:%M}",
            "words": expectation_words(exp, orc),
            "result": str(result or "pending")}


def _ps2(orc, row) -> dict:
    th = orc.thesis if isinstance(orc.thesis, dict) else {}
    meta = row.metadata if isinstance(row.metadata, dict) else {}
    debate = meta.get("debate") if isinstance(meta.get("debate"),
                                              dict) else {}
    ex = debate.get("executioner") if isinstance(debate.get("executioner"),
                                                 dict) else {}
    ch = debate.get("champion") if isinstance(debate.get("champion"),
                                              dict) else {}
    preds = []
    for p in th.get("invalidation") or []:
        if not isinstance(p, dict):
            continue
        preds.append(":".join(str(p.get(k)) for k in ("kind", "tf",
                                                      "level_id")
                              if p.get(k) not in (None, "")))
    prov = th.get("provenance") if isinstance(th.get("provenance"),
                                              dict) else {}
    return {"source": str(th.get("source") or "—"),
            "reason": fence.sanitize(th.get("reason"), 200) or "—",
            "rule": fence.sanitize(th.get("rule"), 60) or "—",
            "invalidation": preds or "—",
            "provenance": ({fence.sanitize(k, 32): fence.sanitize(v, 80)
                            for k, v in sorted(prov.items())
                            if not isinstance(v, (dict, list))}
                           or "—"),
            "killer": _debate_view(ex.get("killer"), row),
            "edge": _debate_view(ch.get("edge"), row),
            "operator": _operator_view(orc, row)}


#: PS2 when the operator typed no thesis on his Orc's page.
NO_OPERATOR_THESIS = "— (no thesis typed by the operator)"


def _operator_view(orc, row) -> str:
    """The operator's own thesis (O1d: the last one he wrote on
    /orcs/<id>/, kept on the card as `thesis_operator`), as a view under
    source "operator": his words, never a fact (no F-id), whole or
    withheld whole (plain.voice), never cut. The dash when he wrote
    none."""
    card = orc.card if isinstance(orc.card, dict) else {}
    mine = card.get("thesis_operator")
    said = mine.get("t") if isinstance(mine, dict) else None
    if not said:
        return NO_OPERATOR_THESIS
    from bot_program.orcs.constants import THESIS_OPERATOR_MAX
    line = voice(said, row_marks(row))
    return fence.view("operator", line, max(THESIS_OPERATOR_MAX, len(line)))


def _debate_view(said, row) -> str:
    """One side's line as a view: whole, or withheld whole (plain.voice),
    never cut. "—" for none."""
    if not said:
        return "—"
    from dashboard.plain_words import LINE_MAX
    line = voice(said, row_marks(row))
    return fence.view("debate", line, max(LINE_MAX, len(line)))


def _ps4(orc, row, ctx) -> dict:
    """The mandate (§2.1). One leg in O1, so gross_I is the root's own
    max(0, d x (e - s)) in R: +1.00R at its initial stop, +0.00R at
    break-even or beyond; the worst case is the R at the effective stop.
    No stop read: a dash, never -1R (unknown is not zero)."""
    from bot_program.orcs.facts import r_at
    eff = ctx.get("effective")
    at_stop = r_at(row, eff) if eff is not None else None
    book = None
    try:
        from bot_program.orcs import sources
        book = sources.book(orc.user, world=ctx.get("world") or "live",
                            cache=ctx.get("cache"))
    except Exception:  # noqa: BLE001
        book = None
    # a dash says why: unreadable, or a demo world with no book of its own
    headroom = (book or {}).get("dash") or "— (book unreadable)"
    if book and not book.get("dash"):
        limit = _f(book.get("_limit"))
        share = _f(book["value"].get("open_risk_share"))
        r_money = _f(orc.r_money)
        if limit and share is not None and r_money:
            headroom = _r(limit * (1.0 - share) / r_money)
        else:
            headroom = "— (no open-risk limit measured)"
    from bot_program.orcs import mandate
    from bot_program.orcs.sessions import trading_day
    now = ctx.get("now")
    if now is None:
        from django.utils import timezone
        now = timezone.now()
    counters = mandate.ps4(orc, {"decision_bars": ctx.get("decision_bars")},
                           day=trading_day(now), now=now)
    loss = _realized_loss(orc)
    return {"wc": (_r(at_stop) if at_stop is not None
                   else "— (no stop read)"),
            "gross": (_r(max(0.0, -at_stop)) if at_stop is not None
                      else "—"),
            "loss": _r(-loss if loss else 0.0),
            "adds_left": counters["adds_left"],
            "reentry_left": max(0, MAX_REENTRIES -
                                int(orc.reentries_used or 0)),
            "plan_changes_left": counters["plan_changes_left"],
            "steps_left_today": counters["steps_left_today"],
            "bars_since_add": counters["bars_since_add"],
            "bars_since_trim": counters["bars_since_trim"],
            "book_headroom": headroom}


def _realized_loss(orc) -> float:
    """The idea's realized loss in R (A.47, P31.4), as a positive number:
    the O arm's banked negative R, and the real legs that closed in loss.
    0.0 when nothing was lost."""
    from bot_program.orcs import mandate
    try:
        loss = float(mandate.arm_world(orc).get("losses_r") or 0.0)
    except Exception:  # noqa: BLE001 — an unread arm banked nothing
        loss = 0.0
    closed = (orc.seen or {}).get("closed_legs") if isinstance(
        orc.seen, dict) else None
    if closed:
        from bot_program.orcs.models import OrcJournal
        for e in OrcJournal.objects.filter(orc_id=orc.pk, kind="fact",
                                           body__leg__in=list(closed)):
            r = _f((e.body or {}).get("r"))
            if r is not None and r < 0:
                loss += -r
    return loss


def _ps5(orc, ctx=None) -> dict:
    """The last PS5_FACTS facts, read up to the re-render's journal_as_of
    when there is one (A.24), and the takeover pinned while the Orc is
    care_owned, even once it scrolled out of the twelve (A.47)."""
    from bot_program.orcs.constants import STATE_CARE_OWNED
    from bot_program.orcs.models import OrcJournal
    qs = OrcJournal.objects.filter(orc_id=orc.pk).exclude(fact_id="")
    upto = (ctx or {}).get("journal_as_of")
    if upto is not None:
        qs = qs.filter(at__lte=upto)
    rows = list(qs.order_by("-at", "-id")[:PS5_FACTS])
    rows.reverse()
    facts = [{"id": e.fact_id, "kind": fence.fact_kind(e),
              "at": f"{e.at:%m-%d %H:%M}", "t": _headline(e.headline)}
             for e in rows]
    if orc.state == STATE_CARE_OWNED:
        took = qs.filter(kind="takeover").order_by("-at", "-id").first()
        if took is not None and took.fact_id not in {f["id"] for f in facts}:
            facts.insert(0, {"id": took.fact_id, "kind": fence.fact_kind(took),
                             "at": f"{took.at:%m-%d %H:%M}",
                             "t": _headline(took.headline), "pinned": True})
    return {"facts": facts or "—", "notes": []}


def ps5_notes(orc, ctx=None) -> list:
    """PS5's notes (A.47, P26): the last PS5_DECISIONS decisions, each
    {at, action, cited, expectation, outcome}, and every refusal since the
    previous model-answered wake (a wake answered by code writes no
    decision, so it never swallows one). Each a T1 view capped at
    FENCE_CAPS["orc"]; the decision's words passed the validator's filter
    when they were written. [] for none."""
    from bot_program.orcs.evidence import expectation_words
    from bot_program.orcs.models import OrcIntent, OrcJournal
    decisions = _decisions(orc, ctx, PS5_DECISIONS)
    if not decisions:
        return []
    intents = {}
    for it in OrcIntent.objects.filter(decision_id__in=[d.pk for d in
                                                        decisions]):
        intents[it.decision_id] = it.status
    out = []
    for d in reversed(decisions):
        b = d.body if isinstance(d.body, dict) else {}
        ans = b.get("answer") if isinstance(b.get("answer"), dict) else {}
        action = str(ans.get("action") or "—")
        lid = str(ans.get("level_id") or "none")
        cited = ", ".join(str(x) for x in ans.get("facts_cited") or []) \
            or "none"
        if b.get("status") == "refused":
            outcome = f"refused ({b.get('rule') or 'V1'})"
        elif b.get("late"):
            outcome = f"late ({b.get('code') or 'row_closed'})"
        elif d.pk in intents:
            outcome = intents[d.pk]
        else:
            outcome = "hold" if action in ("hold", "—") else "kept"
        text = (f"{d.at:%m-%d %H:%M} {action}"
                f"{'' if lid == 'none' else ' ' + lid}; cited {cited}; "
                f"expects {expectation_words(b.get('expectation'), orc)}; "
                f"outcome {outcome}")
        note = str(ans.get("note") or "")
        if note:
            text += f". Note: {note}"
        out.append(fence.view("orc", text, FENCE_CAPS["orc"]))
    since = decisions[0].at
    qs = OrcJournal.objects.filter(orc_id=orc.pk, kind="refusal",
                                   at__gte=since)
    upto = (ctx or {}).get("journal_as_of")
    if upto is not None:
        qs = qs.filter(at__lte=upto)
    for r in qs.order_by("at", "id"):
        body = r.body if isinstance(r.body, dict) else {}
        out.append(fence.view(
            "orc", f"{r.at:%m-%d %H:%M} refused ({body.get('rule') or '—'}): "
            f"{body.get('words') or ''}", FENCE_CAPS["orc"]))
    return out


def _headline(text) -> str:
    """A journal headline as PS5 and PS8 print it: quarantined (an
    instruction-like line is withheld whole), then sanitized. Code writes
    these lines, so nothing is ever withheld unless third-party text
    reached one."""
    return fence._content(text, 200)[0]


def _ps6(orc, row, ctx) -> dict:
    from bot_program.orcs.facts import px, r_at
    care = ctx.get("care") or {}
    meta = row.metadata if isinstance(row.metadata, dict) else {}

    def lv(x):
        v = _f(x)
        return f"{px(row, v)} ({_r(r_at(row, v))})" if v is not None \
            else "—"
    moves = []
    for m in (meta.get("stop_moves") or [])[-PS6_MOVES:]:
        if isinstance(m, dict):
            # a stop_moves entry keeps the MARK it was made at in "at" and
            # the moment in "when" (asset_engine/base.py, the broker move)
            mark = _f(m.get("at"))
            moves.append({"when": str(m.get("when") or "—")[:16],
                          "mark": px(row, mark) if mark is not None
                          else "—",
                          "to": lv(m.get("to") or m.get("stop")
                                   or m.get("level")),
                          "why": fence.sanitize(m.get("why") or
                                                m.get("reason"), 60)})
    actions = []
    try:
        from bot_program.aragorn_models import AragornAction
        for a in (AragornAction.objects.filter(trade_id=row.pk)
                  .order_by("-at")[:5]):
            actions.append({"at": f"{a.at:%m-%d %H:%M}", "kind": a.kind,
                            "t": fence.sanitize(a.detail, 120)})
    except Exception:  # noqa: BLE001
        actions = "— (Aragorn's actions unread)"
    return {"soft_stop": lv(care.get("soft_stop")),
            "soft_why": fence.sanitize(care.get("soft_why"), 40) or "—",
            "effective": lv(ctx.get("effective")),
            "peak": lv(care.get("peak")), "worst": lv(care.get("worst")),
            "mfe": _r(care.get("mfe_r")), "mae": _r(care.get("mae_r")),
            "now": _r(care.get("r_now")),
            "scaled_out": bool(care.get("scaled_out")),
            "venue_stop": lv(care.get("venue_stop")),
            "venue_refused": ("yes" if care.get("venue_stop_refusal")
                              else "no"),
            "stop_moves": moves or "—", "aragorn": actions or "—"}


def _thesis_check(row) -> object:
    meta = row.metadata if isinstance(row.metadata, dict) else {}
    th = meta.get("thesis") if isinstance(meta.get("thesis"), dict) else {}
    if not th.get("verdict"):
        return "— (no thesis check yet)"
    from bot_program.orcs.facts import px
    stop = th.get("stop")
    return {"verdict": fence.sanitize(th.get("verdict"), 16),
            "stop": px(row, stop) if stop is not None else "—",
            "at": str(th.get("at") or "")[:16]}


def _ps7(row, now) -> object:
    try:
        from brain.position_review_models import PositionReview
        rows = (PositionReview.objects
                .filter(book="bot", position_id=row.pk,
                        created_at__gte=now - timedelta(hours=24),
                        created_at__lte=now)
                .order_by("-created_at")
                .only("verdict", "reasoning_md", "created_at")[:3])
        marks = row_marks(row)
        # the whole reasoning is read before the view caps it, so a figure
        # past the cap still withholds it whole
        out = [{"at": f"{r.created_at:%m-%d %H:%M}", "verdict": r.verdict,
                "reasoning": fence.view(
                    "reviewer", voice(r.reasoning_md, marks, keep_lines=True),
                    FENCE_CAPS["reviewer"])}
               for r in rows]
        return out or "— (no review in 24 h)"
    except Exception as e:  # noqa: BLE001
        return f"— (reviews unread: {type(e).__name__})"


def _ps8(orc, ctx=None) -> object:
    """The drums heard since the wake BEFORE this one (the render reads it
    from the wake the tick recorded; the Orc's memory already names this
    wake as the last)."""
    from bot_program.orcs.models import OrcJournal
    ctx = ctx or {}
    since = (ctx.get("prev_recorded") if "prev_recorded" in ctx
             else (orc.seen or {}).get("last_recorded"))
    qs = OrcJournal.objects.filter(orc_id=orc.pk, kind="drum")
    if since:
        qs = qs.filter(at__gt=since)
    rows = list(qs.order_by("-at", "-id")[:5])
    rows.reverse()
    return [{"id": e.fact_id, "t": _headline(e.headline)}
            for e in rows] or "— (no drum heard since the last wake)"


def ps(orc, row, ctx) -> dict:
    """PS's sections (PS1-PS11)."""
    now = ctx.get("now")
    out = {"ps1": _ps1(orc, ctx), "ps2": _ps2(orc, row),
           "ps3": _ps3(orc, ctx),
           "ps4": _ps4(orc, row, ctx), "ps5": _ps5(orc, ctx),
           "ps6": _ps6(orc, row, ctx),
           "ps7": {"reviews": _ps7(row, now),
                   "thesis_check": _thesis_check(row)},
           "ps8": _ps8(orc, ctx)}
    # O2: PS9 the temperament's lead voices and lane texts (§4.6), PS10
    # the lessons and weapons of the lineage (§6.10-6.11), PS11 the
    # Captain's orders and the Emperor's theme orders (§4.2, §4.6).
    out["ps9"] = "— (the temperament arrives with O2)"
    out["ps10"] = "— (no lesson yet: the lineage's record starts in O2)"
    out["ps11"] = "— (no Captain seated yet)"
    return out


def _recovery(ctx, row) -> object:
    """§5.2's recovery odds (brain/thesis_check.recovery_odds): the proving
    ground's analogs of this rule on this class at least as deep, read only
    while the idea is under water; with no analog, its reason, never a
    number."""
    care = ctx.get("care") or {}
    depth = _f(care.get("mae_r"))
    now_r = _f(care.get("r_now"))
    if now_r is not None and (depth is None or now_r < depth):
        depth = now_r
    if row is None or depth is None or depth >= 0:
        return "— (the position is not under water)"
    try:
        from brain.thesis_check import recovery_odds
        o = recovery_odds(getattr(row, "rule_name", "") or "",
                          getattr(row, "asset_class", "") or "", depth)
    except Exception as e:  # noqa: BLE001
        return f"— (recovery odds unread: {type(e).__name__})"
    if not o.get("ok"):
        return f"— ({fence.sanitize(o.get('why') or 'no analog', 120)})"

    def pct(x):
        v = _f(x)
        return f"{v:.0%}" if v is not None else "—"
    return {"n": int(o.get("n") or 0), "depth": _r(depth),
            "won": pct(o.get("won_pct")), "target": pct(o.get("target_pct")),
            "avg": _r(o.get("avg_r")), "thin": bool(o.get("thin"))}


#: PS12's `watch` (O2a, A.47): may a plan clause watch this level?
WATCH_YES = "yes"
WATCH_NEAR = "no: too near the mark"


def ps12(ctx, row=None) -> dict:
    """The tail's menu, candidates (sorted by id, never ranked) and odds.
    Each menu row says whether a plan clause may watch it (V12, A.48: at
    least PLAN_WATCH_MIN_ATR1H x ATR(1h) from the closing-side mark), and
    BE carries its round trip in R (A.8): the entry plus its cost."""
    from bot_program.orcs.constants import PLAN_WATCH_MIN_ATR1H
    m, atr1h = _f(ctx.get("m")), _f(ctx.get("atr1h"))
    entry, rpu = _f(ctx.get("entry")), _f(ctx.get("rpu"))
    menu_rows = []
    for r in (ctx.get("rows") or [])[:30]:
        price = _f(r.get("price"))
        near = not (price is not None and m is not None and atr1h
                    and abs(price - m) >= PLAN_WATCH_MIN_ATR1H * atr1h)
        item = {"id": r.get("id"), "kind": r.get("kind"),
                "tf": r.get("tf") or "",
                "r_away": (f"{r['r_away']:+.2f}"
                           if r.get("r_away") is not None else "—"),
                "atr_away": (f"{r['atr_away']:+.2f}"
                             if r.get("atr_away") is not None else "—"),
                "watch": WATCH_NEAR if near else WATCH_YES}
        if r.get("id") == "BE" and price is not None and entry and rpu:
            item["cost"] = f"{abs(price - entry) / rpu:+.2f}R"
        menu_rows.append(item)
    cands = []
    for c in ctx.get("candidates") or []:
        cands.append({"id": getattr(c, "id", ""),
                      "action": getattr(c, "action", ""),
                      "levels": list(getattr(c, "level_ids", ()) or ())})
    return {"menu": menu_rows or "— (no menu: no fresh venue frame)",
            "candidates": sorted(cands, key=lambda c: c["id"]) or "—",
            # Later: continuation_odds (backtester/proving/memory.py,
            # §5.2): no reader exists yet; it stays a dash through O2
            "odds": {"continuation": "— (continuation odds arrive with O2)",
                     "recovery": _recovery(ctx, row)}}
