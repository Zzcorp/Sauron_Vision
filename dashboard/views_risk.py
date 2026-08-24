"""Risk-depth dashboard — Phase 2.

Surfaces the new Phase-2 layer: portfolio correlation matrix, Kelly inputs
derived from realized signal history, drawdown throttle state for the bot,
and a sample run of the unified risk gate.
"""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def risk_dashboard(request):
    """Render /risk/ — comprehensive risk-depth view."""
    return _render_risk(request, live_only=False)


@login_required
def risk_dashboard_live(request):
    """The moving regions of /risk/, re-rendered — the portfolio page's
    contract: same view body, same template, a bare shell, so a refreshed
    cell can never say something the first render would not have said.
    The page asks on the fill events the shell re-dispatches plus the
    slow sweep — which falls back to a 20s catch-up poll whenever the
    socket is down — so the heavy quartet below is served from a short
    cache keyed to the open-position set: a fill changes the set and
    recomputes instantly; everything else rides the TTL."""
    return _render_risk(request, live_only=True)


RISK_DEPTH_TTL = 45  # seconds — at most one recompute per up-sweep, and
#   N open tabs (or the 20s offline cadence) collapse to a single pass.


def _render_risk(request, live_only):
    import hashlib

    from django.core.cache import cache

    from portfolio.models import Position
    from portfolio.services import get_or_create_default_portfolio

    portfolio = get_or_create_default_portfolio(user=request.user)

    # The heavy quartet — correlation matrix, Kelly table, risk metrics,
    # VaR — reads daily bars and 180 days of realized history. Nothing in
    # it moves on a 20s clock, but the live twin IS on one whenever the
    # socket is down, and each uncached pass re-scanned months of
    # PriceData per open position. Key the cache to the open-position
    # set: a fill changes the set and recomputes instantly.
    open_ids = tuple(
        Position.objects.filter(portfolio=portfolio, closed_at__isnull=True)
        .order_by("id").values_list("id", flat=True)
    )
    fingerprint = hashlib.md5(repr(open_ids).encode()).hexdigest()[:16]
    cache_key = f"risk_depth:{portfolio.id}:{fingerprint}"
    heavy = cache.get(cache_key)
    if heavy is None:
        heavy = _compute_heavy(portfolio)
        cache.set(cache_key, heavy, RISK_DEPTH_TTL)

    # Bot drawdown state — best-effort, per-user live state: cheap enough
    # to read fresh every pass, and stale drawdown throttle state is
    # exactly what this page exists to not show.
    bot_state = None
    try:
        from bot_program.models import BotConfig
        from bot_program.engine.risk import RiskManager
        cfg = BotConfig.objects.filter(user=request.user).first()
        if cfg:
            bot_state = RiskManager(cfg).state_snapshot()
            bot_state["mode"] = cfg.mode
    except Exception:
        bot_state = None

    context = {
        "page_id": "risk",
        "live_only": live_only,
        # The live twin extends the bare shell — same template, same
        # formatter, none of base.html's chrome in the swap payload.
        "base_template": ("dashboard/_live_shell.html" if live_only
                          else "base.html"),
        "portfolio": portfolio,
        "correlation": heavy["correlation"],
        "kelly_rows": heavy["kelly_rows"],
        "bot_state": bot_state,
        "risk_metrics": heavy["risk_metrics"],
        "var_snapshot": heavy["var_snapshot"],
        "max_corr_threshold": float(portfolio.max_correlation_threshold or 0.7),
    }
    return render(request, "dashboard/risk_depth.html", context)


def _compute_heavy(portfolio):
    """One pass of the expensive layer — everything below is cached."""
    from portfolio.correlation import portfolio_correlation
    from portfolio.kelly_from_history import kelly_inputs_for_rule
    from portfolio.risk_engine import RiskEngine
    from signals.models import Signal

    cm = portfolio_correlation(portfolio)
    # order_by("rule_name") clears Signal's -created_at Meta ordering so the
    # DISTINCT really dedups rule names — before the [:30] cap, not after.
    rules = list(
        Signal.objects
        .filter(is_active=False).exclude(outcome="").exclude(rule_name="")
        .order_by("rule_name")
        .values_list("rule_name", flat=True).distinct()[:30]
    )
    kelly_rows = []
    for rn in rules:
        inputs = kelly_inputs_for_rule(rn, days=180)
        if inputs["n"] == 0:
            continue
        # Inline the same Kelly calc the PositionSizer does, so we don't need a portfolio dep here.
        b = inputs["avg_win_pct"] / max(inputs["avg_loss_pct"], 1e-6)
        p = inputs["win_rate"]
        kelly = (b * p - (1 - p)) / b if b > 0 else 0
        kelly_rows.append({
            "rule_name": rn,
            "win_rate": inputs["win_rate"],
            "avg_win_pct": inputs["avg_win_pct"],
            "avg_loss_pct": inputs["avg_loss_pct"],
            "n": inputs["n"],
            "is_empirical": inputs["is_empirical"],
            "full_kelly": round(max(0, min(kelly, 1)), 4),
            "half_kelly": round(max(0, min(kelly / 2, 0.25)), 4),
        })
    kelly_rows.sort(key=lambda r: -r["n"])

    # Risk metrics snapshot
    try:
        engine = RiskEngine(portfolio)
        risk_metrics = engine.calculate_risk_metrics()
        var_snapshot = engine.calculate_var()
    except Exception as e:
        risk_metrics = {"error": str(e)}
        var_snapshot = {"error": str(e)}

    return {
        "correlation": cm.to_dict() if cm.symbols else None,
        "kelly_rows": kelly_rows,
        "risk_metrics": risk_metrics,
        "var_snapshot": var_snapshot,
    }
