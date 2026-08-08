"""Operations Center — unified tabbed view (renamed from Command Center).

Replaces the old "Dashboard" + "Sauron's Eye" + "Command Center" layout
with a single richer page split into 4 tabs:

  LIVE       — current Eye content + brain regime + gate ratio + recent fills
  PORTFOLIO  — equity curve + allocation donut + Sharpe + winners/losers
  HISTORY    — cumulative R curve + rolling win-rate + DoW heatmap + per-rule
  BOTS       — per-bot today's stats + heartbeat + cooldown countdown

Every tab head also displays a LIVE metric so the tab bar itself is a
mini-dashboard (e.g. LIVE shows "3 OPEN · +$142", BOTS shows "5/8 ON").

WebSocket: tabs subscribe to typed events on the existing /ws/eye/ feed
so live updates push (no polling).
"""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Avg, Count
from django.shortcuts import render
from django.utils import timezone


# ── Helpers ──────────────────────────────────────────────────────────────

def _smart_default_tab(user) -> str:
    """If the user has any enabled bot configs → LIVE; else → PORTFOLIO."""
    try:
        from bot_program.models import AssetBotConfig
        if AssetBotConfig.objects.filter(user=user, enabled=True).exists():
            return "live"
    except Exception:
        pass
    return "portfolio"


def _tab_bar_metrics(user) -> dict:
    """Compute the small live metric shown in each tab head.

    Returned shape (all values are pre-formatted strings ready for the template):
      {
        "live":      {"primary": "3 OPEN", "secondary": "+$142.30"},
        "portfolio": {"primary": "$10,234", "secondary": "+2.1%"},
        "history":   {"primary": "47W·12L", "secondary": "+0.34R"},
        "bots":      {"primary": "5/8 ON", "secondary": "+$42.00 24h"},
      }
    """
    out = {
        "live":      {"primary": "—", "secondary": ""},
        "portfolio": {"primary": "—", "secondary": ""},
        "history":   {"primary": "—", "secondary": ""},
        "bots":      {"primary": "—", "secondary": ""},
    }

    # ── LIVE: open positions count + unrealized P&L ──────────────────
    try:
        from bot_program.models import AssetBotTrade
        from portfolio.services import get_or_create_default_portfolio
        from portfolio.models import Position
        portfolio = get_or_create_default_portfolio(user=user)
        n_open_bot = AssetBotTrade.objects.filter(
            config__user=user, status="OPEN").count()
        n_open_pos = Position.objects.filter(
            portfolio=portfolio, closed_at__isnull=True).count()
        n_open = n_open_bot + n_open_pos
        unrealized = sum(
            float(p.unrealized_pnl or 0)
            for p in Position.objects.filter(
                portfolio=portfolio, closed_at__isnull=True))
        sign = "+" if unrealized >= 0 else ""
        out["live"]["primary"] = f"{n_open} OPEN"
        out["live"]["secondary"] = f"{sign}{unrealized:,.2f}"
    except Exception:
        pass

    # ── PORTFOLIO: portfolio value + 24h delta ───────────────────────
    try:
        from portfolio.services import get_or_create_default_portfolio
        from portfolio.models import PortfolioSnapshot
        portfolio = get_or_create_default_portfolio(user=user)
        out["portfolio"]["primary"] = f"${float(portfolio.current_value):,.0f}"
        latest = (PortfolioSnapshot.objects.filter(portfolio=portfolio)
                   .order_by("-date").first())
        if latest:
            pct = float(latest.daily_pnl_pct or 0)
            sign = "+" if pct >= 0 else ""
            out["portfolio"]["secondary"] = f"{sign}{pct:.2f}%"
    except Exception:
        pass

    # ── HISTORY: 30-day W/L count + avg R ────────────────────────────
    try:
        from bot_program.models import AssetBotTrade
        cutoff = timezone.now() - timedelta(days=30)
        closed = AssetBotTrade.objects.filter(
            config__user=user, status="CLOSED", closed_at__gte=cutoff,
            realized_r__isnull=False)
        wins = closed.filter(realized_r__gt=0).count()
        losses = closed.filter(realized_r__lte=0).count()
        if wins + losses > 0:
            avg_r = closed.aggregate(a=Avg("realized_r"))["a"] or 0
            sign = "+" if avg_r >= 0 else ""
            out["history"]["primary"] = f"{wins}W·{losses}L"
            out["history"]["secondary"] = f"{sign}{avg_r:.2f}R"
    except Exception:
        pass

    # ── BOTS: enabled count + 24h P&L ────────────────────────────────
    try:
        from bot_program.models import AssetBotConfig, AssetBotTrade
        configs = AssetBotConfig.objects.filter(user=user)
        n_total = configs.count()
        n_on = configs.filter(enabled=True).count()
        cutoff = timezone.now() - timedelta(hours=24)
        pnl_24h = (AssetBotTrade.objects
                   .filter(config__user=user, status="CLOSED",
                            closed_at__gte=cutoff)
                   .aggregate(s=Sum("pnl"))["s"] or Decimal("0"))
        out["bots"]["primary"] = f"{n_on}/{n_total} ON"
        sign = "+" if pnl_24h >= 0 else ""
        out["bots"]["secondary"] = f"{sign}${float(pnl_24h):,.2f} 24h"
    except Exception:
        pass

    return out


