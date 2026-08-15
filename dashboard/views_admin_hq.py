"""Admin HQ — run-now endpoints + broker credential forms.

Single shared shape for every run-now endpoint:
  - POST-only
  - superuser-only
  - calls the underlying Celery task synchronously (or via .delay() if Celery is alive)
  - shows a Django messages flash
  - redirects to the admin dashboard
"""
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, HttpResponseNotAllowed
from django.shortcuts import redirect
from django.utils.decorators import method_decorator

logger = logging.getLogger(__name__)


# ── helpers ─────────────────────────────────────────────────────────────────

def _admin_only(view):
    """Decorator: superuser-only, POST-only."""
    from functools import wraps
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_superuser:
            return HttpResponseForbidden("Superuser access required.")
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])
        try:
            return view(request, *args, **kwargs)
        except Exception as e:
            logger.exception("admin HQ action failed: %s", e)
            messages.error(request, f"Action failed: {e}")
            return redirect("admin_dashboard")
    return wrapper


def _broker_ping(build_client, label: str) -> bool:
    """True iff the freshly-built client's authenticated ping succeeds.

    `connected` used to be set unconditionally on save — it meant "written
    down", not "these work", and stayed True for keys that had never once
    reached the broker. Every client's ping() returns a plain bool and
    never raises; this wrapper keeps that guarantee against constructor
    surprises too.

    Two IBKR-specific realities are handled here rather than in the view:
    ib_insync needs an asyncio event loop and web requests run in worker
    threads that have none (without this, the ping raised before any
    socket I/O and verification could never succeed under threaded
    serving); and a successful ping leaves a live TWS connection holding
    the client-id slot, which would make every LATER router connection
    fail with error 326 — so the client is always disconnected.
    """
    import asyncio
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    client = None
    try:
        client = build_client()
        return bool(client.ping())
    except Exception as e:  # noqa: BLE001
        logger.warning("[hq] %s credential verification errored: %s", label, e)
        return False
    finally:
        disconnect = getattr(client, "disconnect", None)
        if callable(disconnect):
            try:
                disconnect()
            except Exception:  # noqa: BLE001
                pass


def _pin_ok(request) -> bool:
    """True iff the acting user supplied their correct trading PIN.

    Mirrors the legacy crypto bot's arming check (bot_program.views.toggle_bot):
    a PIN is required to move any bot into LIVE mode so real-money trading can't
    be armed by a click alone.
    """
    from django.contrib.auth.hashers import check_password
    pin = request.POST.get("pin", "")
    prof = getattr(request.user, "trader_profile", None)
    return bool(prof and prof.access_pin_hash and check_password(pin, prof.access_pin_hash))


@_admin_only
def flatten_all_positions(request):
    """The real kill switch: disable every bot AND close every open position.

    This had no user interface at all. `execute_kill_switch` and its endpoint
    both existed and were reachable from nothing, while the only red button
    on the platform — STOP ALL — toggles `platform_master`, which stops the
    SCHEDULER and closes nothing. Pressing it while holding open trades is
    the worst of both worlds: the positions stay live at the broker and the
    bot that would have honoured their stops is now switched off.

    Gated on the trading PIN. It is irreversible, it moves real money, and it
    is exactly the action that should not be one click from a stray cursor —
    the same bar the platform already sets for arming a bot live.
    """
    from django.contrib import messages
    from django.shortcuts import redirect
    from bot_program.engine.kill_switch import execute_kill_switch

    if not _pin_ok(request):
        messages.error(request, "Trading PIN required to flatten positions. "
                                "Nothing was closed.")
        return redirect("admin_dashboard")

    reason = (request.POST.get("reason") or "manual kill switch").strip()[:200]
    try:
        results = execute_kill_switch(user=request.user, reason=reason)
    except Exception as e:
        logger.exception("[kill switch] failed for %s: %s", request.user, e)
        messages.error(request, f"Kill switch FAILED: {e}. Check your broker "
                                f"positions manually before assuming they are flat.")
        return redirect("admin_dashboard")

    closed = (results.get("positions_closed", 0)
              + results.get("asset_positions_closed", 0)
              + results.get("portfolio_positions_closed", 0))
    disabled = (results.get("bots_disabled", 0)
                + results.get("asset_bots_disabled", 0))
    errs = results.get("errors") or []

    msg = f"Kill switch: {disabled} bot(s) disabled, {closed} position(s) closed."
    if errs:
        # Never report a clean sweep when some closes failed — the operator
        # would stop looking, and a position they believe is flat is the most
        # expensive kind of wrong.
        messages.error(request, msg + f" {len(errs)} FAILED — these may still "
                                      f"be open at the broker: {'; '.join(str(e)[:120] for e in errs[:3])}")
    else:
        messages.success(request, msg)
    return redirect("admin_dashboard")



