from celery import shared_task
from core.task_gate import guarded_task
from .engine.runner import run_bot_tick
from .engine.backtest import run_scenario
from .models import BotConfig, BotScenario

@shared_task
def tick_all_bots():
    for cfg in BotConfig.objects.filter(enabled=True):
        try:
            run_bot_tick(cfg.user_id)
        except Exception as e:
            print(f"tick failed for user={cfg.user_id}: {e}")

@shared_task
def run_scenario_task(scenario_id: int):
    try:
        run_scenario(BotScenario.objects.get(id=scenario_id))
    except Exception as e:
        print(f"scenario failed {scenario_id}: {e}")


# ─── Phase 13: multi-asset bot framework ─────────────────────────────────

@shared_task
@guarded_task("pipeline_asset_bots")
def tick_all_asset_bots():
    """Phase-13: walk every enabled AssetBotConfig and run one tick.

    Per-bot exceptions are swallowed (already done inside run_asset_bot_tick).
    """
    from .asset_engine.runner import run_all_asset_bots
    return run_all_asset_bots()


@shared_task
def run_asset_bot_tick_task(config_id: int):
    """One config's tick — fire-and-forget callable from admin / scheduler."""
    from .asset_engine.runner import run_asset_bot_tick
    return run_asset_bot_tick(config_id)


# ─── Phase 14.1: live OptionContract chain refresh ───────────────────────────

def refresh_option_chains_for_user(user_id: int) -> dict:
    """Refresh OptionContract rows for all underlying symbols an OptionsBot
    config is configured to trade for `user_id`.

    For each symbol:
      1. Look up the IBKR client via broker_router.
      2. Pull the option chain via `client.option_chain(symbol)`.
      3. Filter to expiries within the union of all this user's options
         configs' [min_dte, max_dte] windows (defaults 14..60).
      4. Filter to strikes within ±20% of underlying's last price (best effort).
      5. Upsert OptionContract rows with the latest bid/ask/Greeks.

    Returns a summary dict {symbols: int, contracts_upserted: int, errors: int}.

    NB: not Celery-decorated — call from `refresh_all_option_chains` (gated)
    or from admin "run now" buttons. Tests call this directly.
    """
    from datetime import date, timedelta
    from decimal import Decimal
    from django.contrib.auth.models import User
    from instruments.models import Instrument
    from .models import AssetBotConfig
    from .options_models import OptionContract
    from .engine.broker_router import client_for_symbol
    from market_data.models import LiveQuote

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return {"error": f"user {user_id} not found"}

    configs = list(AssetBotConfig.objects.filter(
        user=user, asset_class="options", enabled=True))
    if not configs:
        return {"symbols": 0, "contracts_upserted": 0, "errors": 0,
                "skipped": "no enabled options configs"}

    # Union of DTE windows across this user's options configs.
    min_dte = min(int((c.extras or {}).get("min_dte", 14)) for c in configs)
    max_dte = max(int((c.extras or {}).get("max_dte", 60)) for c in configs)
    today = date.today()
    min_exp = today + timedelta(days=min_dte)
    max_exp = today + timedelta(days=max_dte)

    # Symbol set across all configs.
    symbols = sorted({s for c in configs for s in (c.symbols or [])})

    upserted = 0
    errors = 0
    for symbol in symbols:
        try:
            inst = Instrument.objects.filter(symbol=symbol).first()
            if inst is None:
                continue
            client = client_for_symbol(user, symbol, configs[0])
            if not hasattr(client, "option_chain"):
                continue  # paper / non-IBKR — chain refresh isn't supported

            # Best-effort underlying price for strike-band filtering.
            underlying_px = None
            lq = LiveQuote.objects.filter(instrument=inst).first()
            if lq and lq.last:
                underlying_px = float(lq.last)

            chain = client.option_chain(symbol) or []
            for entry in chain:
                try:
                    expiry_str = entry.get("expiry") or ""
                    if not expiry_str or len(expiry_str) < 10:
                        continue
                    exp = date.fromisoformat(expiry_str[:10])
                    if not (min_exp <= exp <= max_exp):
                        continue

                    strike = float(entry.get("strike") or 0)
                    if strike <= 0:
                        continue
                    if underlying_px:
                        # Keep ±20% band around spot.
                        if abs(strike - underlying_px) / underlying_px > 0.20:
                            continue

                    right = entry.get("right") or ""
                    if right not in ("C", "P"):
                        continue

                    contract, _ = OptionContract.objects.update_or_create(
                        underlying=inst,
                        strike=Decimal(str(strike)),
                        expiry=exp, right=right,
                        defaults={
                            "symbol": entry.get("symbol") or "",
                            "bid": _safe_dec(entry.get("bid")),
                            "ask": _safe_dec(entry.get("ask")),
                            "last_price": _safe_dec(entry.get("last")),
                            "iv": _safe_float(entry.get("iv")),
                            "delta": _safe_float(entry.get("delta")),
                            "gamma": _safe_float(entry.get("gamma")),
                            "theta": _safe_float(entry.get("theta")),
                            "vega": _safe_float(entry.get("vega")),
                            "open_interest": int(entry.get("open_interest") or 0),
                            "volume": int(entry.get("volume") or 0),
                        },
                    )
                    upserted += 1
                except Exception:
                    errors += 1
        except Exception as e:
            errors += 1
            print(f"option chain refresh failed for {symbol}: {e}")

    return {"symbols": len(symbols), "contracts_upserted": upserted,
            "errors": errors, "min_dte": min_dte, "max_dte": max_dte}


