import json
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.views.decorators.http import require_POST
from .models import BotConfig, BinanceAccount, BotTrade, BotScenario
from .forms import BinanceLinkForm, BotConfigForm, ScenarioForm
from .engine.binance_client import BinanceClient
from .engine.runner import run_bot_tick
from .engine.backtest import run_scenario

def _ctx(request, **extra):
    base = {"page_id": "bot_program"}
    base.update(extra); return base

@login_required
def bot_home(request):
    from datetime import timedelta
    from django.utils import timezone
    from decimal import Decimal
    cfg, _ = BotConfig.objects.get_or_create(user=request.user)
    acct = getattr(request.user, "binance_account", None)

    all_closed = BotTrade.objects.filter(config=cfg, status="CLOSED")
    open_trades = BotTrade.objects.filter(config=cfg, status="OPEN")[:20]
    closed_trades = all_closed[:30]
    scenarios = BotScenario.objects.filter(user=request.user)[:20]

    equity = float(cfg.capital_usdt)
    pnl_total = float(sum((t.pnl_usdt for t in all_closed), Decimal(0)))
    total_trades = all_closed.count()
    wins = all_closed.filter(pnl_usdt__gt=0).count()
    losses = all_closed.filter(pnl_usdt__lt=0).count()
    win_rate = round((wins / total_trades * 100), 1) if total_trades else 0

    day_ago = timezone.now() - timedelta(hours=24)
    day_closed = all_closed.filter(closed_at__gte=day_ago)
    pnl_24h = float(sum((t.pnl_usdt for t in day_closed), Decimal(0)))
    trades_24h = day_closed.count()

    week_ago = timezone.now() - timedelta(days=7)
    week_closed = all_closed.filter(closed_at__gte=week_ago)
    pnl_7d = float(sum((t.pnl_usdt for t in week_closed), Decimal(0)))

    open_exposure = float(sum((t.qty * t.entry_price for t in open_trades), Decimal(0)))

    best = all_closed.order_by("-pnl_usdt").first()
    worst = all_closed.order_by("pnl_usdt").first()

    spark_qs = list(all_closed.order_by("closed_at").values_list("pnl_usdt", flat=True)[:200])
    spark = []
    running = 0
    for v in spark_qs:
        running += float(v)
        spark.append(round(running, 2))

    last_event = (all_closed.order_by("-closed_at").values_list("closed_at", flat=True).first()
                  or BotTrade.objects.filter(config=cfg).order_by("-opened_at")
                     .values_list("opened_at", flat=True).first())

    return render(request, "bot_program/home.html", _ctx(request,
        cfg=cfg, acct=acct, open_trades=open_trades,
        closed_trades=closed_trades, scenarios=scenarios,
        equity=equity, pnl_total=pnl_total, pnl_24h=pnl_24h, pnl_7d=pnl_7d,
        total_trades=total_trades, trades_24h=trades_24h,
        wins=wins, losses=losses, win_rate=win_rate,
        open_exposure=open_exposure, best_trade=best, worst_trade=worst,
        spark_data=spark, last_event=last_event,
        weights=cfg.normalized_weights()))

@login_required
def link_binance(request):
    acct, _ = BinanceAccount.objects.get_or_create(user=request.user)
    if request.method == "POST":
        form = BinanceLinkForm(request.POST, instance=acct)
        if form.is_valid():
            acct = form.save(commit=False)
            acct.set_credentials(form.cleaned_data["api_key"], form.cleaned_data["api_secret"])
            # Test
            cli = BinanceClient(form.cleaned_data["api_key"], form.cleaned_data["api_secret"], acct.testnet)
            if cli.ping():
                acct.connected = True
                try:
                    acct.last_balance_usdt = cli.balance_usdt()
                except Exception: pass
                acct.save()
                messages.success(request, "Binance account linked ✓")
            else:
                messages.error(request, "Could not reach Binance with those keys")
            return redirect("bot_home")
    else:
        form = BinanceLinkForm(instance=acct)
    return render(request, "bot_program/link.html", _ctx(request, form=form, acct=acct))

@login_required
def configure_bot(request):
    cfg, _ = BotConfig.objects.get_or_create(user=request.user)
    if request.method == "POST":
        form = BotConfigForm(request.POST, instance=cfg)
        if form.is_valid():
            form.save(); messages.success(request, "Configuration saved.")
            return redirect("bot_home")
    else:
        form = BotConfigForm(instance=cfg)
    return render(request, "bot_program/configure.html", _ctx(request, form=form, cfg=cfg))

@login_required
@require_POST
def toggle_bot(request):
    cfg, _ = BotConfig.objects.get_or_create(user=request.user)
    # Require PIN to arm live mode
    if not cfg.enabled and cfg.mode == "live":
        pin = request.POST.get("pin", "")
        prof = getattr(request.user, "trader_profile", None)
        from django.contrib.auth.hashers import check_password
        if not (prof and prof.access_pin_hash and check_password(pin, prof.access_pin_hash)):
            messages.error(request, "PIN required to arm LIVE mode.")
            return redirect("bot_home")
    cfg.enabled = not cfg.enabled
    cfg.save()
    messages.info(request, f"Bot {'ENABLED' if cfg.enabled else 'DISABLED'}")
    return redirect("bot_home")

@login_required
@require_POST
def run_tick_now(request):
    run_bot_tick(request.user.id)
    messages.info(request, "Bot tick executed.")
    return redirect("bot_home")

@login_required
def scenarios_list(request):
    scenarios = BotScenario.objects.filter(user=request.user)
    return render(request, "bot_program/scenarios.html", _ctx(request, scenarios=scenarios))

@login_required
def scenario_new(request):
    if request.method == "POST":
        form = ScenarioForm(request.POST)
        if form.is_valid():
            s = form.save(commit=False); s.user = request.user; s.save()
            try:
                run_scenario(s)
                messages.success(request, f"Scenario ran. Return: {s.total_return_pct}%")
            except Exception as e:
                messages.error(request, f"Scenario failed: {e}")
            return redirect("scenario_detail", pk=s.id)
    else:
        form = ScenarioForm(initial={"symbols":["BTCUSDT","ETHUSDT"]})
    return render(request, "bot_program/scenario_new.html", _ctx(request, form=form))

@login_required
def scenario_detail(request, pk):
    s = get_object_or_404(BotScenario, pk=pk, user=request.user)
    return render(request, "bot_program/scenario_detail.html", _ctx(request, s=s))
