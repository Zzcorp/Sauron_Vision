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
    """Run a run-now task: async 202 for XHR clicks (the real Celery
    task, completion announced on the operator's socket), synchronous
    with a flash for plain form POSTs. Returns a response to send, or
    None when the caller should redirect as before."""
    from dashboard.run_async import maybe_dispatch_async
    resp = maybe_dispatch_async(request, task_callable, label,
                                "/admin-dashboard/")
    if resp is not None:
        return resp
    try:
        result = task_callable()
        if isinstance(result, dict) and result.get("status") == "skipped":
            messages.warning(request, f"{label}: skipped — {result.get('reason', 'gated')}")
        else:
            messages.success(request, f"{label}: ok")
    except Exception as e:
        logger.exception("%s failed", label)
        messages.error(request, f"{label} failed: {e}")
    return None


# ── run-now endpoints ───────────────────────────────────────────────────────

@_admin_only
def run_signal_scan(request):
    from signals.tasks import run_signal_scan as task
    resp = _run_task(task, "Signal scan", request)
    if resp is not None:
        return resp
    return redirect("admin_dashboard")


@_admin_only
def run_smc_lifecycle(request):
    from signals.tasks_lifecycle import run_smc_lifecycle as task
    resp = _run_task(task, "SMC lifecycle pass", request)
    if resp is not None:
        return resp
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
    resp = _run_task(task, "Decay investigation", request)
    if resp is not None:
        return resp
    return redirect("admin_dashboard")


@_admin_only
def run_daily_snapshot(request):
    from portfolio.tasks import create_daily_snapshot as task
    resp = _run_task(task, "Daily portfolio snapshot", request)
    if resp is not None:
        return resp
    return redirect("admin_dashboard")


@_admin_only
def run_recalc_exposure(request):
    from portfolio.tasks import recalculate_exposure as task
    resp = _run_task(task, "Recalculate exposure", request)
    if resp is not None:
        return resp
    return redirect("admin_dashboard")


@_admin_only
def run_nightly_cleanup(request):
    from market_data.cleanup_tasks import nightly_cleanup_all as task
    resp = _run_task(task, "Nightly cleanup", request)
    if resp is not None:
        return resp
    return redirect("admin_dashboard")


@_admin_only
def run_full_universe_scan(request):
    from signals.tasks import run_full_universe_scan as task
    resp = _run_task(task, "Full universe signal scan", request)
    if resp is not None:
        return resp
    return redirect("admin_dashboard")


@_admin_only
def run_seed_components(request):
    """Re-seed PlatformComponents (idempotent — only adds new ones)."""
    from core.platform_control import seed_components
    n = seed_components()
    messages.success(request, f"seed_components: {n} new component(s) registered.")
    return redirect("admin_dashboard")