def _hero_context(user) -> dict:
    """Header strip data — visible above tabs at all times."""
    from portfolio.services import get_or_create_default_portfolio
    from portfolio.models import PortfolioSnapshot

    portfolio = get_or_create_default_portfolio(user=user)
    latest_snapshot = (PortfolioSnapshot.objects.filter(portfolio=portfolio)
                        .order_by("-date").first())

    pnl_24h = "+0.00"
    if latest_snapshot:
        try:
            pnl_24h = "{:+.2f}".format(float(latest_snapshot.daily_pnl_pct))
        except Exception:
            pass

    # Detect if any live-mode bot exists → "LIVE" pill, else paper.
    mode = "paper"
    try:
        from bot_program.models import AssetBotConfig
        if AssetBotConfig.objects.filter(user=user, enabled=True, mode="live").exists():
            mode = "live"
    except Exception:
        pass

    # Brain regime + trust band for the hero strip (Phase 47 actuation).
    regime = "—"
    regime_conf = 0.0
    trust_band = "unknown"
    try:
        from brain.models import BrainReport
        from brain.context import _brain_trust_score, brain_trust_band
        latest_report = (BrainReport.objects.filter(error="")
                          .order_by("-created_at").first())
        if latest_report:
            regime = latest_report.regime_label
            regime_conf = float(latest_report.regime_confidence or 0)
        trust = _brain_trust_score()
        trust_band = brain_trust_band(trust)
    except Exception:
        pass

    return {
        "portfolio": portfolio,
        "portfolio_value": portfolio.current_value,
        "pnl_24h_pct": pnl_24h,
        "currency": portfolio.currency,
        "operator_mode": mode,
        "now_utc": timezone.now(),
        "brain_regime": regime,
        "brain_regime_conf": regime_conf,
        "brain_trust_band": trust_band,
    }


# ── Main entry point ─────────────────────────────────────────────────────

@login_required
def command_center(request):
    """Renders the wrapper with tabs. Initial tab from `?tab=` or smart default.

    Note: route stays at /command/ for backward compat — only the visible
    name changed to 'Operations Center'.
    """
    tab = (request.GET.get("tab") or _smart_default_tab(request.user)).lower()
    if tab not in ("live", "portfolio", "history", "bots"):
        tab = "live"

    context = {
        "page_id": "command",
        "active_tab": tab,
        "tab_metrics": _tab_bar_metrics(request.user),
        **_hero_context(request.user),
    }
    return render(request, "dashboard/command.html", context)


# ── Per-tab fragment endpoints (HTMX-loaded) ─────────────────────────────

