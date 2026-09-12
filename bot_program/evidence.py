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
# The window a config with no persona is graded over — the number
# `config_evidence` carried as its only default for its whole life. A
# persona replaces it with a window matched to its holding period: 90
# days of scalps is four hundred trades and 90 days of position trades
# is three, and one window cannot grade both (2026-09-12).
DEFAULT_EVIDENCE_DAYS = 90


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


def config_evidence(cfg, *, days=None) -> dict:
    """{lane, n, win_rate, avg_r, r_sum, measured, days, score, reason}.

    `lane` is 'live' (this config's live fills), 'fleet_live' (live fills
    of every config in this asset class, trade-weighted), 'paper' (this
    config's paper fills) or 'none'. `score` is 1.0 unless `measured`.

    `days` None means THE CONFIG'S PERSONA WINDOW, and
    DEFAULT_EVIDENCE_DAYS when it wears none. The grading window has to
    follow the holding period or the number is not an expectancy: 21 days
    is a sample of scalps and one position trade, and the old fixed 90
    graded both as if they were the same evidence. An explicit `days`
    still wins outright — every caller that names a window keeps it, so
    the share allocator's own 90-day lane is untouched (2026-09-12).

    `days` comes BACK in the answer for the same reason: a caller that did
    not name a window (brain.horizon's config lanes) would otherwise print
    numbers from three different windows side by side with nothing saying
    so.
    """
    from datetime import timedelta

    from django.utils import timezone

    from bot_program.bot_grading import VENUE_LIVE, bot_performance_summary

    if days is None:
        from bot_program.personas import persona_evidence_days
        days = persona_evidence_days(cfg, DEFAULT_EVIDENCE_DAYS)
    since = timezone.now() - timedelta(days=days)
    tried = []

    # Lane 1 — this config's own live fills.
    live = _lane_from_rows(_own_fills(cfg, since, paper=False)
                           .values_list("realized_r", flat=True))
    if live["n"] >= MIN_EVIDENCE_N:
        return {"lane": "live", **live, "measured": True, "days": days,
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
                "days": days, "score": evidence_score(wr, avg),
                "reason": f"{fleet_n} fleet live fills in {cfg.asset_class} "
                          f"over {days}d (own live n={live['n']})"}
    tried.append(f"fleet live n={fleet_n}")

    # Lane 3 — this config's own paper fills.
    paper = _lane_from_rows(_own_fills(cfg, since, paper=True)
                            .values_list("realized_r", flat=True))
    if paper["n"] >= MIN_EVIDENCE_N:
        return {"lane": "paper", **paper, "measured": True, "days": days,
                "score": evidence_score(paper["win_rate"], paper["avg_r"]),
                "reason": f"{paper['n']} paper fills in {days}d "
                          f"({', '.join(tried)})"}
    tried.append(f"paper n={paper['n']}")

    # The window is named HERE too, and this is the branch that needed it
    # most: "unmeasured" is the answer a config gets for months, and which
    # window it was unmeasured over is the difference between "too few
    # scalps in three weeks" and "too few position trades in a year". The
    # three measured branches always said it; this one used not to, so a
    # persona window was invisible in exactly the case it governs
    # (2026-09-12).
    return {"lane": "none", "n": 0, "win_rate": None, "avg_r": None,
            "r_sum": 0.0, "measured": False, "score": 1.0, "days": days,
            "reason": f"unmeasured — below {MIN_EVIDENCE_N} graded fills "
                      f"in every lane in {days}d ({', '.join(tried)})"}


# ── What each PERSONA has proven, over its own window ───────────────────
#
# Not a fourth grading system: the same graded rows `_own_fills` reads,
# grouped by the persona the config wears and windowed by the window that
# persona declares. Live and paper are NEVER pooled here, for the reason
# they are never pooled anywhere in this module — the gap between them is
# the fact bot_grading exists to measure, and a persona whose record is
# mostly simulation must say so rather than average it away.

def _persona_lane(rows) -> dict:
    """{n, win_rate, avg_r, r_sum, measured} — r_sum None at n=0.

    `_lane_from_rows` answers 0.0 for an empty lane, which is right for
    the allocator (it multiplies) and wrong for a page (it PRINTS). A
    persona nothing has traded has earned NOTHING MEASURED, and 0.0 R
    reads as "broke even", which is a claim. None renders as an em-dash.
    """
    lane = _lane_from_rows(rows)
    if lane["n"] == 0:
        return {"n": 0, "win_rate": None, "avg_r": None, "r_sum": None,
                "measured": False}
    lane["measured"] = lane["n"] >= MIN_EVIDENCE_N
    return lane


