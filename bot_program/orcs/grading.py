"""THE GRADE (spec §6.3-6.4): one per dead idea, against the mechanical care,
forward-only, once every arm has resolved.

  orc_r_gross    the O arm: the real row while no hand acted, its shadow
                 after (§6.4); priced by the one pricing function
  ghost_r        the care ghost; play_r the playbook arm; policy_r the
                 multi-ghost (chandelier3, staged), live evidence for task #81
  actual_r       the booked P&L over the frozen R (money reporting only;
                 never in a delta)
  r_avail        the O arm's best closing-side R over [entry, the last arm's
                 exit]; capture_x = R_x / r_avail only from 0.5R
  delta_care     orc_r_gross - ghost_r: the unit of every seat test
  net_edge_money (O - G) x R$ - the AI cost (0 in O1; from O2a the
                 idea's decision and error entries, in the Orc's currency)
  orc_r          orc_r_gross - the AI cost in R
  the mind       (O2a, A.58) n_wakes, n_llm (done, refused, late),
                 n_actions (simulated proposals), n_refused (refusal
                 entries), the expectation hit rate, the flip-flop rate;
                 tags s:, schema:, rung: and invalid:<rate>, so grades
                 under different minds are never pooled, and arm:would
                 when the O arm was the Orc's proposals in shadow (its
                 would mode): every surface then names it so
  bar_source     "etoro" only when the menu at birth and every bar the arms
                 read were the venue's own; "platform" otherwise: never
                 pooled
  counts_for_seat  O and G resolved, an R, no late seed, and a FAITHFUL
                 care ghost (its soft stop never left the care's on a tick
                 the O arm recorded): computed, used by no seat in O1.
                 The care's own soft stop never carries an Orc level
                 (§3.3), so a mismatch means the ghost is no reference,
                 in every PR. A missed tick is a flag, never an exclusion
                 (§6.4 names none).
  level_at_birth the seat's level frozen at the birth (Orc.seen), not the
                 seat's level at grading time

No idea is excluded by its outcome, nor by the operator's hand (flagged
hand_touched). The grade never touches OrcSeat: seats are computed in O2,
in shadow. The grade's journal line carries R only.
"""
import logging
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from bot_program.orcs.constants import (ARM_CARE, ARM_ORC, ARM_PLAYBOOK,
                                        CAPTURE_MIN_AVAIL_R, FELL_FAULT,
                                        FELL_HONOURABLE, FELL_WON,
                                        MULTI_GHOST_POLICIES, SEED_LATE,
                                        STATE_DEAD)

logger = logging.getLogger(__name__)

FELL_WORDS = {FELL_WON: "Won.", FELL_HONOURABLE: "Honourable defeat."}
#: The O arm in the grade's words (A.58): the position while the arm only
#: recorded the row; the Orc's shadow arm once its proposals stepped it
#: (its would mode, A.43). The grade keeps which as a tag (OrcGrade has no
#: column for it), so the Orc page and Telegram say what its journal line
#: says (2026-11-05, completing O2a).
ARM_POSITION_T = "the position"
ARM_WOULD_T = "the Orc's shadow arm"
WOULD_TAG = "arm:would"


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def numbers(*, exits, r_money, pnl=None, r_avail=None, ai_cost=0.0) -> dict:
    """The grade's numbers, pure. `exits`: {arm: exit R or None}."""
    o, g = _f(exits.get(ARM_ORC)), _f(exits.get(ARM_CARE))
    p = _f(exits.get(ARM_PLAYBOOK))
    rm = _f(r_money)
    out = {"orc_r_gross": o, "ghost_r": g, "play_r": p,
           "policy_r": {k: _f(exits.get(k)) for k in MULTI_GHOST_POLICIES},
           "actual_r": None, "r_avail": _f(r_avail), "capture_orc": None,
           "capture_ghost": None, "capture_play": None, "delta_care": None,
           "delta_play": None, "net_edge_money": None, "orc_r": None}
    if not rm or rm <= 0:
        # no R, no numbers: an idea without a stop is never graded in R
        return {k: (v if k == "policy_r" else None) for k, v in out.items()}
    if _f(pnl) is not None:
        out["actual_r"] = _f(pnl) / rm
    avail = out["r_avail"]
    if avail is not None and avail >= CAPTURE_MIN_AVAIL_R:
        for key, r in (("capture_orc", o), ("capture_ghost", g),
                       ("capture_play", p)):
            out[key] = None if r is None else r / avail
    if o is not None and g is not None:
        out["delta_care"] = o - g
        out["net_edge_money"] = (o - g) * rm - float(ai_cost or 0.0)
    if o is not None and p is not None:
        out["delta_play"] = o - p
    if o is not None:
        out["orc_r"] = o - float(ai_cost or 0.0) / rm
    return out