@login_required
def command_tab_live(request):
    """LIVE tab — current Eye content + Operations enrichment."""
    from .views_eye import _build_eye_context
    context = _build_eye_context(request.user)

    # Operations enrichment for LIVE.
    user = request.user
    try:
        from portfolio.services import get_or_create_default_portfolio
        from portfolio.models import Position
        portfolio = get_or_create_default_portfolio(user=user)
        open_positions = Position.objects.filter(
            portfolio=portfolio, closed_at__isnull=True)
        deployed_value = sum(
            abs(float(p.quantity or 0) * float(p.current_price or 0))
            for p in open_positions)
        cash_value = float(portfolio.cash_available or 0)
        total = deployed_value + cash_value
        deployed_pct = round(deployed_value / total * 100, 1) if total > 0 else 0
        cash_pct = round(cash_value / total * 100, 1) if total > 0 else 0
        context["live_deployed"] = deployed_value
        context["live_cash"] = cash_value
        context["live_deployed_pct"] = deployed_pct
        context["live_cash_pct"] = cash_pct
    except Exception:
        context["live_deployed"] = 0
        context["live_cash"] = 0
        context["live_deployed_pct"] = 0
        context["live_cash_pct"] = 100

    # Today's gate allow/reject ratio (Phase 15 orchestrator).
    try:
        from bot_program.orchestrator_models import OrchestratorEvent
        cutoff = timezone.now() - timedelta(hours=24)
        today_events = OrchestratorEvent.objects.filter(
            user=user, created_at__gte=cutoff)
        n_allow = today_events.filter(decision="allow").count()
        n_reject = today_events.filter(decision="reject").count()
        n_total = n_allow + n_reject
        accept_rate = round(n_allow / n_total * 100, 1) if n_total > 0 else 0
        context["gate_n_allow"] = n_allow
        context["gate_n_reject"] = n_reject
        context["gate_accept_rate"] = accept_rate
    except Exception:
        context["gate_n_allow"] = 0
        context["gate_n_reject"] = 0
        context["gate_accept_rate"] = 0

    # Recent fills (last 5 closed bot trades in the last 24h) + 24h session metrics.
    try:
        from bot_program.models import AssetBotTrade, AssetBotConfig
        cutoff = timezone.now() - timedelta(hours=24)
        all_24h_closed = list(
            AssetBotTrade.objects
            .filter(config__user=user, status="CLOSED",
                     closed_at__gte=cutoff)
            .select_related("config")
            .order_by("-closed_at")
        )
        context["live_recent_fills"] = all_24h_closed[:5]

        # 24h session aggregates.
        n_closed_24h = len(all_24h_closed)
        rs = [float(t.realized_r or 0) for t in all_24h_closed
              if t.realized_r is not None]
        n_wins = sum(1 for r in rs if r > 0)
        n_losses = sum(1 for r in rs if r < 0)
        sum_r = round(sum(rs), 2)
        win_rate_24h = round(n_wins / len(rs) * 100, 1) if rs else 0
        # Best/worst by R in 24h.
        graded = [t for t in all_24h_closed if t.realized_r is not None]
        best_24h = max(graded, key=lambda t: float(t.realized_r),
                        default=None)
        worst_24h = min(graded, key=lambda t: float(t.realized_r),
                         default=None)

        # Open trades + bots-active (inputs to live_opens cell).
        n_opens = AssetBotTrade.objects.filter(
            config__user=user, status="OPEN").count()
        n_bots_enabled = AssetBotConfig.objects.filter(
            user=user, enabled=True).count()
        n_bots_total = AssetBotConfig.objects.filter(user=user).count()

        # Last 12 closes — sparkline of the realized-R sequence.
        last_12_r = [float(t.realized_r or 0) for t in
                      list(reversed(all_24h_closed[-12:]))
                      if t.realized_r is not None]

        context["live_opens"] = n_opens
        context["live_bots_enabled"] = n_bots_enabled
        context["live_bots_total"] = n_bots_total
        context["live_24h_n"] = n_closed_24h
        context["live_24h_wins"] = n_wins
        context["live_24h_losses"] = n_losses
        context["live_24h_sum_r"] = sum_r
        context["live_24h_win_rate"] = win_rate_24h
        context["live_24h_best"] = best_24h
        context["live_24h_worst"] = worst_24h
        context["live_24h_spark"] = last_12_r
        context["live_24h_spark_min"] = (min(last_12_r) if last_12_r else 0)
        context["live_24h_spark_max"] = (max(last_12_r) if last_12_r else 0)
    except Exception:
        context["live_recent_fills"] = []
        context["live_opens"] = 0
        context["live_bots_enabled"] = 0
        context["live_bots_total"] = 0
        context["live_24h_n"] = 0
        context["live_24h_wins"] = 0
        context["live_24h_losses"] = 0
        context["live_24h_sum_r"] = 0
        context["live_24h_win_rate"] = 0
        context["live_24h_best"] = None
        context["live_24h_worst"] = None
        context["live_24h_spark"] = []
        context["live_24h_spark_min"] = 0
        context["live_24h_spark_max"] = 0

    # Active rules counter (Phase 5 RuleControl) — operator awareness.
    try:
        from bot_program.rule_control_models import RuleControl
        n_rules_active = RuleControl.objects.filter(state="active").count()
        n_rules_paused = RuleControl.objects.filter(state="paused").count()
        n_rules_research = RuleControl.objects.filter(stage="RESEARCH").count()
        context["live_rules_active"] = n_rules_active
        context["live_rules_paused"] = n_rules_paused
        context["live_rules_research"] = n_rules_research
    except Exception:
        context["live_rules_active"] = 0
        context["live_rules_paused"] = 0
        context["live_rules_research"] = 0

    # Latest brain report timing — staleness indicator.
    try:
        from brain.models import BrainReport
        last_br = BrainReport.objects.filter(error="").order_by("-created_at").first()
        if last_br:
            mins = int((timezone.now() - last_br.created_at).total_seconds() / 60)
            if mins < 60:
                context["brain_age_str"] = f"{mins}m"
            elif mins < 60 * 24:
                context["brain_age_str"] = f"{mins // 60}h"
            else:
                context["brain_age_str"] = f"{mins // (60 * 24)}d"
        else:
            context["brain_age_str"] = "—"
    except Exception:
        context["brain_age_str"] = "—"

    # Brain regime/trust for the LIVE strip.
    try:
        from brain.models import BrainReport
        from brain.context import _brain_trust_score, brain_trust_band
        latest_report = (BrainReport.objects.filter(error="")
                          .order_by("-created_at").first())
        if latest_report:
            context["brain_regime"] = latest_report.regime_label
            context["brain_regime_conf"] = float(
                latest_report.regime_confidence or 0)
            concerns = latest_report.top_concerns or []
            context["brain_top_concerns"] = concerns[:3]
        trust = _brain_trust_score()
        context["brain_trust"] = trust
        context["brain_trust_band"] = brain_trust_band(trust)
    except Exception:
        context["brain_regime"] = "unknown"
        context["brain_top_concerns"] = []
        context["brain_trust"] = None
        context["brain_trust_band"] = "unknown"

    return render(request, "dashboard/_command_live.html", context)


