"""The evidence ledger — what every rule and every config has PROVEN.

The platform grades itself in three places and showed them on three
pages: graded Signals per rule (the promotion ladder's first rung), closed
bot trades per venue (its second), and the agents' calls (the calibration
page). Nowhere did the operator see, on one page, the question that
decides where capital goes: what did each rule make in paper, what did it
make live, and how much proven R is sitting in paper that nothing has
taken live yet — the regret.

Three tables, all read-only, all from the tables the ladder itself reads:

  * RULES — per rule_name: stage and status; graded signals (n, hit rate,
    expectancy, cumulative R); paper fills and live fills (n, P&L, R);
    and the regret: cumulative paper R for a rule with no live fill.
  * CONFIGS — per AssetBotConfig: mode, shadow, share of the account, open
    and closed counts, paper and live R; and the shadow calls the config
    registered while in shadow mode, graded by the calibration — the
    direction at the horizon, which is not the bracket, and says so.
  * AGENTS — the calls ledger lives on /calibration/; linked, not copied.

Nothing here is a forecast. A number appears only when a grade exists.
"""
from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, Q, Sum
from django.shortcuts import render


def _blank() -> dict:
    return {"sig_n": 0, "sig_hit": None, "sig_r": 0.0, "sig_avg": None,
            "paper_n": 0, "paper_pnl": 0.0, "paper_r": 0.0,
            "live_n": 0, "live_pnl": 0.0, "live_r": 0.0}


def rule_rows() -> list:
    """One row per rule the platform has any evidence about."""
    from bot_program.models import AssetBotTrade
    from signals.models import Signal
    from signals.models_control import RuleControl

    by_rule: dict = {}
    graded = (Signal.objects.filter(is_active=False)
              .exclude(outcome="").exclude(realized_r__isnull=True)
              .values("rule_name")
              .annotate(n=Count("id"),
                        hits=Count("id", filter=Q(outcome="hit_target")),
                        r_sum=Sum("realized_r"), r_avg=Avg("realized_r")))
    for s in graded:
        row = by_rule.setdefault(s["rule_name"] or "?", _blank())
        n = int(s["n"] or 0)
        row["sig_n"] = n
        row["sig_hit"] = (int(s["hits"] or 0) / n) if n else None
        row["sig_r"] = float(s["r_sum"] or 0.0)
        row["sig_avg"] = (float(s["r_avg"]) if s["r_avg"] is not None
                          else None)
    fills = (AssetBotTrade.objects
             .filter(status="CLOSED", realized_r__isnull=False)
             .values("rule_name", "paper")
             .annotate(n=Count("id"), pnl=Sum("pnl"), r_sum=Sum("realized_r")))
    for f in fills:
        row = by_rule.setdefault(f["rule_name"] or "?", _blank())
        key = "paper" if f["paper"] else "live"
        row[f"{key}_n"] = int(f["n"] or 0)
        row[f"{key}_pnl"] = float(f["pnl"] or 0.0)
        row[f"{key}_r"] = float(f["r_sum"] or 0.0)
    controls = {c.rule_name: c for c in RuleControl.objects.all()}
    for name in controls:
        by_rule.setdefault(name, _blank())

    rows = []
    for name, row in by_rule.items():
        ctrl = controls.get(name)
        row["rule"] = name
        row["stage"] = (getattr(ctrl, "promotion_stage", "") or "—") if ctrl else "—"
        row["status"] = (getattr(ctrl, "status", "") or "") if ctrl else "no control row"
        # THE REGRET: R a rule has proven in paper while nothing took it
        # live. Zero once a single live fill exists — the question then is
        # sizing, which the ladder answers, not this page.
        row["regret_r"] = row["paper_r"] if row["live_n"] == 0 else 0.0
        rows.append(row)
    rows.sort(key=lambda r: (-(r["paper_r"] + r["sig_r"]), r["rule"]))
    return rows


def shadow_agent_for(cfg) -> str:
    """The calibration's name for a config in shadow mode. The id keeps
    six configs called "manual" apart; the name keeps the ledger readable."""
    return f"bot:{cfg.name}#{cfg.pk}"


def config_rows() -> list:
    from ai_agents.models import AgentPrediction
    from bot_program.asset_engine.safety import is_shadow
    from bot_program.capital_truth import (allocate_shares, followers_of,
                                           share_label, tracks_broker)
    from bot_program.models import AssetBotConfig, AssetBotTrade

    plans: dict = {}
    rows = []
    for cfg in (AssetBotConfig.objects.select_related("user")
                .order_by("user__username", "asset_class", "name")):
        if cfg.user_id not in plans:
            try:
                plans[cfg.user_id] = allocate_shares(
                    followers_of(cfg.user))["plan"]
            except Exception:  # noqa: BLE001 — the ledger must render
                plans[cfg.user_id] = {}
        closed = AssetBotTrade.objects.filter(config=cfg, status="CLOSED")
        agg = closed.aggregate(
            n=Count("id"), pnl=Sum("pnl"),
            paper_n=Count("id", filter=Q(paper=True)),
            paper_r=Sum("realized_r", filter=Q(paper=True)),
            live_n=Count("id", filter=Q(paper=False)),
            live_r=Sum("realized_r", filter=Q(paper=False)))
        open_n = AssetBotTrade.objects.filter(
            config=cfg, status__in=("OPEN", "CLOSE_PENDING")).count()
        calls = AgentPrediction.objects.filter(
            agent=shadow_agent_for(cfg), prediction_type="direction")
        c_all = calls.count()
        c_agg = calls.filter(was_correct__isnull=False).aggregate(
            n=Count("id"), hits=Count("id", filter=Q(was_correct=True)),
            move=Avg("score"))
        c_n = int(c_agg["n"] or 0)
        rows.append({
            "cfg": cfg,
            "owner": cfg.user.username,
            "shadow": is_shadow(cfg),
            "research": bool((cfg.extras or {}).get("research_fleet")),
            "share": (share_label(cfg, plans[cfg.user_id])
                      if tracks_broker(cfg) else ""),
            "open_n": open_n,
            "closed_n": int(agg["n"] or 0),
            "pnl": float(agg["pnl"] or 0.0),
            "paper_n": int(agg["paper_n"] or 0),
            "paper_r": float(agg["paper_r"] or 0.0),
            "live_n": int(agg["live_n"] or 0),
            "live_r": float(agg["live_r"] or 0.0),
            "calls_n": c_all,
            "calls_graded": c_n,
            "calls_hit": (int(c_agg["hits"] or 0) / c_n) if c_n else None,
            "calls_move": (float(c_agg["move"]) if c_agg["move"] is not None
                           else None),
        })
    return rows


@login_required
def evidence_ledger(request):
    rules = rule_rows()
    configs = config_rows()
    totals = {
        "rules": len(rules),
        "sig_n": sum(r["sig_n"] for r in rules),
        "paper_r": round(sum(r["paper_r"] for r in rules), 2),
        "live_r": round(sum(r["live_r"] for r in rules), 2),
        "regret_r": round(sum(r["regret_r"] for r in rules), 2),
        "shadow_calls": sum(c["calls_n"] for c in configs),
    }
    return render(request, "dashboard/evidence.html", {
        "page_id": "evidence", "rules": rules, "configs": configs,
        "totals": totals,
    })