def _run_task(task_callable, label: str, request):
    """Run a Celery task synchronously and flash the result."""
    try:
        result = task_callable()
        if isinstance(result, dict) and result.get("status") == "skipped":
            messages.warning(request, f"{label}: skipped — {result.get('reason', 'gated')}")
        else:
            messages.success(request, f"{label}: ok")
    except Exception as e:
        logger.exception("%s failed", label)
        messages.error(request, f"{label} failed: {e}")


# ── run-now endpoints ───────────────────────────────────────────────────────

@_admin_only
def run_signal_scan(request):
    from signals.tasks import run_signal_scan as task
    _run_task(task, "Signal scan", request)
    return redirect("admin_dashboard")


@_admin_only
def run_smc_lifecycle(request):
    from signals.tasks_lifecycle import run_smc_lifecycle as task
    _run_task(task, "SMC lifecycle pass", request)
    return redirect("admin_dashboard")


@_admin_only
def run_grade_signals(request):
    """Print the grade_signals digest to logs. (No DB writes — pure read.)"""
    from io import StringIO
    from django.core.management import call_command
    buf = StringIO()
    try:
        call_command("grade_signals", stdout=buf)
        messages.success(request, "grade_signals digest emitted to logs.")
    except Exception as e:
        messages.error(request, f"grade_signals failed: {e}")
    return redirect("admin_dashboard")


@_admin_only
def run_decay_investigation(request):
    from ai_agents.tasks import investigate_decaying_rules as task
    _run_task(task, "Decay investigation", request)
    return redirect("admin_dashboard")


@_admin_only
def run_daily_snapshot(request):
    from portfolio.tasks import create_daily_snapshot as task
    _run_task(task, "Daily portfolio snapshot", request)
    return redirect("admin_dashboard")


@_admin_only
def run_recalc_exposure(request):
    from portfolio.tasks import recalculate_exposure as task
    _run_task(task, "Recalculate exposure", request)
    return redirect("admin_dashboard")


@_admin_only
def run_nightly_cleanup(request):
    from market_data.cleanup_tasks import nightly_cleanup_all as task
    _run_task(task, "Nightly cleanup", request)
    return redirect("admin_dashboard")


@_admin_only
def run_full_universe_scan(request):
    from signals.tasks import run_full_universe_scan as task
    _run_task(task, "Full universe signal scan", request)
    return redirect("admin_dashboard")


@_admin_only
def run_seed_components(request):
    """Re-seed PlatformComponents (idempotent — only adds new ones)."""
    from core.platform_control import seed_components
    n = seed_components()
    messages.success(request, f"seed_components: {n} new component(s) registered.")
    return redirect("admin_dashboard")


# ── broker credential forms ─────────────────────────────────────────────────

@_admin_only
def save_oanda_credentials(request):
    """Create or update OANDAAccount for a target user.

    Required POST fields: target_username, oanda_api_key, oanda_account_id, practice (checkbox).
    """
    from django.contrib.auth.models import User
    from bot_program.models import OANDAAccount

    target_username = request.POST.get("target_username", "").strip()
    api_key = request.POST.get("oanda_api_key", "").strip()
    account_id = request.POST.get("oanda_account_id", "").strip()
    # Unchecked HTML checkbox = key absent from POST → False (live).
    # The template defaults to checked so the safe path is the obvious one.
    practice = request.POST.get("practice") == "on"

    if not (target_username and api_key and account_id):
        messages.error(request, "OANDA: target_username, api_key and account_id are all required.")
        return redirect("admin_dashboard")

    try:
        user = User.objects.get(username=target_username)
    except User.DoesNotExist:
        messages.error(request, f"OANDA: user '{target_username}' not found.")
        return redirect("admin_dashboard")

    acct, _ = OANDAAccount.objects.get_or_create(user=user)
    acct.set_credentials(api_key, account_id)
    acct.practice = practice
    env = "practice" if practice else "live"
    # OANDA's ping() is an authenticated account-summary call, so this
    # verifies the key AND the account id in one round trip.
    from bot_program.engine.oanda_client import OANDATrader
    acct.connected = _broker_ping(
        lambda: OANDATrader(api_key, account_id, env=env), "OANDA")
    if acct.connected:
        from django.utils import timezone
        acct.last_sync = timezone.now()
    acct.save()
    if acct.connected:
        messages.success(request, f"OANDA credentials saved and verified "
                                  f"for {target_username} ({env}).")
    else:
        messages.warning(request, f"OANDA credentials saved for "
                                  f"{target_username} ({env}) but NOT "
                                  f"verified — the account-summary call "
                                  f"failed. Check the key and account id.")
    return redirect("admin_dashboard")