@login_required
def command_tab_portfolio(request):
    """PORTFOLIO tab — strategic snapshot with sparkline + allocation."""
    from portfolio.services import get_or_create_default_portfolio
    from portfolio.models import Position, PortfolioSnapshot

    portfolio = get_or_create_default_portfolio(user=request.user)
    open_positions = Position.objects.filter(
        portfolio=portfolio, closed_at__isnull=True)
    closed_positions = list(
        Position.objects.filter(portfolio=portfolio, closed_at__isnull=False)
        .select_related("instrument", "strategy")
    )
    total_closed = len(closed_positions)
    winning = [p for p in closed_positions if float(p.unrealized_pnl) > 0]
    losing = [p for p in closed_positions if float(p.unrealized_pnl) <= 0]
    win_rate = (len(winning) / total_closed * 100) if total_closed else 0
    avg_win = (sum(float(p.unrealized_pnl) for p in winning) / len(winning)) if winning else 0
    avg_loss = (sum(float(p.unrealized_pnl) for p in losing) / len(losing)) if losing else 0
    profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else 0

    total_unrealized = sum(float(p.unrealized_pnl) for p in open_positions)
    cash_pct = round(float(portfolio.cash_available) / max(float(portfolio.current_value), 1) * 100)

    latest_snapshot = (PortfolioSnapshot.objects.filter(portfolio=portfolio)
                        .order_by("-date").first())

    best_trades = sorted(closed_positions,
                         key=lambda p: float(p.unrealized_pnl), reverse=True)[:5]
    worst_trades = sorted(closed_positions,
                          key=lambda p: float(p.unrealized_pnl))[:5]

    # Equity curve sparkline — last 30 days of total_value.
    cutoff_30d = timezone.now().date() - timedelta(days=30)
    equity_rows = list(
        PortfolioSnapshot.objects.filter(
            portfolio=portfolio, date__gte=cutoff_30d)
        .order_by("date")
        .values_list("date", "total_value")
    )
    equity_points = [float(v) for _, v in equity_rows]

    # Allocation donut data — by asset class, from current open positions.
    alloc_by_class = defaultdict(float)
    for p in open_positions.select_related("instrument"):
        ac = getattr(p.instrument, "asset_class", "") or "other"
        alloc_by_class[ac] += abs(float(p.quantity or 0) * float(p.current_price or 0))
    alloc_by_class["cash"] = float(portfolio.cash_available or 0)
    alloc_total = sum(alloc_by_class.values()) or 1.0
    allocation = sorted(
        ({"asset_class": k, "value": v, "pct": round(v / alloc_total * 100, 1)}
         for k, v in alloc_by_class.items() if v > 0),
        key=lambda r: r["value"], reverse=True,
    )

    # 30d Sharpe / Sortino approximations from PortfolioSnapshot.daily_pnl_pct.
    sharpe = sortino = None
    try:
        rets = [float(s.daily_pnl_pct or 0) for s in
                PortfolioSnapshot.objects.filter(
                    portfolio=portfolio, date__gte=cutoff_30d)]
        if len(rets) >= 5:
            mean = sum(rets) / len(rets)
            var = sum((r - mean) ** 2 for r in rets) / len(rets)
            std = var ** 0.5
            sharpe = round((mean / std) * (252 ** 0.5), 2) if std > 0 else None
            downside = [r for r in rets if r < 0]
            if downside:
                d_var = sum(r ** 2 for r in downside) / len(downside)
                d_std = d_var ** 0.5
                sortino = round((mean / d_std) * (252 ** 0.5), 2) if d_std > 0 else None
    except Exception:
        pass

    context = {
        "portfolio": portfolio,
        "open_positions": list(open_positions[:20]),
        "open_positions_total": open_positions.count(),
        "total_unrealized": total_unrealized,
        "cash_pct": cash_pct,
        "exposure_pct": 100 - cash_pct,
        "win_rate": round(win_rate, 1),
        "n_closed": total_closed,
        "n_winning": len(winning),
        "n_losing": len(losing),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 2),
        "best_trades": best_trades,
        "worst_trades": worst_trades,
        "max_drawdown": (float(latest_snapshot.max_drawdown)
                          if latest_snapshot else 0),
        "sharpe_30d": sharpe,
        "sortino_30d": sortino,
        "equity_points": equity_points,
        "equity_min": min(equity_points) if equity_points else 0,
        "equity_max": max(equity_points) if equity_points else 0,
        "allocation": allocation,
    }
    return render(request, "dashboard/_command_portfolio.html", context)


