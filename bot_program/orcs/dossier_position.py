"""PS, THE POSITION (spec §5.2a "PS: the position"), one Orc's, per wake,
uncached, from code. Every figure in R from the frozen risk (§1.2); no
money anywhere; a model's words (the debate's killer and edge, the
reviewer's reasoning) only as views, labelled "may be wrong; facts win".

  PS1  you: L0 shadow, the commission, the allowed actions and why not,
       the army type (never a rank)
  PS2  the thesis and its provenance (money-free, thesis.provenance)
  PS3  "no plan yet: the Orc writes one from O2"
  PS4  the mandate: worst case, gross, loss, adds and re-entry left, the
       book's headroom in R
  PS5  the journal digest: the last 12 facts since birth with their ids
  PS6  the care: its stops, peak and worst, the scale-out, the venue's
       stop and any refusal, the last 10 stop moves, Aragorn's actions
  PS7  the reviewer's verdicts of 24 h, the reasoning as a view
  PS8  the war drums heard since the last wake
  PS9-PS11  dashes until O2
  PS12 (tail) the menu, the candidates (unordered, after the F5 shrink),
       the recovery odds while under water (continuation odds: O2)
  PS13 (tail) the integrity verdict
"""
import logging
from datetime import timedelta

from bot_program.orcs import fence
from bot_program.orcs.constants import FENCE_CAPS, MAX_ADDS, MAX_REENTRIES

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
    return {"level": "L0 shadow", "commission": str(orc.commission or ""),
            "allowed_actions": list(ctx.get("allowed") or ["hold"]),
            "why_not": list(ctx.get("why_not") or []),
            "army": name_of(orc.army_type) + (" + Corsairs" if overlay
                                              else "")}


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
            "killer": (fence.view("debate", ex.get("killer"), 200)
                       if ex.get("killer") else "—"),
            "edge": (fence.view("debate", ch.get("edge"), 200)
                     if ch.get("edge") else "—"),
            "operator": "— (no thesis typed by the operator)"}


def _ps4(orc, row, ctx) -> dict:
    from bot_program.orcs.facts import r_at
    eff = ctx.get("effective")
    wc = r_at(row, eff) if eff is not None else -1.0
    book = None
    try:
        from bot_program.orcs import sources
        book = sources.book(orc.user, real=bool(ctx.get("real")),
                            cache=ctx.get("cache"))
    except Exception:  # noqa: BLE001
        book = None
    headroom = "— (book unreadable)"
    if book and not book.get("dash"):
        limit = _f(book.get("_limit"))
        share = _f(book["value"].get("open_risk_share"))
        r_money = _f(orc.r_money)
        if limit and share is not None and r_money:
            headroom = _r(limit * (1.0 - share) / r_money)
        else:
            headroom = "— (no open-risk limit measured)"
    return {"wc": _r(wc), "gross": _r(0.0), "loss": _r(0.0),
            "adds_left": max(0, MAX_ADDS - int(orc.adds_used or 0)),
            "reentry_left": max(0, MAX_REENTRIES -
                                int(orc.reentries_used or 0)),
            "book_headroom": headroom}


def _ps5(orc) -> dict:
    from bot_program.orcs.models import OrcJournal
    rows = list(OrcJournal.objects.filter(orc_id=orc.pk)
                .exclude(fact_id="").order_by("-at", "-id")[:PS5_FACTS])
    rows.reverse()
    return {"facts": [{"id": e.fact_id, "kind": fence.fact_kind(e),
                       "at": f"{e.at:%m-%d %H:%M}",
                       "t": fence.sanitize(e.headline, 200)} for e in rows]
            or "—", "notes": []}


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
            moves.append({"at": str(m.get("at") or "")[:16],
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
        out = [{"at": f"{r.created_at:%m-%d %H:%M}", "verdict": r.verdict,
                "reasoning": fence.view("reviewer", r.reasoning_md,
                                        FENCE_CAPS["reviewer"])}
               for r in rows]
        return out or "— (no review in 24 h)"
    except Exception as e:  # noqa: BLE001
        return f"— (reviews unread: {type(e).__name__})"


def _ps8(orc) -> object:
    from bot_program.orcs.models import OrcJournal
    since = (orc.seen or {}).get("last_recorded")
    qs = OrcJournal.objects.filter(orc_id=orc.pk, kind="drum")
    if since:
        qs = qs.filter(at__gt=since)
    rows = list(qs.order_by("-at", "-id")[:5])
    rows.reverse()
    return [{"id": e.fact_id, "t": fence.sanitize(e.headline, 200)}
            for e in rows] or "— (no drum heard since the last wake)"


def ps(orc, row, ctx) -> dict:
    """PS's sections (PS1-PS11)."""
    now = ctx.get("now")
    out = {"ps1": _ps1(orc, ctx), "ps2": _ps2(orc, row), "ps3": PS3_WORDS,
           "ps4": _ps4(orc, row, ctx), "ps5": _ps5(orc),
           "ps6": _ps6(orc, row, ctx),
           "ps7": {"reviews": _ps7(row, now),
                   "thesis_check": _thesis_check(row)},
           "ps8": _ps8(orc)}
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


def ps12(ctx, row=None) -> dict:
    """The tail's menu, candidates (sorted by id, never ranked) and odds."""
    menu_rows = []
    for r in (ctx.get("rows") or [])[:30]:
        menu_rows.append({"id": r.get("id"), "kind": r.get("kind"),
                          "tf": r.get("tf") or "",
                          "r_away": (f"{r['r_away']:+.2f}"
                                     if r.get("r_away") is not None else "—"),
                          "atr_away": (f"{r['atr_away']:+.2f}"
                                       if r.get("atr_away") is not None
                                       else "—")})
    cands = []
    for c in ctx.get("candidates") or []:
        cands.append({"id": getattr(c, "id", ""),
                      "action": getattr(c, "action", ""),
                      "levels": list(getattr(c, "level_ids", ()) or ())})
    return {"menu": menu_rows or "— (no menu: no fresh venue frame)",
            "candidates": sorted(cands, key=lambda c: c["id"]) or "—",
            # O2: continuation_odds (backtester/proving/memory.py, §5.2)
            "odds": {"continuation": "— (continuation odds arrive with O2)",
                     "recovery": _recovery(ctx, row)}}