@_admin_only
def save_alpaca_credentials(request):
    from django.contrib.auth.models import User
    from bot_program.models import AlpacaAccount

    target_username = request.POST.get("target_username", "").strip()
    api_key = request.POST.get("alpaca_api_key", "").strip()
    api_secret = request.POST.get("alpaca_api_secret", "").strip()
    # Same convention as OANDA: unchecked = absent = live.
    paper = request.POST.get("paper") == "on"

    if not (target_username and api_key and api_secret):
        messages.error(request, "Alpaca: target_username, api_key and api_secret are all required.")
        return redirect("admin_dashboard")

    try:
        user = User.objects.get(username=target_username)
    except User.DoesNotExist:
        messages.error(request, f"Alpaca: user '{target_username}' not found.")
        return redirect("admin_dashboard")

    acct, _ = AlpacaAccount.objects.get_or_create(user=user)
    acct.set_credentials(api_key, api_secret)
    acct.paper = paper
    env = "paper" if paper else "live"
    # Alpaca's ping() hits /v2/account with the submitted keys — a real
    # credential check, not a reachability check.
    from bot_program.engine.alpaca_client import AlpacaTrader
    acct.connected = _broker_ping(
        lambda: AlpacaTrader(api_key, api_secret, env=env), "Alpaca")
    if acct.connected:
        from django.utils import timezone
        acct.last_sync = timezone.now()
    acct.save()
    if acct.connected:
        messages.success(request, f"Alpaca credentials saved and verified "
                                  f"for {target_username} ({env}).")
    else:
        messages.warning(request, f"Alpaca credentials saved for "
                                  f"{target_username} ({env}) but NOT "
                                  f"verified — the account call failed. "
                                  f"Check the key pair.")
    return redirect("admin_dashboard")


@_admin_only
def save_ibkr_credentials(request):
    """Create or update IBKRAccount for a target user — Phase-14.

    Required POST: target_username, ibkr_account_id.
    Optional:
        ibkr_host (default 127.0.0.1)
        ibkr_port (default 7497 paper TWS)
        ibkr_client_id (default 1)
        paper (checkbox; default off = live, but most users will check it
               since 7497 is the paper TWS port)
        primary_for_stocks, primary_for_forex, primary_for_options,
        primary_for_commodity (checkboxes — opt-in routing override)
    """
    from django.contrib.auth.models import User
    from bot_program.models import IBKRAccount

    target_username = request.POST.get("target_username", "").strip()
    account_id = request.POST.get("ibkr_account_id", "").strip()
    host = request.POST.get("ibkr_host", "").strip() or "127.0.0.1"
    try:
        port = int(request.POST.get("ibkr_port", "7497") or 7497)
        client_id = int(request.POST.get("ibkr_client_id", "1") or 1)
    except ValueError:
        messages.error(request, "IBKR: port and client_id must be integers.")
        return redirect("admin_dashboard")

    paper = request.POST.get("paper") == "on"
    primary_stocks = request.POST.get("primary_for_stocks") == "on"
    primary_forex = request.POST.get("primary_for_forex") == "on"
    primary_options = request.POST.get("primary_for_options") == "on"
    primary_commodity = request.POST.get("primary_for_commodity") == "on"
    primary_cfd = request.POST.get("primary_for_cfd") == "on"

    if not (target_username and account_id):
        messages.error(request, "IBKR: target_username and account_id are required.")
        return redirect("admin_dashboard")

    try:
        user = User.objects.get(username=target_username)
    except User.DoesNotExist:
        messages.error(request, f"IBKR: user '{target_username}' not found.")
        return redirect("admin_dashboard")

    acct, _ = IBKRAccount.objects.get_or_create(user=user)
    acct.set_credentials(account_id)
    acct.host = host
    acct.port = port
    acct.client_id = client_id
    acct.paper = paper
    acct.is_primary_for_stocks = primary_stocks
    acct.is_primary_for_forex = primary_forex
    acct.is_primary_for_options = primary_options
    acct.is_primary_for_commodity = primary_commodity
    acct.is_primary_for_cfd = primary_cfd
    # IBKR's ping() proves the TWS/Gateway socket answers — NOT that the
    # account id is valid (that is all ib_insync exposes cheaply). The
    # message says which of the two was checked.
    from bot_program.engine.ibkr_client import IBKRTrader
    acct.connected = _broker_ping(
        lambda: IBKRTrader(host=host, port=port, client_id=client_id,
                           account_id=account_id, paper=paper), "IBKR")
    if acct.connected:
        from django.utils import timezone
        acct.last_sync = timezone.now()
    acct.save()

    env = "paper" if paper else "live"
    if acct.connected:
        messages.success(
            request,
            f"IBKR credentials saved for {target_username} — TWS reachable "
            f"at {host}:{port} ({env}, client_id={client_id}).",
        )
    else:
        messages.warning(
            request,
            f"IBKR credentials saved for {target_username} but TWS was NOT "
            f"reachable at {host}:{port} — start TWS/Gateway and re-save to "
            f"verify. (This checks the socket, not the account id.)",
        )
    return redirect("admin_dashboard")