def _fills_for(configs, since, *, paper):
    from bot_program.models import AssetBotTrade
    if not configs:
        return []
    return list(AssetBotTrade.objects
                .filter(config__in=configs, status="CLOSED", paper=paper,
                        closed_at__gte=since, outcome__in=GRADED_OUTCOMES,
                        realized_r__isnull=False)
                .exclude(rule_name="").exclude(rule_name="manual_take")
                .values_list("realized_r", flat=True))


def _lane_sentence(label, lane, days) -> str:
    """A full sentence, always — 'swing has earned +3.2R over 18 live
    fills in 90 days' or 'scalp is unmeasured: 2 fills, the floor is 10'.

    The empty state is a sentence too. A dash in a cell with no sentence
    beside it is the platform's oldest UI lie: it looks like a measured
    nothing.
    """
    n = int(lane["n"] or 0)
    if n == 0:
        return (f"{label} has no graded fill in {days} days — "
                f"unmeasured, which is not zero.")
    if not lane["measured"]:
        return (f"{label} is unmeasured: {n} fill"
                f"{'' if n == 1 else 's'} in {days} days, the floor is "
                f"{MIN_EVIDENCE_N}.")
    return (f"{label} has earned {float(lane['r_sum']):+.1f}R over {n} "
            f"fills in {days} days, {float(lane['win_rate']) * 100:.0f}% "
            f"of them winners.")


def persona_rows() -> list:
    """One row per persona, over THAT persona's own grading window.

    [{key, label, purpose, holding, evidence_days, horizon_weight,
      share_floor_pct, share_ceiling_pct, n_configs, names, configs,
      live, paper, measured, sentence}]

    `measured` is True when EITHER lane has cleared MIN_EVIDENCE_N — the
    platform's floor, the same one config_evidence uses. `configs` carries
    each wearing config with its own live and paper record over the same
    window, so the page can show which of them the persona's number is
    actually made of.
    """
    from datetime import timedelta

    from django.utils import timezone

    from bot_program.models import AssetBotConfig
    from bot_program.personas import PERSONAS, persona_of

    now = timezone.now()
    wearing: dict = {k: [] for k in PERSONAS}
    for cfg in (AssetBotConfig.objects.select_related("user")
                .order_by("asset_class", "name")):
        key = persona_of(cfg)
        if key in wearing:
            wearing[key].append(cfg)

    rows = []
    for key, persona in PERSONAS.items():
        cfgs = wearing[key]
        since = now - timedelta(days=persona.evidence_days)
        live = _persona_lane(_fills_for(cfgs, since, paper=False))
        paper = _persona_lane(_fills_for(cfgs, since, paper=True))
        per_config = []
        for cfg in cfgs:
            c_live = _persona_lane(_fills_for([cfg], since, paper=False))
            c_paper = _persona_lane(_fills_for([cfg], since, paper=True))
            per_config.append({
                "cfg": cfg, "name": cfg.name, "pk": cfg.pk,
                "owner": cfg.user.username, "mode": cfg.mode,
                "asset_class": cfg.asset_class, "enabled": cfg.enabled,
                "live": c_live, "paper": c_paper,
                "live_sentence": _lane_sentence(f"{cfg.name} live", c_live,
                                                persona.evidence_days),
                "paper_sentence": _lane_sentence(f"{cfg.name} paper",
                                                 c_paper,
                                                 persona.evidence_days),
            })
        measured = bool(live["measured"] or paper["measured"])
        if not cfgs:
            sentence = (f"No config wears {key}. Give one this personality "
                        f"with: python manage.py persona apply "
                        f"<config_id> {key} --yes")
        elif live["n"]:
            sentence = _lane_sentence(key, live, persona.evidence_days)
        else:
            sentence = _lane_sentence(key, paper, persona.evidence_days) \
                if paper["n"] else _lane_sentence(key, live,
                                                  persona.evidence_days)
        rows.append({
            "key": key, "label": persona.label, "purpose": persona.purpose,
            "holding": persona.holding,
            "evidence_days": persona.evidence_days,
            "horizon_weight": persona.horizon_weight,
            "share_floor_pct": persona.share_floor_pct,
            "share_ceiling_pct": persona.share_ceiling_pct,
            "n_configs": len(cfgs),
            "names": [c.name for c in cfgs],
            "configs": per_config,
            "live": live, "paper": paper,
            "measured": measured, "sentence": sentence,
        })
    return rows