def bar_source(orc, tracks) -> str:
    sources = set()
    for t in tracks:
        sources.update((t.state or {}).get("bar_sources") or [])
    menu = str((orc.seen or {}).get("menu_source") or "")
    if menu == "etoro" and sources <= {"etoro"}:
        return "etoro"
    return "platform"


def _rr(x) -> str:
    return "—" if x is None else f"{x:+.2f}R"


def grade_line(nums, verdict, *, would=False) -> str:
    """The grade in one line, in R (A.58): "Graded in shadow: ...". The O
    arm is "the position" while it only recorded the row, and "the Orc's
    shadow arm" once its proposals stepped it (its would mode)."""
    tail = (f"Fault: {verdict.causes[0]}." if verdict.fell == FELL_FAULT
            else FELL_WORDS.get(verdict.fell, "Not classed: no R."))
    arm = ARM_WOULD_T if would else ARM_POSITION_T
    return (f"Graded in shadow: {arm} "
            f"{_rr(nums['orc_r_gross'])}, the care ghost "
            f"{_rr(nums['ghost_r'])}, the playbook {_rr(nums['play_r'])}; "
            f"Δ against the care {_rr(nums['delta_care'])}. {tail}")


def graded_would(g) -> bool:
    """The grade `g` measured the Orc's shadow arm in would mode (its tag
    WOULD_TAG): the surfaces then name the O arm ARM_WOULD_T."""
    tags = getattr(g, "tags", None)
    return isinstance(tags, (list, tuple)) and WOULD_TAG in tags


def _usd_per(ccy):
    """USD for one unit of `ccy`, from the freshest quote or 1h/4h bar of
    its USD pair (direct, else inverse); 1.0 for USD; None unread. A read
    of market data only: the order path's own helper is not reached."""
    from datetime import timedelta

    from market_data.models import LiveQuote, PriceData
    ccy = str(ccy or "").upper()
    if ccy in ("", "USD"):
        return 1.0
    now = timezone.now()

    def quote(symbol):
        q = LiveQuote.objects.filter(instrument__symbol=symbol).first()
        if q is not None and q.last and (now - q.updated_at) <= timedelta(
                minutes=15):
            return float(q.last)
        bar = (PriceData.objects
               .filter(instrument__symbol=symbol, timeframe__in=("1h", "4h"),
                       timestamp__gte=now - timedelta(hours=6))
               .order_by("-timestamp").first())
        return float(bar.close) if bar is not None else None
    try:
        direct = quote(f"{ccy}USD")
        if direct and direct > 0:
            return direct
        inverse = quote(f"USD{ccy}")
        if inverse and inverse > 0:
            return 1.0 / inverse
    except Exception:  # noqa: BLE001 — unread is no rate
        return None
    return None


def mind_counts(orc) -> dict:
    """A.58's counters of the idea's mind, from its wakes, intents and
    journal: n_wakes, n_llm, n_actions, n_refused, the invalid-output
    rate, the expectation hit rate, the flip-flop rate, the AI cost in USD
    and the minds' versions."""
    from bot_program.orcs.constants import MODEL_ANSWERED
    from bot_program.orcs.models import OrcIntent, OrcJournal, OrcWake
    wakes = list(OrcWake.objects.filter(orc=orc).values_list("status",
                                                             flat=True))
    n_llm = sum(1 for st in wakes if st in MODEL_ANSWERED)
    refused_wakes = sum(1 for st in wakes if st == "refused")
    entries = list(OrcJournal.objects.filter(
        orc=orc, kind__in=("decision", "error", "refusal", "plan", "fact"))
        .order_by("at", "id").only("kind", "body", "cost_usd"))
    cost = sum((e.cost_usd or Decimal(0)) for e in entries
               if e.kind in ("decision", "error"))
    graded = [e.body.get("result") for e in entries if e.kind == "fact"
              and isinstance(e.body, dict)
              and e.body.get("fk") == "expectation"]
    plans = [tuple(sorted((c.get("clause"), c.get("level_id"),
                           c.get("price"))
                          for c in ((e.body or {}).get("plan") or {})
                          .get("clauses") or [] if isinstance(c, dict)))
             for e in entries if e.kind == "plan"]
    flips = sum(1 for i in range(2, len(plans)) if plans[i] == plans[i - 2])
    versions = {"s": set(), "schema": set(), "rung": set()}
    for e in entries:
        if e.kind == "decision" and isinstance(e.body, dict):
            for key, field in (("s", "s_version"),
                               ("schema", "schema_version"),
                               ("rung", "rung")):
                if e.body.get(field):
                    versions[key].add(str(e.body[field]))
    return {"n_wakes": len(wakes), "n_llm": n_llm,
            "n_actions": OrcIntent.objects.filter(
                orc=orc, status="simulated").count(),
            "n_refused": sum(1 for e in entries if e.kind == "refusal"),
            "invalid": (refused_wakes / n_llm) if n_llm else None,
            "expectation_hit_rate": ((graded.count("hit") / len(graded))
                                     if graded else None),
            "flipflop_rate": (flips / len(plans)) if plans else None,
            "ai_cost_usd": Decimal(cost), "versions": versions}