@_admin_only
def hq_create_asset_bot(request):
    """Create or update an AssetBotConfig for the current user."""
    import json as json_mod
    from bot_program.models import AssetBotConfig

    asset_class = request.POST.get("asset_class", "").strip()
    name = request.POST.get("name", "").strip() or "Asset Bot"
    if asset_class not in ("stock", "forex", "commodity", "options", "cfd"):
        messages.error(request, "asset_class must be stock|forex|commodity|options|cfd")
        return redirect("admin_dashboard")

    try:
        symbols = json_mod.loads(request.POST.get("symbols", "[]") or "[]")
        extras = json_mod.loads(request.POST.get("extras", "{}") or "{}")
    except Exception as e:
        messages.error(request, f"Invalid JSON: {e}")
        return redirect("admin_dashboard")

    try:
        capital = float(request.POST.get("capital", "10000"))
        position_pct = float(request.POST.get("position_size_pct", "2"))
        max_concurrent = int(request.POST.get("max_concurrent_positions", "5"))
        max_loss_pct = float(request.POST.get("max_daily_loss_pct", "2"))
        sl_pct = float(request.POST.get("stop_loss_pct", "1.5"))
        tp_pct = float(request.POST.get("take_profit_pct", "3"))
        entry_min = float(request.POST.get("entry_score_min", "0.6"))
    except ValueError as e:
        messages.error(request, f"Invalid numeric field: {e}")
        return redirect("admin_dashboard")

    # Setting LIVE mode requires the trading PIN — otherwise an already-enabled
    # paper config could be flipped to live (and armed) without one.
    mode = request.POST.get("mode", "paper")
    if mode == "live" and not _pin_ok(request):
        messages.error(request, "PIN required to configure a LIVE asset bot.")
        return redirect("admin_dashboard")

    cfg, created = AssetBotConfig.objects.update_or_create(
        user=request.user, asset_class=asset_class, name=name,
        defaults={
            "symbols": symbols, "capital": capital,
            "base_currency": request.POST.get("base_currency", "USD"),
            "mode": mode,
            "position_size_pct": position_pct,
            "max_concurrent_positions": max_concurrent,
            "max_daily_loss_pct": max_loss_pct,
            "stop_loss_pct": sl_pct, "take_profit_pct": tp_pct,
            "entry_score_min": entry_min,
            "extras": extras,
        },
    )
    messages.success(
        request,
        f"{'Created' if created else 'Updated'} AssetBotConfig "
        f"'{cfg.name}' ({cfg.asset_class}, {cfg.mode})."
    )
    return redirect("admin_dashboard")


@_admin_only
def hq_toggle_asset_bot(request):
    from bot_program.models import AssetBotConfig
    cfg_id = request.POST.get("config_id")
    cfg = AssetBotConfig.objects.filter(id=cfg_id).first()
    if not cfg:
        messages.error(request, "AssetBotConfig not found")
        return redirect("admin_dashboard")
    # Require the trading PIN to ARM a live-mode bot (parity with the legacy
    # crypto bot). Disabling never needs a PIN — stopping must stay frictionless.
    arming_live = (not cfg.enabled) and cfg.mode == "live"
    if arming_live and not _pin_ok(request):
        messages.error(request, "PIN required to arm a LIVE asset bot.")
        return redirect("admin_dashboard")
    cfg.enabled = not cfg.enabled
    cfg.save(update_fields=["enabled", "updated_at"])
    messages.success(
        request,
        f"AssetBot '{cfg.name}' ({cfg.asset_class}) "
        f"{'ENABLED' if cfg.enabled else 'DISABLED'}."
    )
    return redirect("admin_dashboard")


