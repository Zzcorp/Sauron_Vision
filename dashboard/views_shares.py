"""The share allocator's page — /shares/.

What share of the broker account each live follower pool takes today,
what the allocator proposes it should take, and why — one sentence per
config with every factor in it. The decisions (apply behind the PIN,
reject, rollback) are POST views in views_admin_hq; this page only
reads. Every read is fenced: a page that 500s because the brain context
or the drawdown history is unreadable hides the pending plan an
operator came to decide on, and a hidden plan expires undecided
(2026-09-12).

Nothing here talks to the broker. The reading is the sync's last stored
one and its AGE is shown beside it, so a stale number is never dressed
as current.
"""
import logging

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

logger = logging.getLogger(__name__)


def _age_text(seconds) -> str:
    """'3m' / '2.4h' — the reading's age, for the KPI cell."""
    s = int(seconds or 0)
    if s < 3600:
        return f"{s // 60}m"
    return f"{s / 3600:.1f}h"


@login_required
def shares_dashboard(request):
    from bot_program.share_models import SharePlan

    user = request.user

    # ── the account: reading, drawdown, governor ─────────────────────
    reading, drawdown, governor = None, None, None
    reading_stale = False
    try:
        from bot_program.capital_truth import (TRACKING_FRESH_SECONDS,
                                               account_equity)
        reading = account_equity(user)
        if reading is not None:
            reading["age_text"] = _age_text(reading["age_seconds"])
            reading_stale = reading["age_seconds"] > TRACKING_FRESH_SECONDS
    except Exception as e:  # noqa: BLE001 — the page renders regardless
        logger.warning("[shares page] reading unreadable: %s", e)
    try:
        from bot_program.capital_truth import equity_drawdown
        from bot_program.share_allocator import governor_for
        drawdown = equity_drawdown(user)
        if drawdown is not None:
            drawdown["pct_text"] = f"{float(drawdown['drawdown_pct']) * 100:.1f}%"
            governor = governor_for(drawdown["drawdown_pct"])
    except Exception as e:  # noqa: BLE001
        logger.warning("[shares page] drawdown unreadable: %s", e)

    # ── the followers and their current shares ───────────────────────
    followers, plan_now, alloc_reason = [], {}, ""
    try:
        from bot_program.capital_truth import allocate_shares, followers_of
        followers = followers_of(user)
        alloc = allocate_shares(followers)
        plan_now = alloc["plan"] if alloc["ok"] else {}
        alloc_reason = "" if alloc["ok"] else alloc["reason"]
    except Exception as e:  # noqa: BLE001
        logger.warning("[shares page] followers unreadable: %s", e)

    # ── the plans ────────────────────────────────────────────────────
    plans = SharePlan.objects.filter(user=user)
    plan = (plans.filter(state=SharePlan.STATE_PROPOSED)
            .order_by("-proposed_at").first())
    pending = list(plans.filter(state=SharePlan.STATE_PROPOSED)
                   .order_by("-proposed_at"))
    applied = list(plans.filter(state=SharePlan.STATE_APPLIED)
                   .select_related("confirmed_by").order_by("-applied_at"))
    history = list(plans.exclude(state=SharePlan.STATE_PROPOSED)
                   .select_related("confirmed_by").order_by("-proposed_at")[:20])
    for p in pending + applied + history:
        p.rows = _plan_rows(p)

    # ── current vs target, one row per follower ──────────────────────
    rows = []
    inputs = (plan.inputs or {}) if plan is not None else {}
    for cfg in followers:
        row = {"cfg": cfg, "current": "—", "current_pct": None,
               "target": None, "floor": None, "ceiling": None,
               "delta": None, "why": "", "held": False, "lane": ""}
        try:
            from bot_program.capital_truth import (account_share_pct,
                                                   share_label)
            from bot_program.share_allocator import bounds_for
            row["current"] = share_label(cfg, plan_now)
            pct = account_share_pct(cfg)
            if pct is None and cfg.pk in plan_now:
                pct = float(plan_now[cfg.pk]) * 100.0
            row["current_pct"] = pct
            lo, hi, _why = bounds_for(cfg)
            row["floor"], row["ceiling"] = lo, hi
        except Exception as e:  # noqa: BLE001
            logger.warning("[shares page] %s: share unreadable: %s",
                           cfg.name, e)
        inp = inputs.get(str(cfg.pk)) or {}
        if inp:
            row["target"] = inp.get("target")
            row["why"] = inp.get("why") or ""
            row["held"] = bool(inp.get("held"))
            row["lane"] = (inp.get("evidence") or {}).get("lane", "")
            if inp.get("floor") is not None:
                row["floor"], row["ceiling"] = inp["floor"], inp["ceiling"]
            try:
                if row["target"] is not None and row["current_pct"] is not None:
                    row["delta"] = float(row["target"]) - float(row["current_pct"])
            except (TypeError, ValueError):
                row["delta"] = None
        rows.append(row)

    live_mode, daily_applies_used, max_applies = False, 0, 3
    auto_derisk = False
    try:
        from bot_program.share_allocator import (MAX_APPLIES_PER_DAY,
                                                 applies_used_today,
                                                 is_auto_derisk_enabled,
                                                 is_live_mode)
        max_applies = MAX_APPLIES_PER_DAY
        live_mode = is_live_mode()
        auto_derisk = is_auto_derisk_enabled()
        daily_applies_used = applies_used_today(user)
    except Exception as e:  # noqa: BLE001
        logger.warning("[shares page] mode unreadable: %s", e)

    # ── the market state: SHOCK / EXPANSION / NORMAL, and why ────────
    # The same reader the proposer runs, fed the evidence off the latest
    # plan's own inputs rather than re-scored here — a page load must not
    # re-run the evidence ledger. market_state never raises; the fence is
    # for the brain context read beside it.
    market = {"mode": "normal", "reasons": ["market state unreadable"],
              "drop_24h_pct": None, "drawdown_pct": None, "at_hwm": False,
              "regime": None}
    try:
        from bot_program.share_allocator import market_state
        ctx = None
        try:
            from brain.context import get_brain_context
            ctx = get_brain_context(max_age_minutes=90)
        except Exception as e:  # noqa: BLE001
            logger.warning("[shares page] brain context unreadable: %s", e)
        evidence = {}
        latest = plans.order_by("-proposed_at").first()
        for k, inp in ((latest.inputs or {}) if latest is not None else {}).items():
            if isinstance(inp, dict) and isinstance(inp.get("evidence"), dict):
                evidence[inp.get("name") or f"#{k}"] = inp["evidence"]
        market = market_state(user, ctx, evidence=evidence)
        if market.get("drop_24h_pct") is not None:
            market["drop_text"] = f"{float(market['drop_24h_pct']) * 100:.1f}%"
    except Exception as e:  # noqa: BLE001
        logger.warning("[shares page] market state unreadable: %s", e)

    context = {
        "page_id": "shares",
        "reading": reading,
        "reading_stale": reading_stale,
        "drawdown": drawdown,
        "governor": governor,
        "plan": plan,
        "rows": rows,
        "alloc_reason": alloc_reason,
        "pending": pending,
        "applied": applied,
        "history": history,
        "live_mode": live_mode,
        "auto_derisk": auto_derisk,
        "market": market,
        "is_admin": user.is_superuser,
        "daily_applies_used": daily_applies_used,
        "MAX_APPLIES_PER_DAY": max_applies,
    }
    return render(request, "dashboard/shares.html", context)


def _plan_rows(plan) -> list:
    """[{pk, name, current, target, held, why}] off the plan's own JSON —
    the numbers the plan saw, not today's, so a decided plan reads the
    same a week later."""
    out = []
    inputs = plan.inputs or {}
    current = plan.current_shares or {}
    for k, target in (plan.targets or {}).items():
        inp = inputs.get(k) or {}
        cur = current.get(k)
        try:
            cur_text = f"{float(cur):g}%" if cur is not None else "auto"
        except (TypeError, ValueError):
            cur_text = "?"
        try:
            tgt_text = f"{float(target):g}%"
        except (TypeError, ValueError):
            tgt_text = "?"
        out.append({"pk": k, "name": inp.get("name") or f"#{k}",
                    "current": cur_text, "target": tgt_text,
                    "held": bool(inp.get("held")),
                    "why": inp.get("why") or "",
                    # Why a move stopped where it did: the day's allowance
                    # up and down under the plan's mode (None on plans
                    # proposed before the modes existed).
                    "allowance_up": inp.get("allowance_up"),
                    "allowance_down": inp.get("allowance_down")})
    return out