@shared_task
@guarded_task("pipeline_asset_bots")
def refresh_all_option_chains() -> dict:
    """Walk every user with an enabled options AssetBotConfig and refresh.

    Beat-scheduled hourly during NYSE hours (Phase 14.1). Gated by the
    `pipeline_asset_bots` PlatformComponent — admin can disable from HQ.
    """
    return _refresh_all_option_chains_impl()


def _refresh_all_option_chains_impl() -> dict:
    """Pure implementation, callable by tests or run-now buttons."""
    from .models import AssetBotConfig

    user_ids = list(AssetBotConfig.objects.filter(
        asset_class="options", enabled=True
    ).values_list("user_id", flat=True).distinct())

    results = {}
    total_upserted = 0
    for uid in user_ids:
        try:
            r = refresh_option_chains_for_user(uid)
            results[uid] = r
            total_upserted += int(r.get("contracts_upserted", 0))
        except Exception as e:
            results[uid] = {"error": str(e)}
    return {"users": len(user_ids), "total_upserted": total_upserted,
            "details": results}


def _safe_dec(v):
    from decimal import Decimal, InvalidOperation
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None


def _safe_float(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ─── Phase 26: track-record decay detection ──────────────────────────────────

@shared_task
@guarded_task("pipeline_asset_bots")
def check_all_track_record_decay():
    """Walk every user with recent bot trades, detect rules whose recent
    performance has decayed vs baseline, fire notifications.

    Beat-scheduled daily. Gated by `pipeline_asset_bots` PlatformComponent.
    Tests should call `check_all_users_decay()` directly to bypass the gate.
    """
    from .track_record_decay import check_all_users_decay
    return check_all_users_decay()


# ─── Phase 19: live IBKR market-data feed ───────────────────────────────────

@shared_task
@guarded_task("pipeline_asset_bots")
def refresh_all_ibkr_market_data():
    """Walk every connected IBKRAccount, pull historical klines + ticker for
    symbols on enabled AssetBotConfigs, upsert into PriceData / LiveQuote
    with source='ibkr'. Lets users drop external data vendors for asset
    classes routed through IBKR.

    Beat-scheduled hourly during NYSE hours. Gated by `pipeline_asset_bots`.
    Tests should call `refresh_ibkr_data_all_users()` directly to bypass.
    """
    from .ibkr_data_feed import refresh_ibkr_data_all_users
    return refresh_ibkr_data_all_users()


# ─── Phase 33.4: AssetBotTrade reconciliation ───────────────────────────────

@shared_task
@guarded_task("pipeline_asset_bots")
def reconcile_all_asset_bot_trades():
    """Walk every user with an open live AssetBotTrade and verify the broker
    still agrees the position is open. Closes orphans + grades them.

    Beat-scheduled every 15 min during market hours. Tests should call
    `reconcile_all_users()` directly to bypass the guard.
    """
    from .reconcile_asset import reconcile_all_users
    return reconcile_all_users()


# ─── Phase 33.5: daily PostgreSQL backup ────────────────────────────────────

@shared_task
def run_daily_postgres_backup():
    """Take a `pg_dump -Fc` dump + prune older than BACKUP_KEEP_DAYS (30).

    NOT gated by `pipeline_asset_bots` — backups should run regardless of
    bot framework state. Skipped silently on sqlite dev box.
    """
    from core.backups import run_postgres_backup
    return run_postgres_backup()


# ─── Retry pending closes ───────────────────────────────────────────────────

@shared_task
def retry_pending_closes():
    """Drain AssetBotTrade rows stuck in CLOSE_PENDING.

    A CLOSE_PENDING row means the bot decided to flatten but the broker order
    failed — the position is STILL OPEN at the broker. Every 5 minutes we
    resubmit the close; only a broker success finalises the row as CLOSED.

    Deliberately NOT gated by the pipeline_asset_bots component: switching
    the bots off is the operator's natural reaction to a failed close (and
    is exactly what the kill switch does), and that must not disable the
    only drain for stranded live positions.
    """
    from .pending_closes import retry_all_pending_closes
    return retry_all_pending_closes()