@_admin_only
def hq_run_asset_bot(request):
    """Manually run a single AssetBotConfig's tick."""
    from bot_program.asset_engine.runner import run_asset_bot_tick
    cfg_id = request.POST.get("config_id")
    try:
        cfg_id = int(cfg_id)
    except (TypeError, ValueError):
        messages.error(request, "Invalid config_id")
        return redirect("admin_dashboard")
    try:
        result = run_asset_bot_tick(cfg_id)
    except Exception as e:
        messages.error(request, f"Tick failed: {e}")
        return redirect("admin_dashboard")
    if result.get("status") == "ok":
        messages.success(
            request,
            f"AssetBot tick: {result.get('managed', 0)} closed · "
            f"{len(result.get('opened', []))} opened · "
            f"gate: {result.get('gate_reason', '?')}"
        )
    else:
        messages.warning(request, f"Tick: {result.get('reason') or result.get('status')}")
    return redirect("admin_dashboard")


@_admin_only
def hq_run_all_asset_bots(request):
    """Run a tick for every enabled AssetBotConfig."""
    from bot_program.asset_engine.runner import run_all_asset_bots
    try:
        result = run_all_asset_bots()
        messages.success(
            request,
            f"Ticked {result['configs_ticked']} enabled AssetBotConfig(s)."
        )
    except Exception as e:
        messages.error(request, f"Run failed: {e}")
    return redirect("admin_dashboard")


@_admin_only
def hq_fire_test_event(request):
    """Manually fire an event into the Phase-12 dispatcher.

    Form fields:
      event_type — required (e.g. 'price_tick', 'news')
      payload    — JSON dict (e.g. {"symbol": "AAPL", "last": 200.50})
    """
    import json as json_mod
    from signals.fast_rules import dispatch_event

    event_type = request.POST.get("event_type", "").strip()
    if not event_type:
        messages.error(request, "event_type is required")
        return redirect("admin_dashboard")

    raw = request.POST.get("payload", "{}").strip() or "{}"
    try:
        payload = json_mod.loads(raw)
    except Exception as e:
        messages.error(request, f"Invalid payload JSON: {e}")
        return redirect("admin_dashboard")

    try:
        result = dispatch_event(event_type, payload, source="admin")
        messages.success(
            request,
            f"Dispatched {event_type}: {result['rules_fired']}/{result['rules_evaluated']} "
            f"rules fired in {result['elapsed_ms']:.1f}ms · "
            f"{len(result['signal_ids'])} signal(s) created."
        )
    except Exception as e:
        messages.error(request, f"Dispatch failed: {e}")
    return redirect("admin_dashboard")


@_admin_only
def hq_run_pattern_miner(request):
    """Trigger an immediate pattern-mining pass."""
    from signals.pattern_miner import mine_all_active, expire_stale_discoveries
    try:
        expired = expire_stale_discoveries()
        result = mine_all_active()
        messages.success(
            request,
            f"Pattern mining: {result['discoveries_created']} new discoveries "
            f"across {result['instruments_scanned']} instruments "
            f"({expired} stale expired)."
        )
    except Exception as e:
        messages.error(request, f"Pattern mining failed: {e}")
    return redirect("admin_dashboard")


@_admin_only
def hq_activate_discovery(request):
    """Promote a DiscoveredSetup to a draft OpportunitySetup (is_active=False)."""
    from signals.pattern_miner import activate_discovered_setup, MiningError
    try:
        ds_id = int(request.POST.get("discovery_id", "0"))
    except ValueError:
        messages.error(request, "Invalid discovery_id")
        return redirect("admin_dashboard")
    try:
        setup = activate_discovered_setup(ds_id, request.user)
        messages.success(
            request,
            f"Activated discovery #{ds_id} → setup '{setup.name}' "
            f"(is_active=False; enable from /opportunities/ when ready)."
        )
    except MiningError as e:
        messages.error(request, f"Activation: {e}")
    return redirect("admin_dashboard")