@login_required
def command_tab_history(request):
    """HISTORY tab — closed trade analytics + per-rule track record."""
    from bot_program.models import AssetBotTrade

    cutoff = timezone.now() - timedelta(days=90)
    closed = (AssetBotTrade.objects
              .filter(config__user=request.user, status="CLOSED",
                       closed_at__gte=cutoff)
              .order_by("-closed_at"))
    n_closed = closed.count()
    total_r = closed.aggregate(s=Sum("realized_r"))["s"] or 0
    n_wins = closed.filter(realized_r__gt=0).count()
    win_rate = (n_wins / n_closed * 100) if n_closed else 0

    by_rule = (closed.exclude(rule_name="")
               .values("rule_name", "asset_class")
               .annotate(n=Count("id"),
                         avg_r=Avg("realized_r"),
                         total_pnl=Sum("pnl"))
               .order_by("-total_pnl")[:20])

    # Cumulative R curve — sort by close time, running sum.
    cum_r_rows = list(
        closed.filter(realized_r__isnull=False)
        .order_by("closed_at")
        .values_list("closed_at", "realized_r")
    )
    cum_r_points: list[float] = []
    running = 0.0
    for _, r in cum_r_rows:
        running += float(r)
        cum_r_points.append(round(running, 4))

    # Rolling 30d win-rate per closed_at date.
    win_rate_points: list[float] = []
    by_date: dict = defaultdict(list)
    for closed_at, r in cum_r_rows:
        by_date[closed_at.date()].append(float(r))
    sorted_dates = sorted(by_date.keys())
    window = 30
    for d in sorted_dates:
        start = d - timedelta(days=window)
        recent = [r for dt in sorted_dates if start <= dt <= d
                   for r in by_date[dt]]
        if recent:
            wr = sum(1 for r in recent if r > 0) / len(recent) * 100
            win_rate_points.append(round(wr, 1))

    # Day-of-week heatmap data: count + avg R per Mon-Sun.
    dow_stats = [{"label": d, "n": 0, "avg_r": 0.0, "total_r": 0.0}
                  for d in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]]
    for closed_at, r in cum_r_rows:
        idx = closed_at.weekday()
        dow_stats[idx]["n"] += 1
        dow_stats[idx]["total_r"] += float(r)
    for d in dow_stats:
        d["avg_r"] = round(d["total_r"] / d["n"], 3) if d["n"] > 0 else 0.0

    # Top rules by Sharpe-like metric (avg_r / stdev).
    rule_stats: dict = defaultdict(list)
    for t in closed.filter(realized_r__isnull=False).only(
            "rule_name", "realized_r"):
        if t.rule_name:
            rule_stats[t.rule_name].append(float(t.realized_r))
    top_rules_sharpe = []
    for name, rs in rule_stats.items():
        if len(rs) < 5:
            continue
        m = sum(rs) / len(rs)
        v = sum((r - m) ** 2 for r in rs) / len(rs)
        s = v ** 0.5
        if s > 0:
            top_rules_sharpe.append({
                "rule_name": name, "n": len(rs),
                "avg_r": round(m, 3), "sharpe": round(m / s, 3),
            })
    top_rules_sharpe.sort(key=lambda r: r["sharpe"], reverse=True)
    top_rules_sharpe = top_rules_sharpe[:5]

    decay_alerts = []
    try:
        from bot_program.models import RuleTrackRecordAlert
        decay_alerts = list(
            RuleTrackRecordAlert.objects
            .filter(user=request.user, resolved_at__isnull=True)
            .order_by("-detected_at")[:10]
        )
    except Exception:
        pass

    context = {
        "n_closed": n_closed,
        "win_rate": round(win_rate, 1),
        "total_r": round(float(total_r), 2),
        "n_wins": n_wins,
        "by_rule": list(by_rule),
        "decay_alerts": decay_alerts,
        "recent_closed": list(closed.select_related("config")[:30]),
        "cum_r_points": cum_r_points,
        "cum_r_min": min(cum_r_points) if cum_r_points else 0,
        "cum_r_max": max(cum_r_points) if cum_r_points else 0,
        "win_rate_points": win_rate_points,
        "dow_stats": dow_stats,
        "dow_max_n": max((d["n"] for d in dow_stats), default=0),
        "top_rules_sharpe": top_rules_sharpe,
    }
    return render(request, "dashboard/_command_history.html", context)


