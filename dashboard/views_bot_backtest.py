"""Phase-18 bot-trade backtest dashboard.

GET  /bot-backtest/        — list of past runs + new-run form
POST /bot-backtest/run/    — kick off a synchronous run
GET  /bot-backtest/<id>/   — detail view of one run
"""
from datetime import datetime
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST


@login_required
def bot_backtest_list(request):
    from bot_program.models import AssetBotConfig, BotBacktestRun
    configs = list(AssetBotConfig.objects.filter(user=request.user)
                    .order_by("asset_class", "name"))
    runs = list(BotBacktestRun.objects.filter(user=request.user)[:30])
    all_runs = list(BotBacktestRun.objects.filter(user=request.user))

    # Phase 63 — aggregates for the strip.
    # BotBacktestRun.STATUS_CHOICES are "complete" and "error"; this block
    # counted "completed" and "failed", which no row can ever hold. Every
    # aggregate below it was therefore permanently zero and best_run
    # permanently None, on a page whose runs really do complete.
    n_total = len(all_runs)
    n_completed = sum(1 for r in all_runs if r.status == "complete")
    n_failed = sum(1 for r in all_runs if r.status == "error")
    n_running = sum(1 for r in all_runs if r.status in ("pending", "running"))

    # Aggregate stats from completed runs (stats is JSONField)
    completed_runs = [r for r in all_runs if r.status == "complete"]
    avg_trades = (sum(r.stats.get("n_trades", 0) for r in completed_runs)
                   / max(len(completed_runs), 1))
    avg_win_rate = (sum(r.stats.get("win_rate", 0) for r in completed_runs)
                     / max(len(completed_runs), 1))
    avg_total_r = (sum(r.stats.get("total_r", 0) for r in completed_runs)
                    / max(len(completed_runs), 1))

    # Best run by total_r
    best_run = max(completed_runs,
                    key=lambda r: r.stats.get("total_r", 0),
                    default=None)
    last_run = all_runs[0] if all_runs else None

    context = {
        "page_id": "bot_backtest",
        "configs": configs, "runs": runs,
        "n_total_runs": n_total,
        "n_completed": n_completed,
        "n_failed": n_failed,
        "n_running": n_running,
        "n_configs": len(configs),
        "avg_trades": round(avg_trades, 1),
        "avg_win_rate": round(avg_win_rate, 3),
        "avg_total_r": round(avg_total_r, 2),
        "best_run": best_run,
        "last_run": last_run,
    }
    return render(request, "dashboard/bot_backtest.html", context)


@login_required
@require_POST
def bot_backtest_run(request):
    from bot_program.models import AssetBotConfig, BotBacktestRun
    from bot_program.backtest_asset import (
        BacktestParams, run_backtest, serialise_trades,
    )

    try:
        config_id = int(request.POST.get("config_id", "0") or 0)
    except ValueError:
        messages.error(request, "Invalid config_id.")
        return redirect("bot_backtest_list")
    cfg = get_object_or_404(AssetBotConfig, id=config_id, user=request.user)

    try:
        start = datetime.fromisoformat(request.POST.get("start", ""))
        end = datetime.fromisoformat(request.POST.get("end", ""))
    except ValueError:
        messages.error(request, "Invalid start/end ISO date (YYYY-MM-DD).")
        return redirect("bot_backtest_list")

    if timezone.is_naive(start):
        start = timezone.make_aware(start)
    if timezone.is_naive(end):
        end = timezone.make_aware(end)
    if end <= start:
        messages.error(request, "End must be after start.")
        return redirect("bot_backtest_list")

    # Phase 22 — optional realism knobs.
    try:
        tx_cost = float(request.POST.get("transaction_cost_pct", "0") or 0)
        slip = float(request.POST.get("slippage_pct", "0") or 0)
        train_pct = float(request.POST.get("train_pct", "0.7") or 0.7)
    except ValueError:
        tx_cost, slip, train_pct = 0.0, 0.0, 0.7
    walk_forward = request.POST.get("walk_forward") == "on"

    run = BotBacktestRun.objects.create(
        user=request.user, config=cfg,
        config_name_snapshot=cfg.name,
        asset_class_snapshot=cfg.asset_class,
        params={"config_id": cfg.id, "start": start.isoformat(),
                 "end": end.isoformat(),
                 "symbols": list(cfg.symbols or []),
                 "transaction_cost_pct": tx_cost,
                 "slippage_pct": slip,
                 "walk_forward": walk_forward,
                 "train_pct": train_pct},
        status="running", started_at=timezone.now(),
    )
    try:
        params = BacktestParams(
            config_id=cfg.id, start=start, end=end,
            symbols=list(cfg.symbols or []),
            transaction_cost_pct=tx_cost,
            slippage_pct=slip,
            walk_forward=walk_forward,
            train_pct=train_pct,
        )
        result = run_backtest(params)
        run.stats = result.stats or {}
        # Persist walk-forward partitions inside the stats JSON for the detail view.
        if result.train_stats is not None:
            run.stats["walk_forward"] = {
                "split_at": result.walk_forward_split_at.isoformat()
                            if result.walk_forward_split_at else None,
                "train": result.train_stats,
                "test": result.test_stats,
            }
        run.trades_json = serialise_trades(result.trades)
        run.status = "complete"
        run.completed_at = timezone.now()
    except Exception as e:
        run.status = "error"
        run.error = str(e)[:1000]
        run.completed_at = timezone.now()
    run.save()
    # A run that raised still reached this line and still announced "done".
    # The status is right in the database; only the sentence was wrong.
    if run.status == "error":
        messages.error(request, f"Backtest {run.id} failed — {run.error[:200]}")
    else:
        messages.success(request, f"Backtest {run.id} done — "
                                  f"{run.stats.get('n', 0)} trades simulated.")
    return redirect("bot_backtest_detail", run_id=run.id)


@login_required
def bot_backtest_detail(request, run_id: int):
    from bot_program.models import BotBacktestRun
    run = get_object_or_404(BotBacktestRun, id=run_id, user=request.user)
    context = {
        "page_id": "bot_backtest",
        "run": run,
        "trades": run.trades_json or [],
    }
    return render(request, "dashboard/bot_backtest_detail.html", context)