def mind_tags(counts) -> list:
    """The grade's tags (A.58): s:, schema:, rung: of every decision, and
    invalid:<rate> once a model answered."""
    tags = []
    for key in ("s", "schema", "rung"):
        tags += [f"{key}:{v}" for v in sorted(counts["versions"][key])]
    if counts.get("invalid") is not None:
        tags.append(f"invalid:{counts['invalid']:.2f}")
    return tags


def _level_at_birth(orc) -> int:
    """The seat's level when the idea was born (birth froze it in
    Orc.seen); an Orc born before that memory existed reads its seat
    now (every seat is L0 in O1)."""
    seen = orc.seen if isinstance(orc.seen, dict) else {}
    if seen.get("level_at_birth") is not None:
        return int(seen["level_at_birth"])
    return int(getattr(orc.seat, "level", 0) or 0)


def _first_divergence(o_state) -> str:
    fd = (o_state or {}).get("first_divergence")
    return str(fd.get("kind") or "") if isinstance(fd, dict) else ""


def grade(orc, *, now=None):
    """The idea's one grade, once every arm resolved; None before. A second
    call returns the grade already written. Never touches OrcSeat."""
    from bot_program.models import AssetBotTrade
    from bot_program.orcs import journal, tribunal
    from bot_program.orcs.models import OrcGrade, OrcTrack
    now = now or timezone.now()
    if orc.state != STATE_DEAD:
        return None
    done = OrcGrade.objects.filter(orc=orc).first()
    if done is not None:
        return done
    tracks = list(OrcTrack.objects.filter(orc=orc))
    if not tracks or any(t.open for t in tracks):
        return None
    by = {t.arm: t for t in tracks}
    o = by.get(ARM_ORC)
    o_state = (o.state or {}) if o else {}
    would = o_state.get("mode") == "would"
    row = AssetBotTrade.objects.filter(pk=orc.root_trade_id).first()
    # A.58: the mind's counters and its AI cost, in the Orc's currency;
    # with no rate the money figures stay unknown, never priced at 1
    mind = mind_counts(orc)
    tags = mind_tags(mind) + ([WOULD_TAG] if would else [])
    ai_cost = float(mind["ai_cost_usd"])
    if ai_cost:
        per = _usd_per(orc.ccy)
        if per:
            ai_cost = ai_cost / per
        else:
            ai_cost = None
            tags.append("ai_cost_unconverted")
    nums = numbers(exits={a: t.exit_r for a, t in by.items()},
                   r_money=orc.r_money,
                   pnl=getattr(row, "pnl", None),
                   r_avail=o_state.get("best_m_r"),
                   ai_cost=ai_cost or 0.0)
    if ai_cost is None:
        nums["orc_r"] = nums["net_edge_money"] = None
    first = _first_divergence(o_state)
    verdict = tribunal.classify(tribunal.IdeaFacts(
        orc_r_gross=nums["orc_r_gross"], ghost_r=nums["ghost_r"],
        delta_care=nums["delta_care"], first_divergence=first,
        breaches=0, signpost_unacted=False, exit_available=False))
    seeds = {a: (by[a].state or {}).get("seed") for a in (ARM_ORC, ARM_CARE)
             if a in by}
    late = SEED_LATE in seeds.values()
    missed = sum(int((by[a].state or {}).get("ticks_missed") or 0)
                 for a in (ARM_ORC, ARM_CARE) if a in by)
    faith = o_state.get("faith") if isinstance(o_state.get("faith"),
                                               dict) else {}
    unfaithful = int(faith.get("soft_mismatch") or 0)
    o_exit = o_state.get("exit") or {}
    capped = [t.arm for t in tracks if t.tail_capped]
    source = bar_source(orc, tracks)
    counts = bool(nums["orc_r_gross"] is not None
                  and nums["ghost_r"] is not None
                  and orc.r_money is not None and not late
                  and not unfaithful)
    flags = {"inferred_exit": bool(o_exit.get("inferred")),
             "tail_capped": capped, "late_seed": late,
             "ticks_missed": missed, "soft_mismatch": unfaithful,
             "hand_touched": bool(orc.hand_touched),
             "bar_source": source, "real_exit": o_exit.get("kind") or ""}
    from bot_program.scorecard import exit_of
    try:
        label = exit_of(row) if row is not None else ""
    except Exception:  # noqa: BLE001
        label = ""
    try:
        with transaction.atomic():
            g, created = OrcGrade.objects.get_or_create(orc=orc, defaults={
                "r_money": orc.r_money,
                "ai_cost_usd": mind["ai_cost_usd"],
                "orc_r": nums["orc_r"], "orc_r_gross": nums["orc_r_gross"],
                "ghost_r": nums["ghost_r"], "play_r": nums["play_r"],
                "actual_r": nums["actual_r"], "r_avail": nums["r_avail"],
                "capture_orc": nums["capture_orc"],
                "capture_ghost": nums["capture_ghost"],
                "capture_play": nums["capture_play"],
                "delta_care": nums["delta_care"],
                "delta_play": nums["delta_play"],
                "net_edge_money": (Decimal(str(round(nums["net_edge_money"],
                                                     4)))
                                   if nums["net_edge_money"] is not None
                                   else None),
                "level_at_birth": _level_at_birth(orc),
                "venue": str(orc.seat.venue or "")[:8],
                "counts_for_seat": counts, "bar_source": source,
                "hand_touched": bool(orc.hand_touched),
                "exit_label": str(label)[:80],
                "policy_r": nums["policy_r"], "tags": tags,
                "n_wakes": mind["n_wakes"], "n_llm": mind["n_llm"],
                "n_actions": mind["n_actions"],
                "n_refused": mind["n_refused"],
                "expectation_hit_rate": mind["expectation_hit_rate"],
                "flipflop_rate": mind["flipflop_rate"],
                "fell": verdict.fell, "sub_label": verdict.sub_label,
                "army_type": str(orc.army_type or "")[:16],
                "first_divergence": first[:8], "graded_at": now})
            if created:
                journal.append(orc, "grade", grade_line(
                    nums, verdict, would=would),
                               body={**{k: v for k, v in nums.items()
                                        if k != "net_edge_money"},
                                     "fell": verdict.fell,
                                     "sub_label": verdict.sub_label,
                                     "causes": list(verdict.causes),
                                     "counts_for_seat": counts,
                                     "flags": flags})
    except IntegrityError:
        g = OrcGrade.objects.filter(orc=orc).first()
    return g