@_admin_only
def hq_reject_discovery(request):
    from signals.pattern_miner import reject_discovered_setup, MiningError
    try:
        ds_id = int(request.POST.get("discovery_id", "0"))
    except ValueError:
        messages.error(request, "Invalid discovery_id")
        return redirect("admin_dashboard")
    try:
        ds = reject_discovered_setup(ds_id, request.user)
        messages.success(request, f"Rejected DiscoveredSetup #{ds.id}.")
    except MiningError as e:
        messages.error(request, f"Rejection: {e}")
    return redirect("admin_dashboard")


@_admin_only
def hq_run_opportunity_scan(request):
    """Trigger an immediate scan of all active OpportunitySetups."""
    from signals.opportunity_scanner import scan_all_setups
    try:
        result = scan_all_setups()
        messages.success(
            request,
            f"Opportunity scan: {result['matches']} match(es) "
            f"across {result['evaluations']} evaluations "
            f"({result['setups_scanned']} setups × {result['instruments_scanned']} instruments)."
        )
    except Exception as e:
        messages.error(request, f"Scan failed: {e}")
    return redirect("admin_dashboard")


@_admin_only
def hq_resolve_opportunities(request):
    from signals.opportunity_scanner import resolve_pending_flags
    try:
        result = resolve_pending_flags()
        messages.success(
            request,
            f"Flag resolution: hit={result['hit']} miss={result['miss']} "
            f"neutral={result['neutral']} expired={result['expired']} "
            f"skipped={result['skipped']}"
        )
    except Exception as e:
        messages.error(request, f"Resolution failed: {e}")
    return redirect("admin_dashboard")


@_admin_only
def hq_create_opportunity_setup(request):
    """Create a new OpportunitySetup from the admin form."""
    import json as json_mod
    from signals.models import OpportunitySetup

    name = request.POST.get("name", "").strip()
    if not name:
        messages.error(request, "Setup name is required.")
        return redirect("admin_dashboard")

    if OpportunitySetup.objects.filter(name=name).exists():
        messages.error(request, f"A setup named '{name}' already exists.")
        return redirect("admin_dashboard")

    try:
        conditions = json_mod.loads(request.POST.get("conditions", "[]"))
        if not isinstance(conditions, list):
            raise ValueError("conditions must be a JSON list")
    except Exception as e:
        messages.error(request, f"Invalid conditions JSON: {e}")
        return redirect("admin_dashboard")

    try:
        asset_classes = json_mod.loads(request.POST.get("asset_classes", "[]"))
        sizing = json_mod.loads(request.POST.get("sizing", "{}"))
    except Exception as e:
        messages.error(request, f"Invalid asset_classes/sizing JSON: {e}")
        return redirect("admin_dashboard")

    direction = request.POST.get("direction", "bullish")
    description = request.POST.get("description", "")
    try:
        min_score = float(request.POST.get("min_match_score", "0.7"))
        horizon = int(request.POST.get("suggested_horizon_days", "5"))
    except ValueError:
        messages.error(request, "min_match_score / suggested_horizon_days must be numbers.")
        return redirect("admin_dashboard")

    setup = OpportunitySetup.objects.create(
        name=name, description=description, direction=direction,
        asset_classes=asset_classes, conditions=conditions,
        min_match_score=min_score, suggested_horizon_days=horizon,
        sizing=sizing, is_active=True, created_by=request.user,
    )
    messages.success(request, f"Created OpportunitySetup '{setup.name}'.")
    return redirect("admin_dashboard")


@_admin_only
def hq_toggle_opportunity_setup(request):
    from signals.models import OpportunitySetup
    setup_id = request.POST.get("setup_id")
    setup = OpportunitySetup.objects.filter(id=setup_id).first()
    if not setup:
        messages.error(request, f"Setup #{setup_id} not found.")
        return redirect("admin_dashboard")
    setup.is_active = not setup.is_active
    setup.save(update_fields=["is_active", "updated_at"])
    messages.success(request, f"Setup '{setup.name}' "
                              f"{'activated' if setup.is_active else 'deactivated'}.")
    return redirect("admin_dashboard")


@_admin_only
def hq_run_evolution(request):
    """Trigger immediate evolution proposer pass over decaying parameter-aware rules."""
    from signals.evolution import propose_for_decaying_rules
    try:
        result = propose_for_decaying_rules()
        messages.success(
            request,
            f"Evolution: {result['rules_with_schema']} schemas registered, "
            f"{result['rules_decaying_evolved']} decaying & evolved, "
            f"{result['total_proposals']} proposals created."
        )
    except Exception as e:
        messages.error(request, f"Evolution proposer failed: {e}")
    return redirect("admin_dashboard")