@_admin_only
def run_seed_strategies(request):
    """Seed the twelve shipped setups into the promotion ladder.

    The platform ships six starter and six advanced setups, and both lived
    behind management commands the deploy never ran — so an operator who
    installed everything correctly still opened the Strategies page to a
    flat zero and reasonably concluded the engine was broken.

    Safe to press twice. A re-run OVERWRITES the shipped definitions —
    description, direction, asset classes, conditions, match threshold,
    horizon, sizing, and the seed-owned keys of RuleControl.parameters — which
    is how a repaired condition reaches rows that already exist. It does NOT
    touch anything the operator or the engine decided: promotion stage and its
    timestamps, pause / reduce status, weight multiplier, allocator weight,
    notes, or whether a setup is armed. Local edits to the twelve shipped
    definitions themselves are what a re-run discards.
    """
    from io import StringIO

    from django.core.management import call_command

    out = StringIO()
    try:
        call_command("seed_strategies", stdout=out)
        call_command("seed_advanced_strategies", stdout=out)
    except Exception as exc:  # noqa: BLE001 — report, never 500 the panel
        messages.error(request, f"Seeding failed: {exc}")
        return redirect("admin_dashboard")

    from signals.models_control import RuleControl
    messages.success(
        request,
        f"Strategy definitions refreshed — {RuleControl.objects.count()} "
        f"rule(s) on the promotion ladder. New rules start in RESEARCH and "
        f"trade nothing until promoted; existing rules keep their stage, "
        f"pause/reduce state, allocator weight and armed/disarmed setting.")
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
def test_ibkr_connection(request):
    """POST {target_username} — is TWS answering, right now?

    Saving already pings, but that made verification a side effect of
    WRITING: the only way to re-check a connection was to re-submit the
    whole form, which rewrites the routing overrides from whatever the
    checkboxes happen to hold. An operator who starts TWS after saving had
    no way to confirm it worked without risking their configuration.

    This changes nothing. It builds a client from the STORED row, pings,
    records the outcome on `connected`/`last_sync`, and says what it found —
    including which account the socket points at, because "reachable" and
    "reachable, and it is the funded one" are different answers.
    """
    from django.contrib.auth.models import User
    from bot_program.models import IBKRAccount

    target_username = request.POST.get("target_username", "").strip()
    try:
        user = User.objects.get(username=target_username)
    except User.DoesNotExist:
        messages.error(request, f"IBKR: user '{target_username}' not found.")
        return redirect("admin_dashboard")

    acct = getattr(user, "ibkr_account", None)
    if acct is None:
        messages.error(request, f"IBKR: no connection saved for {target_username}.")
        return redirect("admin_dashboard")

    account_id = acct.get_account_id() or ""
    if not account_id:
        # The disconnected state. Say so rather than reporting a socket
        # result, because the router refuses to trade this row either way.
        messages.warning(
            request,
            f"IBKR: {target_username} has no account id stored — the "
            f"connection is disconnected and nothing will route to it. "
            f"Re-save the credentials to reconnect.")
        return redirect("admin_dashboard")

    from bot_program.engine.ibkr_client import IBKRTrader
    reachable = _broker_ping(
        lambda: IBKRTrader(host=acct.host, port=acct.port,
                           client_id=acct.client_id, account_id=account_id,
                           paper=acct.paper), "IBKR")

    acct.connected = reachable
    fields = ["connected"]
    if reachable:
        from django.utils import timezone
        acct.last_sync = timezone.now()
        fields.append("last_sync")
    acct.save(update_fields=fields)

    where = f"{acct.host}:{acct.port}"
    if not reachable:
        messages.error(
            request,
            f"IBKR: nothing answered at {where} for {target_username}. TWS or "
            f"IB Gateway must be running on that host with API connections "
            f"enabled, and the client id ({acct.client_id}) must not already "
            f"be in use by another session.")
    elif acct.env_is_certain:
        messages.success(
            request,
            f"IBKR: {where} answered — {acct.env_label}, account {account_id}, "
            f"client_id={acct.client_id}. "
            + ("Orders routed here would move REAL funds."
               if acct.is_live else
               "This socket is simulated; no real funds can move through it."))
    else:
        messages.warning(
            request,
            f"IBKR: {where} answered, but port {acct.port} is not one of "
            f"IBKR's four, so this platform cannot tell whether it is a paper "
            f"or a funded account. Check it in TWS before arming any bot.")
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

    # DERIVED from the port, not posted. The form has no paper checkbox —
    # the port select replaced it, because the port is what actually
    # selects the account. Reading a checkbox that is never submitted
    # stored paper=False on every save, which made the disagreement alarm
    # fire on ORDINARY paper saves and stay silent on the one case it
    # exists for. Storing the port's own answer keeps the column
    # meaningful for rows edited elsewhere (Django admin), which is now
    # the only way the two can diverge.
    paper = port in IBKRAccount.PAPER_PORTS
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

    # The PORT decides, not the checkbox. The checkbox is documented on the
    # model as informational and the socket is what actually selects the
    # account, so a message built from the checkbox could confirm "paper"
    # while pointing at a funded account. An unrecognised port is reported
    # as unknown rather than assumed safe — that is the direction of this
    # mistake that costs real money.
    env = acct.env or "UNRECOGNISED PORT"
    if not acct.env_is_certain:
        messages.warning(
            request,
            f"IBKR: port {port} is not one of IBKR's four "
            f"({', '.join(str(p) for p in sorted(IBKRAccount.PAPER_PORTS))} paper, "
            f"{', '.join(str(p) for p in sorted(IBKRAccount.LIVE_PORTS))} live), so "
            f"this platform cannot tell whether it points at a paper or a "
            f"funded account. Verify it in TWS before arming any bot.",
        )
    elif acct.paper_flag_disagrees:
        messages.warning(
            request,
            f"IBKR: the 'paper' box was {'ticked' if paper else 'unticked'} "
            f"but port {port} is the {acct.env.upper()} socket, and the port "
            f"is what selects the account. Treating this connection as "
            f"{acct.env.upper()}.",
        )
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

    # ── the time-stop ceiling ────────────────────────────────────────────
    # Three states, and all three have to be expressible or the setting is
    # not really a setting: blank = inherit the asset-class default,
    # 0 = no time stop at all, N = N hours. Blank is NOT "off" — an empty
    # box must never be the way an operator accidentally removes the only
    # exit that releases capital from a thesis that never moved.
    raw_hold = (request.POST.get("max_hold_hours", "") or "").strip()
    max_hold_hours = None
    if raw_hold:
        try:
            max_hold_hours = float(raw_hold)
        except ValueError:
            messages.error(request, f"Invalid max hold hours: {raw_hold!r}")
            return redirect("admin_dashboard")
        if max_hold_hours < 0:
            messages.error(request, "Max hold hours cannot be negative — "
                                     "use 0 to switch the time stop off.")
            return redirect("admin_dashboard")

    # The pre-field home of this setting still WINS at runtime, so leaving it
    # in the extras JSON would make the field above decorative: the operator
    # would type a ceiling, save, and the engine would keep enforcing the old
    # one. Draining it here means every save through this form leaves exactly
    # one writer, and the operator is told which value survived.
    from bot_program.asset_models import LEGACY_MAX_HOLD_EXTRAS_KEY
    if isinstance(extras, dict) and LEGACY_MAX_HOLD_EXTRAS_KEY in extras:
        legacy = extras.pop(LEGACY_MAX_HOLD_EXTRAS_KEY)
        if max_hold_hours is None:
            try:
                max_hold_hours = max(0.0, float(legacy))
            except (TypeError, ValueError):
                messages.error(
                    request,
                    f"extras['{LEGACY_MAX_HOLD_EXTRAS_KEY}']={legacy!r} is not "
                    f"a number — put the ceiling in the Max hold field.")
                return redirect("admin_dashboard")
            messages.warning(
                request,
                f"Moved extras['{LEGACY_MAX_HOLD_EXTRAS_KEY}']={legacy} into "
                f"the Max hold field — that setting has its own box now.")
        else:
            messages.warning(
                request,
                f"Both the Max hold field ({max_hold_hours}h) and "
                f"extras['{LEGACY_MAX_HOLD_EXTRAS_KEY}']={legacy} were set; "
                f"the field wins and the extras key was dropped.")

    # Setting LIVE mode requires the trading PIN — otherwise an already-enabled
    # paper config could be flipped to live (and armed) without one.
    mode = request.POST.get("mode", "paper")
    if mode == "live" and not _pin_ok(request):
        messages.error(request, "PIN required to configure a LIVE asset bot.")
        return redirect("admin_dashboard")

    # Stop-management knobs. These live in `extras` because the engine
    # reads them with `_extras_float`, but they get real inputs of their
    # own: `trail_pct` has existed since the trailing rule was written and
    # was reachable only by typing the key into the raw Extras JSON box,
    # so in practice every position ran with its entry stop until it was
    # hit. A winner giving everything back is the failure that finds.
    #
    # A blank field means "leave whatever extras already holds", and that
    # has to be true of the DICT as well as the key. This form is a
    # create-or-overwrite: it posts the whole extras blob from a box that
    # defaults to "{}", so saving it to change one number used to replace
    # every stored key with nothing - switching these rules back off on
    # the very next edit, silently, which is the failure they exist to
    # prevent. Start from what the config already holds, let the JSON box
    # overlay it, then the dedicated fields. An explicit 0 means off; the
    # JSON box remains the way to change anything without an input.
    existing = (AssetBotConfig.objects
                .filter(user=request.user, asset_class=asset_class, name=name)
                .values_list("extras", flat=True).first()) or {}
    if isinstance(existing, dict):
        merged = dict(existing)
        merged.update(extras)
        extras = merged

    for field in ("breakeven_at_r", "breakeven_buffer_r",
                  "trail_pct", "trail_start_r"):
        raw = (request.POST.get(field) or "").strip()
        if not raw:
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            messages.error(request, f"{field} must be a number (got {raw!r})")
            return redirect("admin_dashboard")
        if value < 0:
            messages.error(request, f"{field} cannot be negative")
            return redirect("admin_dashboard")
        extras[field] = value

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
            "max_hold_hours": max_hold_hours,
            "extras": extras,
        },
    )
    # Named on the way out, because the ceiling that is actually enforced can
    # come from three places and "I left it blank" should not mean "I do not
    # know what it does".
    ts = cfg.time_stop_setting()
    hold_note = (f"time stop {ts['hours']:.0f}h ({ts['source']})"
                 if ts["enabled"] else
                 f"NO time stop — positions are unbounded in time "
                 f"({ts['source']})")
    messages.success(
        request,
        f"{'Created' if created else 'Updated'} AssetBotConfig "
        f"'{cfg.name}' ({cfg.asset_class}, {cfg.mode}) · {hold_note}."
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
    from bot_program.tasks import tick_all_asset_bots as _twin
    from dashboard.run_async import maybe_dispatch_async
    resp = maybe_dispatch_async(request, _twin, "Asset bots tick",
                                "/admin-dashboard/")
    if resp is not None:
        return resp
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
    from signals.tasks import mine_patterns as _twin
    from dashboard.run_async import maybe_dispatch_async
    resp = maybe_dispatch_async(request, _twin, "Pattern mining",
                                "/admin-dashboard/")
    if resp is not None:
        return resp
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
    from signals.tasks import scan_opportunities as _twin
    from dashboard.run_async import maybe_dispatch_async
    resp = maybe_dispatch_async(request, _twin, "Opportunity scan",
                                "/admin-dashboard/")
    if resp is not None:
        return resp
    try:
        result = scan_all_setups()
        # `matches` over `scored`, not over `evaluations`. A setup carrying a
        # gate drops most of its asset classes before any evidence is read, so
        # quoting the raw pair count as the denominator made a designed universe
        # cut read as a collapse in hit rate. The skips are named so a falling
        # flag count can be attributed rather than guessed at.
        skipped = (result["asset_class_skipped"] + result["gate_skipped"])
        msg = (
            f"Opportunity scan: {result['matches']} match(es) "
            f"of {result['scored']} scored "
            f"({result['setups_scanned']} setups × "
            f"{result['instruments_scanned']} instruments = "
            f"{result['evaluations']} pairs; {skipped} outside a setup's "
            f"universe, {result['gate_skipped']} of them by gate)."
        )
        for key, phrase in (
            ("no_price_data", "{} match(es) had no price to build levels from."),
            ("evaluator_errors", "{} condition(s) raised and scored 0."),
            ("errors", "{} pair(s) failed outright."),
        ):
            if result.get(key):
                msg += " " + phrase.format(result[key])
        # A pair that raised out of scan_setup produced nothing at all, so the
        # scan is not a clean success even though it completed. Evaluator errors
        # only understate one leg's score, so they are reported in the text
        # without recolouring the whole run.
        if result["errors"]:
            messages.warning(request, msg)
        else:
            messages.success(request, msg)
    except Exception as e:
        messages.error(request, f"Scan failed: {e}")
    return redirect("admin_dashboard")


@_admin_only
def hq_resolve_opportunities(request):
    from signals.opportunity_scanner import resolve_pending_flags
    from signals.tasks import resolve_opportunity_flags as _twin
    from dashboard.run_async import maybe_dispatch_async
    resp = maybe_dispatch_async(request, _twin, "Flag resolution",
                                "/admin-dashboard/")
    if resp is not None:
        return resp
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
    """Create a new OpportunitySetup from the admin form.

    Hand-authored setups go through the SAME condition guard as the generated
    ones. They used to go through none of it: `conditions` was checked only for
    being a JSON list, `sizing` was not checked at all, and the row was written
    with `is_active=True`, so an unvalidated setup was scanning on the next pass.

    All three silent failure modes were reachable from this form. A param key
    the evaluator never reads leaves the condition running on defaults; an
    out-of-vocabulary `direction` on a two-branch evaluator does not go quiet,
    it selects the OPPOSITE branch; a sizing key outside SIZING_KEYS is
    discarded and the target falls back to 2R. None of them raise, and there is
    no model-level backstop — `OpportunitySetup` defines no `clean()` and
    `objects.create()` never calls `full_clean()`.
    """
    import json as json_mod
    from brain.strategy_generator import validate_conditions
    from signals.models import OpportunitySetup
    from signals.opportunity_scanner import SIZING_KEYS, unknown_sizing_keys

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

    ok, reason = validate_conditions(conditions)
    if not ok:
        messages.error(request, f"Conditions rejected: {reason}")
        return redirect("admin_dashboard")

    try:
        asset_classes = json_mod.loads(request.POST.get("asset_classes", "[]"))
        sizing = json_mod.loads(request.POST.get("sizing", "{}"))
    except Exception as e:
        messages.error(request, f"Invalid asset_classes/sizing JSON: {e}")
        return redirect("admin_dashboard")

    # Types, because `scan_setup` reads both with `in` and a bare string would
    # silently behave as a substring test over asset-class names.
    if not isinstance(asset_classes, list):
        messages.error(request, "asset_classes must be a JSON list (empty = all).")
        return redirect("admin_dashboard")
    if not isinstance(sizing, dict):
        messages.error(request, "sizing must be a JSON object.")
        return redirect("admin_dashboard")
    dead = unknown_sizing_keys(sizing)
    if dead:
        messages.error(
            request,
            f"Sizing keys {dead} are never read — `_suggested_levels` builds "
            f"the stop and target from {sorted(SIZING_KEYS)} and nothing else, "
            f"so those values would be silently discarded.")
        return redirect("admin_dashboard")

    direction = request.POST.get("direction", "bullish")
    description = request.POST.get("description", "")
    try:
        min_score = float(request.POST.get("min_match_score", "0.7"))
        horizon = int(request.POST.get("suggested_horizon_days", "5"))
    except ValueError:
        messages.error(request, "min_match_score / suggested_horizon_days must be numbers.")
        return redirect("admin_dashboard")

    # The form's min/max attributes are client-side only, and these are the same
    # bounds `validate_proposal` holds the generated path to.
    if not (0.0 < min_score < 1.0):
        messages.error(request, f"min_match_score {min_score} is outside (0, 1) — "
                                f"the composite it is compared against is a "
                                f"normalised 0..1 score.")
        return redirect("admin_dashboard")
    if not (1 <= horizon <= 60):
        messages.error(request, f"suggested_horizon_days {horizon} is outside [1, 60].")
        return redirect("admin_dashboard")

    # Created DISARMED, like every other authoring path on this platform: the
    # seeders land at is_active=False and so does the generator's draft. This
    # form hard-coded is_active=True, so a hand-written setup was the only kind
    # that went live without anyone confirming it a second time — and it was
    # also the only kind nothing had validated.
    setup = OpportunitySetup.objects.create(
        name=name, description=description, direction=direction,
        asset_classes=asset_classes, conditions=conditions,
        min_match_score=min_score, suggested_horizon_days=horizon,
        sizing=sizing, is_active=False, created_by=request.user,
    )
    messages.success(
        request,
        f"Created OpportunitySetup '{setup.name}' — INACTIVE. Arm it from "
        f"Intelligence → Opportunities when you want the scanner to run it.")
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
    from signals.tasks import propose_strategy_evolutions as _twin
    from dashboard.run_async import maybe_dispatch_async
    # force=True: the beat task's evidence-cadence gate must not silently
    # skip a human's explicit click.
    resp = maybe_dispatch_async(request, _twin, "Evolution proposer",
                                "/admin-dashboard/",
                                kwargs={"force": True})
    if resp is not None:
        return resp
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
    from signals.tasks import auto_evaluate_promotions as _twin
    from dashboard.run_async import maybe_dispatch_async
    resp = maybe_dispatch_async(request, _twin, "Promotion evaluation",
                                "/admin-dashboard/")
    if resp is not None:
        return resp
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
    from signals.tasks import propose_meta_allocation as _twin
    from dashboard.run_async import maybe_dispatch_async
    resp = maybe_dispatch_async(request, _twin, "Meta-allocation proposal",
                                "/admin-dashboard/")
    if resp is not None:
        return resp
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


# ── The Eye — who is on the platform, from where, holding what ──────────────

# Resolve locations for at most this many users per page view: each cold
# lookup is a real network call with a 4s ceiling, and an admin page must
# stay an admin page even when the geo service is down.
EYE_GEO_BUDGET = 25


@login_required
def admin_eye(request):
    """Live operator view of the user base: connected-now, last address
    and location, device, last page touched, and what each account holds
    (allocated capital, bots, open positions, manual takes). GET-only,
    superuser-only — this page shows addresses."""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Superuser access required.")

    from datetime import timedelta

    from django.contrib.auth.models import User
    from django.contrib.sessions.models import Session
    from django.db.models import Count, Q, Sum
    from django.shortcuts import render
    from django.utils import timezone

    from bot_program.manual_trade import MANUAL_RULE
    from bot_program.models import AssetBotConfig, AssetBotTrade
    from core.presence import (ONLINE_WINDOW_SECONDS, UserPresence,
                               device_label, geo_for_ip)

    now = timezone.now()
    online_cutoff = now - timedelta(seconds=ONLINE_WINDOW_SECONDS)
    day_ago = now - timedelta(hours=24)
    week_ago = now - timedelta(days=7)

    presences = {p.user_id: p for p in UserPresence.objects.all()}

    # CLOSE_PENDING is still live exposure — the broker holds the position
    # until the close retry lands, and every other exposure count on the
    # platform includes it.
    live_statuses = ("OPEN", "CLOSE_PENDING")
    open_by_user = {r["config__user"]: r["n"] for r in
                    AssetBotTrade.objects.filter(status__in=live_statuses)
                    .values("config__user").annotate(n=Count("id"))}
    manual_by_user = {r["config__user"]: r["n"] for r in
                      AssetBotTrade.objects.filter(rule_name=MANUAL_RULE)
                      .values("config__user").annotate(n=Count("id"))}
    cap_by_user = {r["user"]: r for r in
                   AssetBotConfig.objects.values("user").annotate(
                       total=Sum("capital"), bots=Count("id"),
                       bots_on=Count("id", filter=Q(enabled=True)))}

    rows = []
    for u in User.objects.order_by("-date_joined"):
        p = presences.get(u.id)
        cap = cap_by_user.get(u.id) or {}
        rows.append({
            "user": u,
            "presence": p,
            "online": bool(p and p.last_seen >= online_cutoff),
            # cached_only: the render path NEVER does a network lookup —
            # a page of N users during a geo outage must not serially
            # block the shared sync thread. The page warms cold entries
            # through the /eye/geo/ endpoint after it has rendered.
            "geo": geo_for_ip(p.last_ip, cached_only=True) if p else "",
            "device": device_label(p.user_agent) if p else "—",
            "capital": cap.get("total") or 0,
            "bots": cap.get("bots") or 0,
            "bots_on": cap.get("bots_on") or 0,
            "open_trades": open_by_user.get(u.id, 0),
            "manual_taken": manual_by_user.get(u.id, 0),
        })
    # Online first, then most recently seen, then newest account.
    rows.sort(key=lambda r: (
        not r["online"],
        -(r["presence"].last_seen.timestamp() if r["presence"] else 0),
    ))

    online_now = sum(1 for r in rows if r["online"])
    seen_24h = sum(1 for p in presences.values() if p.last_seen >= day_ago)

    metrics = {
        "users_total": len(rows),
        "online_now": online_now,
        "seen_24h": seen_24h,
        "new_7d": User.objects.filter(date_joined__gte=week_ago).count(),
        "sessions_active": Session.objects.filter(
            expire_date__gte=now).count(),
        "open_trades": AssetBotTrade.objects.filter(
            status__in=live_statuses).count(),
        "capital_total": AssetBotConfig.objects.aggregate(
            t=Sum("capital"))["t"] or 0,
    }
    try:
        from signals.models import Signal
        metrics["signals_active"] = Signal.objects.filter(
            is_active=True).count()
    except Exception:  # noqa: BLE001
        metrics["signals_active"] = 0
    try:
        from scraping.models import NewsArticle
        metrics["news_24h"] = NewsArticle.objects.filter(
            scraped_at__gte=day_ago).count()
    except Exception:  # noqa: BLE001
        metrics["news_24h"] = 0
    try:
        from market_data.models import LiveQuote
        metrics["quotes_fresh"] = LiveQuote.objects.filter(
            updated_at__gte=now - timedelta(minutes=15)).count()
    except Exception:  # noqa: BLE001
        metrics["quotes_fresh"] = 0
    try:
        from ai_agents.models import AgentTask
        ai = AgentTask.objects.filter(created_at__gte=day_ago)
        metrics["ai_24h"] = ai.count()
        metrics["ai_cost_24h"] = float(sum(
            float(t.cost_usd or 0) for t in ai))
    except Exception:  # noqa: BLE001
        metrics["ai_24h"], metrics["ai_cost_24h"] = 0, 0.0

    return render(request, "dashboard/admin_eye.html", {
        "page_id": "admin_eye",
        "rows": rows,
        "metrics": metrics,
    })


# Wall-clock ceiling for one geo-warm pass. Individual lookups are
# time-limited too, but DNS resolution is not — the monotonic check
# between lookups is what bounds the whole request.
EYE_GEO_TIME_BUDGET_SECONDS = 8.0


@login_required
def admin_eye_geo(request):
    """GET — resolve locations for the most recent presences, cached a
    day. Called by the Eye page AFTER it renders, so the slow part (up to
    EYE_GEO_BUDGET keyless lookups) never blocks the page — or, via the
    shared sync-view executor, anyone else's page."""
    if not request.user.is_superuser:
        return HttpResponseForbidden("Superuser access required.")
    import time

    from django.http import JsonResponse

    from core.presence import UserPresence, geo_for_ip

    out = {}
    started = time.monotonic()
    newest = (UserPresence.objects.exclude(last_ip="")
              .order_by("-last_seen")[:EYE_GEO_BUDGET])
    for p in newest:
        if time.monotonic() - started > EYE_GEO_TIME_BUDGET_SECONDS:
            break
        label = geo_for_ip(p.last_ip)
        if label:
            out[p.last_ip] = label
    return JsonResponse({"geo": out})


@login_required
def hq_books(request):
    """The whole house at one glance — every book, and what is held where.

    The capital_summary discipline holds ALL the way down here: the two
    economies are separate tables, paper and live pools are separate
    rows (simulated money is not deployable money), currencies are never
    summed into one figure (a EUR book plus a USD bot is two numbers,
    not a number in no currency that exists), and an unpriced leg is
    counted, never booked at zero or a stale entry. Underneath, the
    cross-book concentration table: one symbol held in several
    REAL-money books is one bet wearing several accounts — paper
    holders are listed and marked, but only real money trips the flag.
    """
    if not request.user.is_superuser:
        return HttpResponseForbidden("Superuser access required.")

    from collections import defaultdict
    from decimal import Decimal

    from django.shortcuts import render

    from bot_program.models import AssetBotConfig, AssetBotTrade
    from portfolio.models import Portfolio, Position
    from portfolio.services import is_option_row, value_per_unit

    # One fetch of every open legacy position, shared by both passes.
    all_open = list(Position.objects.filter(closed_at__isnull=True)
                    .select_related("instrument", "portfolio"))
    by_book = defaultdict(list)
    for pos in all_open:
        by_book[pos.portfolio_id].append(pos)

    books = []
    for pf in Portfolio.objects.order_by("name"):
        marked = Decimal("0")
        unpriced = 0
        legs = by_book.get(pf.pk, [])
        for pos in legs:
            if pos.current_price:
                marked += abs(pos.quantity * pos.current_price)
            else:
                unpriced += 1
        books.append({
            "name": pf.name,
            "currency": pf.currency,
            "cash": pf.cash_available,
            "initial": pf.initial_capital,
            "n_open": len(legs),
            "n_priced": len(legs) - unpriced,
            "marked": marked,
            "unpriced": unpriced,
        })

    # Bot books: one row per (trader, mode, currency) — the three axes
    # along which the figures must never be added together.
    pools = defaultdict(float)
    for cfg in (AssetBotConfig.objects.filter(enabled=True)
                .select_related("user")):
        pools[(cfg.user.username, cfg.mode,
               cfg.base_currency or "USD")] += float(cfg.capital or 0)
    open_trades = list(AssetBotTrade.objects.filter(
        status__in=("OPEN", "CLOSE_PENDING")).select_related("config__user"))
    by_lane = {}
    for tr in open_trades:
        key = (tr.config.user.username, tr.config.mode,
               tr.config.base_currency or "USD")
        row = by_lane.setdefault(key, {"n": 0, "notional": 0.0})
        row["n"] += 1
        row["notional"] += abs(float(tr.qty or 0)
                               * float(tr.entry_price or 0)
                               * value_per_unit(tr))
    bot_books = []
    for key in sorted(set(pools) | set(by_lane)):
        username, mode, currency = key
        row = by_lane.get(key, {"n": 0, "notional": 0.0})
        bot_books.append({
            "user": username,
            "mode": mode,
            "currency": currency,
            "pool": round(pools.get(key, 0.0), 2),
            "n_open": row["n"],
            "notional": round(row["notional"], 2),
        })

    # Cross-book concentration. Per-currency buckets — never one sum.
    held = {}

    def _row(sym):
        return held.setdefault(sym, {
            "symbol": sym, "holders": set(), "real_holders": set(),
            "long": defaultdict(float), "short": defaultdict(float),
            "premium": defaultdict(float), "unpriced": 0,
        })

    for pos in all_open:
        h = _row(pos.instrument.symbol)
        holder = f"book · {pos.portfolio.name}"
        h["holders"].add(holder)
        h["real_holders"].add(holder)
        if not pos.current_price:
            # Same discipline as the books table: counted, never valued
            # at a stale entry or a confident zero.
            h["unpriced"] += 1
            continue
        side = "long" if pos.direction == "long" else "short"
        h[side][pos.portfolio.currency] += abs(
            float(pos.quantity or 0) * float(pos.current_price))
    for tr in open_trades:
        h = _row(tr.symbol)
        mode = tr.config.mode
        holder = f"bot · {tr.config.user.username} [{mode}]"
        h["holders"].add(holder)
        if mode != "paper":
            h["real_holders"].add(holder)
        currency = tr.config.base_currency or "USD"
        notional = abs(float(tr.qty or 0) * float(tr.entry_price or 0)
                       * value_per_unit(tr))
        if is_option_row(tr):
            # Premium dollars are not share exposure — folding them into
            # the long/short columns would understate the bet by orders
            # of magnitude. Own bucket, rendered as its own fact.
            h["premium"][currency] += notional
        else:
            side = ("long" if (tr.side or "").upper() in ("BUY", "LONG")
                    else "short")
            h[side][currency] += notional

    def _parts(bucket):
        return " + ".join(f"{cur} {amt:,.2f}"
                          for cur, amt in sorted(bucket.items())) or ""

    concentration = []
    for h in held.values():
        per_ccy = [h["long"][c] + h["short"][c]
                   for c in set(h["long"]) | set(h["short"])]
        concentration.append({
            "symbol": h["symbol"],
            "holders": sorted(h["holders"]),
            "n_holders": len(h["holders"]),
            "crowded": len(h["real_holders"]) >= 2,
            "long_display": _parts(h["long"]),
            "short_display": _parts(h["short"]),
            "premium_display": _parts(h["premium"]),
            "unpriced": h["unpriced"],
            # Sort tiebreak: the largest SINGLE-CURRENCY share notional.
            # Mixing currencies into one sortable sum would rank a JPY
            # book ~150x overstated; premium stays out by design.
            "_rank": max(per_ccy) if per_ccy else 0.0,
        })
    concentration.sort(key=lambda r: (-r["n_holders"], -r["_rank"]))

    return render(request, "dashboard/hq_books.html", {
        "page_id": "admin",
        "books": books,
        "bot_books": bot_books,
        "concentration": concentration,
        "n_crowded": sum(1 for r in concentration if r["crowded"]),
    })