# ── the faithfulness audit (§6.1) ────────────────────────────────────────

def shadow_audit(*, days=7, journal=False, now=None) -> list:
    """Every idea that died in the last `days` days: the care ghost against
    the care, in words. With `journal`, each idea's line is a fact on its
    own journal, once."""
    from datetime import timedelta

    from bot_program.orcs import ghost
    from bot_program.orcs import journal as orc_journal
    from bot_program.orcs.models import Orc
    now = now or timezone.now()
    since = now - timedelta(days=int(days))
    orcs = list(Orc.objects.filter(state=STATE_DEAD, died_at__gte=since)
                .order_by("root_trade_id"))
    lines = [f"Shadow audit · last {int(days)} days · {len(orcs)} idea(s) "
             f"checked"]
    for orc in orcs:
        try:
            f = ghost.faithfulness(orc)
            text = ghost.faith_line(f)
            lines.append(f"  Orc #{orc.root_trade_id} {orc.symbol}: {text}")
            if journal and (orc.seen or {}).get("audited") != text:
                orc_journal.append(orc, "fact", text,
                                   body={"faithfulness": f}, fact=True,
                                   remember={"audited": text})
        except Exception as e:  # noqa: BLE001 — one idea never stops it
            logger.warning("[orcs] audit of Orc %s failed: %s", orc.pk, e)
            lines.append(f"  Orc #{orc.root_trade_id} {orc.symbol}: not "
                         f"read ({type(e).__name__})")
    return lines