@login_required
def command_tab_bots(request):
    """BOTS tab — per-AssetBotConfig overview with heartbeat + cooldown."""
    from bot_program.models import AssetBotConfig, AssetBotTrade

    configs = list(AssetBotConfig.objects.filter(user=request.user)
                    .order_by("asset_class", "name"))
    rows = []
    now = timezone.now()
    for cfg in configs:
        open_n = AssetBotTrade.objects.filter(config=cfg, status="OPEN").count()
        since_24h = now - timedelta(hours=24)
        closed_24h = AssetBotTrade.objects.filter(
            config=cfg, status="CLOSED", closed_at__gte=since_24h)
        opens_24h = AssetBotTrade.objects.filter(
            config=cfg, opened_at__gte=since_24h).count()
        pnl_24h = closed_24h.aggregate(s=Sum("pnl"))["s"] or Decimal("0")

        last_close = (AssetBotTrade.objects
                       .filter(config=cfg, status="CLOSED",
                                closed_at__isnull=False)
                       .order_by("-closed_at").only("closed_at").first())
        cooldown_remaining_min = 0
        if last_close and (cfg.cool_down_minutes or 0) > 0:
            elapsed_min = (now - last_close.closed_at).total_seconds() / 60
            cooldown_remaining_min = max(
                0, int(cfg.cool_down_minutes - elapsed_min))

        # Liveness from last trade activity (AssetBot beat is Phase 13.5 every 5min).
        last_open_obj = (AssetBotTrade.objects
                         .filter(config=cfg)
                         .order_by("-opened_at").only("opened_at").first())
        candidates = []
        if last_open_obj is not None and last_open_obj.opened_at:
            candidates.append(last_open_obj.opened_at)
        if last_close is not None and last_close.closed_at:
            candidates.append(last_close.closed_at)
        last_activity = max(candidates) if candidates else None
        is_alive = (
            last_activity is not None
            and (now - last_activity).total_seconds() < 6 * 3600
        )

        rows.append({
            "config": cfg,
            "open_count": open_n,
            "opens_24h": opens_24h,
            "closed_24h": closed_24h.count(),
            "pnl_24h": pnl_24h,
            "cooldown_remaining_min": cooldown_remaining_min,
            "last_activity": last_activity,
            "is_alive": is_alive,
        })

    context = {
        "rows": rows,
        "n_configs": len(configs),
        "n_enabled": sum(1 for c in configs if c.enabled),
        "n_live": sum(1 for c in configs if c.enabled and c.mode == "live"),
        "n_alive": sum(1 for r in rows if r["is_alive"]),
    }
    return render(request, "dashboard/_command_bots.html", context)
