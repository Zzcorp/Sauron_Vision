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
    from portfolio.services import get_or_create_default_portfolio
    from portfolio.correlation import portfolio_correlation
    from portfolio.kelly_from_history import kelly_inputs_for_rule
    from portfolio.risk_engine import RiskEngine
    from signals.models import Signal

    portfolio = get_or_create_default_portfolio(user=request.user)

    cm = portfolio_correlation(portfolio)
    rules = list(
        Signal.objects
        .filter(is_active=False).exclude(outcome="").exclude(rule_name="")
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

    # Bot drawdown state — best-effort: only present if user has a BotConfig.
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

    # Risk metrics snapshot
    try:
        engine = RiskEngine(portfolio)
        risk_metrics = engine.calculate_risk_metrics()
        var_snapshot = engine.calculate_var()
    except Exception as e:
        risk_metrics = {"error": str(e)}
        var_snapshot = {"error": str(e)}

    context = {
        "page_id": "risk",
        "portfolio": portfolio,
        "correlation": cm.to_dict() if cm.symbols else None,
        "kelly_rows": kelly_rows,
        "bot_state": bot_state,
        "risk_metrics": risk_metrics,
        "var_snapshot": var_snapshot,
        "max_corr_threshold": float(portfolio.max_correlation_threshold or 0.7),
    }
    return render(request, "dashboard/risk_depth.html", context)