@_admin_only
def hq_apply_evolution(request):
    """Admin promotes a RuleMutation, forking the parent into a new RESEARCH-stage rule."""
    from signals.evolution import apply_evolution, EvolutionError
    try:
        mut_id = int(request.POST.get("mutation_id", "0"))
    except ValueError:
        messages.error(request, "Invalid mutation_id")
        return redirect("admin_dashboard")
    try:
        new_ctrl = apply_evolution(mut_id, request.user)
        messages.success(
            request,
            f"Forked '{new_ctrl.rule_name}' from mutation #{mut_id} (RESEARCH stage)."
        )
    except EvolutionError as e:
        messages.error(request, f"Evolution: {e}")
    return redirect("admin_dashboard")


@_admin_only
def hq_reject_evolution(request):
    from signals.evolution import reject_evolution, EvolutionError
    try:
        mut_id = int(request.POST.get("mutation_id", "0"))
    except ValueError:
        messages.error(request, "Invalid mutation_id")
        return redirect("admin_dashboard")
    try:
        mut = reject_evolution(mut_id, request.user)
        messages.success(request, f"Rejected RuleMutation #{mut.id}.")
    except EvolutionError as e:
        messages.error(request, f"Evolution: {e}")
    return redirect("admin_dashboard")


@_admin_only
def hq_run_promotions(request):
    """Trigger an immediate auto-evaluation pass over the promotion pipeline."""
    from signals.promotion_pipeline import auto_evaluate_all_rules
    try:
        result = auto_evaluate_all_rules()
        messages.success(
            request,
            f"Promotion eval: {result['n_promoted']} promoted, "
            f"{result['n_demoted']} demoted."
        )
    except Exception as e:
        messages.error(request, f"Promotion eval failed: {e}")
    return redirect("admin_dashboard")


@_admin_only
def hq_promote_rule(request):
    """Manual promote: rule_name → next stage (or specified target)."""
    from signals.promotion_pipeline import promote_rule, PipelineError
    rule_name = request.POST.get("rule_name", "").strip()
    target = request.POST.get("target_stage") or None
    if not rule_name:
        messages.error(request, "rule_name required")
        return redirect("admin_dashboard")
    try:
        ev = promote_rule(rule_name, target_stage=target, user=request.user,
                          reason="manual_promote")
        messages.success(request, f"Promoted '{rule_name}': "
                                  f"{ev.from_stage} → {ev.to_stage}")
    except PipelineError as e:
        messages.error(request, f"Promotion: {e}")
    return redirect("admin_dashboard")


@_admin_only
def hq_demote_rule(request):
    from signals.promotion_pipeline import demote_rule, PipelineError
    rule_name = request.POST.get("rule_name", "").strip()
    target = request.POST.get("target_stage") or None
    if not rule_name:
        messages.error(request, "rule_name required")
        return redirect("admin_dashboard")
    try:
        ev = demote_rule(rule_name, target_stage=target, user=request.user,
                         reason="manual_demote")
        messages.success(request, f"Demoted '{rule_name}': "
                                  f"{ev.from_stage} → {ev.to_stage}")
    except PipelineError as e:
        messages.error(request, f"Demotion: {e}")
    return redirect("admin_dashboard")


@_admin_only
def hq_propose_allocation(request):
    """Admin trigger for an immediate meta-allocator proposal."""
    from signals.meta_allocator import propose_allocation
    try:
        alloc = propose_allocation()
        messages.success(
            request,
            f"Meta-allocator: proposed allocation #{alloc.id} "
            f"(tier {alloc.sample_tier}, {alloc.rules_considered} rules).",
        )
    except Exception as e:
        messages.error(request, f"Meta-allocator proposal failed: {e}")
    return redirect("admin_dashboard")


@_admin_only
def hq_apply_allocation(request):
    """Admin promotes a shadow MetaAllocation to applied."""
    from signals.meta_allocator import apply_allocation, AllocatorError
    try:
        alloc_id = int(request.POST.get("allocation_id", "0"))
    except ValueError:
        messages.error(request, "Invalid allocation_id")
        return redirect("admin_dashboard")
    try:
        alloc = apply_allocation(alloc_id, request.user)
        messages.success(
            request,
            f"Applied MetaAllocation #{alloc.id} — "
            f"{len(alloc.previous_weights or {})} rule weight(s) updated."
        )
    except AllocatorError as e:
        messages.error(request, f"Allocator: {e}")
    return redirect("admin_dashboard")


