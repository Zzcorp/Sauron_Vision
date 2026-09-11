"""The evidence ledger — what every rule and every config has PROVEN.

Read-only aggregates over the tables the promotion ladder itself reads:
graded Signals per rule, closed bot trades per venue, and the direction
calls a config registered while in shadow mode. One module, so the page
(/evidence/), the strategy generator's snapshot and the shadow gate all
read the same numbers — a ledger with two implementations is two ledgers.

Nothing here is a forecast. A number appears only when a grade exists.
"""
from django.db.models import Avg, Count, Q, Sum


def _blank() -> dict:
    return {"sig_n": 0, "sig_hit": None, "sig_r": 0.0, "sig_avg": None,
            "paper_n": 0, "paper_pnl": 0.0, "paper_r": 0.0,
            "live_n": 0, "live_pnl": 0.0, "live_r": 0.0}


def rule_rows() -> list:
    """One row per rule the platform has any evidence about.

    Per rule_name: stage and status; graded signals (n, hit rate,
    expectancy, cumulative R); paper fills and live fills (n, P&L, R); and
    the regret — cumulative paper R for a rule with no live fill.
    """
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
        # sizing, which the ladder answers, not this ledger.
        row["regret_r"] = row["paper_r"] if row["live_n"] == 0 else 0.0
        rows.append(row)
    rows.sort(key=lambda r: (-(r["paper_r"] + r["sig_r"]), r["rule"]))
    return rows


def shadow_agent_for(cfg) -> str:
    """The calibration's name for a config in shadow mode. The id keeps
    six configs called "manual" apart; the name keeps the ledger readable."""
    return f"bot:{cfg.name}#{cfg.pk}"


def config_rows() -> list:
    """One row per AssetBotConfig: what it did, and what its shadow called."""
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


# ── What one config has proven, for the share allocator ─────────────────
#
# Three lanes, tried in order and NEVER pooled: this config's own live
# fills; the fleet's live fills of the same asset class; this config's
# paper fills. Paper and live are kept apart because the gap between them
# is the fact bot_grading exists to measure — pooling would size a live
# pool on a simulation. Fewer than MIN_EVIDENCE_N graded fills in every
# lane is UNMEASURED and scores 1.0 (neutral), not 0.5 (penalised): the
# allocator must not shrink a pool for being new. A NULL realized_r is an
# unpriced exit and is excluded, never counted as a zero-R trade.
MIN_EVIDENCE_N = 10
GRADED_OUTCOMES = ["hit_target", "stopped_out", "manual_close", "expired",
                   "time_stop"]


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def evidence_score(win_rate, avg_r) -> float:
    """1 + (wr - 0.5) * 0.6 + clamp(avg_r, -1, 1) * 0.4, held to [0.5, 1.5].

    A coin-flip rule with zero expectancy is exactly 1.0; the win-rate
    term and the R term each move it by at most ±0.3 / ±0.4, so no single
    hot streak can double a share.
    """
    return _clamp(1.0 + (float(win_rate) - 0.5) * 0.6
                  + _clamp(float(avg_r), -1.0, 1.0) * 0.4, 0.5, 1.5)


def _own_fills(cfg, since, *, paper):
    from bot_program.models import AssetBotTrade
    return (AssetBotTrade.objects
            .filter(config=cfg, status="CLOSED", paper=paper,
                    closed_at__gte=since, outcome__in=GRADED_OUTCOMES,
                    realized_r__isnull=False)
            .exclude(rule_name="").exclude(rule_name="manual_take"))


def _lane_from_rows(rows) -> dict:
    rs = [float(r) for r in rows if r is not None]
    n = len(rs)
    if n == 0:
        return {"n": 0, "win_rate": None, "avg_r": None, "r_sum": 0.0}
    wins = sum(1 for r in rs if r > 0)
    return {"n": n, "win_rate": wins / n, "avg_r": sum(rs) / n,
            "r_sum": sum(rs)}


def config_evidence(cfg, *, days=90) -> dict:
    """{lane, n, win_rate, avg_r, r_sum, measured, score, reason}.

    `lane` is 'live' (this config's live fills), 'fleet_live' (live fills
    of every config in this asset class, trade-weighted), 'paper' (this
    config's paper fills) or 'none'. `score` is 1.0 unless `measured`.
    """
    from datetime import timedelta

    from django.utils import timezone

    from bot_program.bot_grading import VENUE_LIVE, bot_performance_summary

    since = timezone.now() - timedelta(days=days)
    tried = []

    # Lane 1 — this config's own live fills.
    live = _lane_from_rows(_own_fills(cfg, since, paper=False)
                           .values_list("realized_r", flat=True))
    if live["n"] >= MIN_EVIDENCE_N:
        return {"lane": "live", **live, "measured": True,
                "score": evidence_score(live["win_rate"], live["avg_r"]),
                "reason": f"{live['n']} live fills in {days}d"}
    tried.append(f"live n={live['n']}")

    # Lane 2 — the fleet's live fills in this asset class, weighted by n
    # per (rule, class) row. bot_performance_summary already excludes
    # NULL realized_r and blank rule names; manual_take rows are dropped
    # here for the same reason lane 1 drops them — a hand-taken trade is
    # the operator's evidence, not a rule's.
    fleet_n, fleet_wins, fleet_r = 0, 0.0, 0.0
    try:
        rows = bot_performance_summary(asset_class=cfg.asset_class,
                                       days=days, venue=VENUE_LIVE, min_n=1)
    except Exception:  # noqa: BLE001 — a lane that cannot answer is unmeasured
        rows = []
    for row in rows:
        if (row.get("rule_name") or "") == "manual_take":
            continue
        n = int(row.get("n") or 0)
        fleet_n += n
        fleet_wins += float(row.get("win_rate") or 0.0) * n
        fleet_r += float(row.get("expectancy") or 0.0) * n
    if fleet_n >= MIN_EVIDENCE_N:
        wr, avg = fleet_wins / fleet_n, fleet_r / fleet_n
        return {"lane": "fleet_live", "n": fleet_n, "win_rate": wr,
                "avg_r": avg, "r_sum": fleet_r, "measured": True,
                "score": evidence_score(wr, avg),
                "reason": f"{fleet_n} fleet live fills in {cfg.asset_class} "
                          f"over {days}d (own live n={live['n']})"}
    tried.append(f"fleet live n={fleet_n}")

    # Lane 3 — this config's own paper fills.
    paper = _lane_from_rows(_own_fills(cfg, since, paper=True)
                            .values_list("realized_r", flat=True))
    if paper["n"] >= MIN_EVIDENCE_N:
        return {"lane": "paper", **paper, "measured": True,
                "score": evidence_score(paper["win_rate"], paper["avg_r"]),
                "reason": f"{paper['n']} paper fills in {days}d "
                          f"({', '.join(tried)})"}
    tried.append(f"paper n={paper['n']}")

    return {"lane": "none", "n": 0, "win_rate": None, "avg_r": None,
            "r_sum": 0.0, "measured": False, "score": 1.0,
            "reason": f"unmeasured — below {MIN_EVIDENCE_N} graded fills "
                      f"in every lane ({', '.join(tried)})"}
