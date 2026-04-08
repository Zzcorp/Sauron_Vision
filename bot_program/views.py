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
    cfg, _ = BotConfig.objects.get_or_create(user=request.user)
    acct = getattr(request.user, "binance_account", None)
    open_trades = BotTrade.objects.filter(config=cfg, status="OPEN")[:20]
    closed_trades = BotTrade.objects.filter(config=cfg, status="CLOSED")[:30]
    scenarios = BotScenario.objects.filter(user=request.user)[:20]
    equity = float(cfg.capital_usdt)
    pnl_total = sum(float(t.pnl_usdt) for t in BotTrade.objects.filter(config=cfg, status="CLOSED"))
    return render(request, "bot_program/home.html", _ctx(request,
        cfg=cfg, acct=acct, open_trades=open_trades,
        closed_trades=closed_trades, scenarios=scenarios,
        equity=equity, pnl_total=pnl_total,
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