@_admin_only
def hq_rollback_allocation(request):
    from signals.meta_allocator import rollback_allocation, AllocatorError
    try:
        alloc_id = int(request.POST.get("allocation_id", "0"))
    except ValueError:
        messages.error(request, "Invalid allocation_id")
        return redirect("admin_dashboard")
    try:
        alloc = rollback_allocation(alloc_id, request.user)
        messages.success(request, f"Rolled back MetaAllocation #{alloc.id}.")
    except AllocatorError as e:
        messages.error(request, f"Allocator: {e}")
    return redirect("admin_dashboard")


@_admin_only
def hq_reject_allocation(request):
    from signals.meta_allocator import reject_allocation, AllocatorError
    try:
        alloc_id = int(request.POST.get("allocation_id", "0"))
    except ValueError:
        messages.error(request, "Invalid allocation_id")
        return redirect("admin_dashboard")
    try:
        alloc = reject_allocation(alloc_id, request.user)
        messages.success(request, f"Rejected MetaAllocation #{alloc.id}.")
    except AllocatorError as e:
        messages.error(request, f"Allocator: {e}")
    return redirect("admin_dashboard")


@_admin_only
def hq_apply_rule_action(request):
    """Admin confirms a proposed RuleAction. Live mode required."""
    from signals.rule_actuator import apply_action, ActuatorError

    try:
        action_id = int(request.POST.get("action_id", "0"))
    except ValueError:
        messages.error(request, "Invalid action_id")
        return redirect("admin_dashboard")

    try:
        action = apply_action(action_id, request.user)
        messages.success(
            request,
            f"Applied {action.action} on rule '{action.rule_name}' (RuleAction #{action.id})."
        )
    except ActuatorError as e:
        messages.error(request, f"Actuator: {e}")
    return redirect("admin_dashboard")


@_admin_only
def hq_reject_rule_action(request):
    """Admin rejects a proposed RuleAction without applying it."""
    from signals.rule_actuator import reject_action, ActuatorError

    try:
        action_id = int(request.POST.get("action_id", "0"))
    except ValueError:
        messages.error(request, "Invalid action_id")
        return redirect("admin_dashboard")

    try:
        action = reject_action(action_id, request.user)
        messages.success(request, f"Rejected RuleAction #{action.id} for '{action.rule_name}'.")
    except ActuatorError as e:
        messages.error(request, f"Actuator: {e}")
    return redirect("admin_dashboard")


@_admin_only
def hq_rollback_rule_action(request):
    """Admin rolls back a previously-applied RuleAction; restores the snapshot."""
    from signals.rule_actuator import rollback_action, ActuatorError

    try:
        action_id = int(request.POST.get("action_id", "0"))
    except ValueError:
        messages.error(request, "Invalid action_id")
        return redirect("admin_dashboard")

    try:
        action = rollback_action(action_id, request.user)
        messages.success(
            request,
            f"Rolled back RuleAction #{action.id} for '{action.rule_name}' "
            f"to status={action.previous_status}."
        )
    except ActuatorError as e:
        messages.error(request, f"Actuator: {e}")
    return redirect("admin_dashboard")


@_admin_only
def disconnect_broker(request):
    """Clear stored credentials for a (user, broker) pair without deleting the row."""
    from django.contrib.auth.models import User
    from bot_program.models import BinanceAccount, OANDAAccount, AlpacaAccount, IBKRAccount

    target_username = request.POST.get("target_username", "").strip()
    broker = request.POST.get("broker", "").strip()
    try:
        user = User.objects.get(username=target_username)
    except User.DoesNotExist:
        messages.error(request, f"User '{target_username}' not found.")
        return redirect("admin_dashboard")

    model = {"binance": BinanceAccount, "oanda": OANDAAccount,
             "alpaca": AlpacaAccount, "ibkr": IBKRAccount}.get(broker)
    if model is None:
        messages.error(request, f"Unknown broker '{broker}'.")
        return redirect("admin_dashboard")

    acct = model.objects.filter(user=user).first()
    if acct is None:
        messages.warning(request, f"{broker}: no account for {target_username}.")
        return redirect("admin_dashboard")

    # Clear encrypted fields without deleting other settings.
    if hasattr(acct, "api_key_enc"):
        acct.api_key_enc = ""
    if hasattr(acct, "api_secret_enc"):
        acct.api_secret_enc = ""
    if hasattr(acct, "account_id_enc"):
        acct.account_id_enc = ""
    acct.connected = False
    acct.save()
    messages.success(request, f"{broker.title()} disconnected for {target_username}.")
    return redirect("admin_dashboard")
