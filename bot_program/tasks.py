import logging
from datetime import date, timedelta

from celery import shared_task
from core.dead_man_switch import heartbeat
from core.task_gate import guarded_task

from .alarm import alarm_task

logger = logging.getLogger(__name__)
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
@heartbeat
@guarded_task("pipeline_asset_bots")
def tick_all_asset_bots():
    """Phase-13: walk every enabled AssetBotConfig and run one tick.

    Per-bot exceptions are swallowed (already done inside run_asset_bot_tick).

    The dead man's switch (2026-09-30, core/dead_man_switch.py) pings an
    outside watcher after every pass, OUTSIDE the gate: a paused platform
    still pings, a dead box does not, and the watcher raises the alarm.

    ONE PASS AT A TIME (2026-10-02): a pass that outlives the 5-minute beat
    (a slow venue, the trade debate's minute) must not meet a second pass
    judging the same book — two passes could each pass the duplicate and
    open-risk gates and send the same order twice. A pass that finds the
    lock held skips, said; the lock expires on its own after TICK_LOCK_S.
    """
    from django.core.cache import cache

    from .asset_engine.runner import run_all_asset_bots
    if not cache.add(TICK_LOCK_KEY, timezone_now_iso(), TICK_LOCK_S):
        logger.warning("[asset bots] a pass is still running — this beat "
                       "skips (no second pass on the same book)")
        return {"status": "skipped", "reason": "a pass is still running"}
    try:
        return run_all_asset_bots()
    finally:
        cache.delete(TICK_LOCK_KEY)


TICK_LOCK_KEY = "asset_bots:tick_lock"
TICK_LOCK_S = 900


def timezone_now_iso() -> str:
    from django.utils import timezone
    return timezone.now().isoformat()


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
            # A chain refresh is a pure market-data read: it must not
            # hold the exclusive trading session (see ibkr_sessions).
            client = client_for_symbol(user, symbol, configs[0],
                                       purpose="data")
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

    Beat-scheduled around the clock (since 2026-10-06: eToro's forex,
    commodity and crypto stops fire at night), every 5 min since
    2026-10-31 (every 15 before). Tests should call
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


# ─── The broker's own reading ────────────────────────────────────────────

@shared_task
@guarded_task("broker_account_sync")
def sync_broker_account() -> dict:
    """Read each interfaced IBKR account's equity and holdings, cache them
    on the IBKRAccount row. The ONLY writer of those columns.

    Broker I/O lives here and nowhere else: never on a render path (a
    page load must not race an operator or hold a worker on a socket) and
    never on an entry path (capital_truth's docstring owns that refusal).
    Pages read the cached columns plus their AGE — a stale reading with an
    honest timestamp beats a fresh one fetched from inside a view.

    Deliberately NOT gated behind pipeline_asset_bots and not hour-gated:
    knowing what the account holds is not a bot function, and an ISA does
    not stop existing when the bots are off or the market is closed.

    Unreadable is UNMEASURED, not zero: on any failure the previous
    reading is left standing with its age visible, and nothing is written.
    The task then reports work-without-store, which task_gate grades as a
    warning — a gateway that has been down all day should look yellow, not
    green.
    """
    import asyncio

    from django.utils import timezone

    from .capital_truth import broker_backed, ibkr_in_use
    from .engine.ibkr_client import is_ibkr_available
    from .engine.ibkr_sessions import acquire_trader
    from .models import IBKRAccount

    out = {"attempted": 0, "stored": 0, "unreachable": 0}
    if not is_ibkr_available():
        # No keyed account, nothing to read: the missing library costs
        # nothing, so the pass is idle, not "not configured" (2026-09-26).
        # A keyed account without the library is still the warning.
        # A keyed row the operator has retired (capital_truth.ibkr_in_use:
        # not the book, no class, no live position) is not an account to
        # read either (2026-09-30).
        if not any(ibkr_in_use(a) for a in
                   IBKRAccount.objects.exclude(account_id_enc="")):
            return {**out, "idle": "no keyed IBKR account"}
        return {**out, "skipped": "ib_insync not installed"}

    # ib_insync needs an event loop; celery prefork workers, like web
    # worker threads, may not have one. Same guard _broker_ping uses.
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    accounts = IBKRAccount.objects.exclude(account_id_enc="")
    for acct in accounts:
        user = acct.user
        if broker_backed(user) is None:
            continue
        # RETIRED, NOT UNREACHABLE (2026-09-30). The operator left IBKR:
        # the book is eToro and nothing routes here, yet this row was
        # attempted every 15 minutes, missed (the Gateway is down), graded
        # the shared sync row a warning and, from the third miss, told the
        # Eye and the alarm chat "broker unreachable" for ever. A row that
        # is not in use is not read, and its miss count is cleared so a
        # standing alert ends with it. Ticking a flag brings it back.
        if not ibkr_in_use(acct):
            _clear_broker_miss(acct)
            continue
        out["attempted"] += 1
        client = None
        try:
            # The probe id, not the trade id: IBKR keeps one session per
            # clientId and REFUSES a second connection on it (error 326),
            # so a sync on the trading id would fail whenever the trader
            # held the socket — or hold it against the trader. The session
            # comes from ibkr_sessions, which leases this process its own
            # slot; disconnecting below closes the socket and leaves the
            # slot to this process for the next pass.
            client = acquire_trader(
                acct.host, acct.port, acct.client_id, "probe",
                account_id=acct.get_account_id() or "",
                paper=bool(acct.paper))
            if client is None:
                raise RuntimeError("no free IBKR clientId slot")
            reading = client.net_liquidation()
            rows = client.broker_portfolio()
        except Exception as e:  # noqa: BLE001 — one account must not stop the rest
            logger.warning("broker sync: %s unreadable: %s", acct.label, e)
            reading, rows = None, None
        finally:
            disconnect = getattr(client, "disconnect", None)
            if callable(disconnect):
                try:
                    disconnect()
                except Exception:  # noqa: BLE001
                    pass

        if reading is None and rows is None:
            out["unreachable"] += 1
            # NONE IS THE CONTRACT HERE, NOT AN EXCEPTION (2026-09-15).
            # `account_values()` and `broker_portfolio()` both document "or
            # None when unreadable" and both return None from
            # `if not self._connect()` without logging. So the `except`
            # above never fires for the case that matters most — a Gateway
            # that is up and not logged in — and this miss used to be
            # counted in total silence: the live box showed misses = 8
            # against zero "unreadable" lines in six hours of worker logs,
            # while every equity figure on every page went stale.
            #
            # The line itself lives in `_note_broker_miss`, which is the
            # only place the CONSECUTIVE count exists. `out["unreachable"]`
            # counts accounts within THIS pass and resets every invocation,
            # so logging it here printed "miss 1" forever on a one-account
            # box — a number shaped like the one an operator needs and not
            # it.
            _note_broker_miss(acct, user)
            continue
        _clear_broker_miss(acct)

        now = timezone.now()
        fields = []
        if reading is not None:
            value, currency = reading
            acct.last_equity = value
            acct.last_equity_currency = currency
            acct.last_equity_at = now
            fields += ["last_equity", "last_equity_currency",
                       "last_equity_at"]
        if rows is not None:
            acct.broker_positions = rows
            acct.broker_positions_at = now
            fields += ["broker_positions", "broker_positions_at"]
        acct.save(update_fields=fields)
        if reading is not None:
            # The history row — the drawdown governor's memory. Written
            # here and nowhere else, from the SAME reading the cell just
            # stored, so the road and the current position can never
            # quote two different syncs. A failed insert must not fail
            # the sync (the cell is already written and the pools still
            # need re-sizing), and a missed sync writes NOTHING: a zero
            # placeholder would read as a total drawdown and pin the
            # governor to its floor for 90 days (2026-09-12).
            try:
                from decimal import Decimal

                from .equity_models import BrokerEquityReading
                BrokerEquityReading.objects.create(
                    broker="ibkr", account_pk=acct.pk,
                    account=acct, value=Decimal(str(round(float(value), 2))),
                    currency=currency or "", env=acct.env or "", at=now)
                _prune_equity_history("ibkr", acct.pk, now)
            except Exception as e:  # noqa: BLE001 — history is beside the sync, not in it
                logger.warning("broker sync: history row failed: %s", e)
            # ONLY WHEN THIS ROW IS THE BOOK. Both newer walks carry this
            # guard — "two brokers retuning the same pools would fight" — and
            # this one did not: from the moment a Saxo or eToro box was
            # ticked, every follower pool was still being resized from IBKR's
            # NetLiquidation while capital_truth gated the entries on the
            # other broker's reading. Pools sized from one account, entries
            # refused on another, and once both readings land the pools take
            # whichever walk finished last.
            book = broker_backed(user)
            if book is not None and type(book) is type(acct) \
                    and book.pk == acct.pk:
                _follow_the_account(user, value, currency)
                _shock_trigger(user, now)
        out["stored"] += 1
    if not out["attempted"]:
        # IDLE, NOT "RAN AND PRODUCED NOTHING" (2026-09-26). No keyed IBKR
        # account belongs to a user with a book, so this pass read nothing — IBKR is
        # being retired, and on the live box that is every pass. The gate
        # writes nothing for an idle result: broker_account_sync is the row
        # of all three walks, and this verdict used to land on it minutes
        # after eToro's, turning a healthy sync into a warning in the daily
        # digest and an eToro error into a quiet "ran and produced
        # nothing". A keyed account
        # that answered nothing was attempted, and is still a warning.
        out["idle"] = "no IBKR account to read"
    return out


def _warm_etoro_names(client, user, demo: bool) -> None:
    """Name what the book holds before the sync reads it (2026-10-01).

    eToro answers /portfolio with instrumentIds, and this fresh client can
    name only what it resolved itself — so the stored snapshot read
    "ETORO:<id>" for the operator's forex position and a bare id beside it, on
    /treasury/, in the operator's own diagnostics and in Morgul's drift
    guard, which then compares by count instead of by symbol. Every symbol
    the platform holds OPEN at this account's world is resolved first,
    through the adapter's own instrument_id (the pinned ids answer without
    /search). A name that cannot be resolved stays "ETORO:<id>", as before:
    unnamed is said, never guessed. Wrapped whole: naming is beside the
    sync, never in it."""
    try:
        from .models import AssetBotTrade
        name_it = getattr(client, "instrument_id", None)
        if not callable(name_it):
            return
        rows = AssetBotTrade.objects.filter(
            config__user=user, paper=False,
            status__in=("OPEN", "CLOSE_PENDING"))
        # the rows' own world word (AssetBot.VENUE_WORLDS: a demo fill is
        # stamped "paper"), and only rows eToro carried (or unstamped
        # legacy ones): no /search for another broker's symbol
        world = "paper" if demo else "live"
        syms = sorted({t.symbol for t in rows
                       if str((t.metadata or {}).get("broker_env")
                              or world) == world
                       and str((t.metadata or {}).get("broker")
                               or "etoro") == "etoro"})
        for sym in syms:
            try:
                name_it(sym)
            except Exception as e:  # noqa: BLE001 — one name, not the sync
                logger.debug("broker sync: cannot name %s (%s)", sym, e)
    except Exception as e:  # noqa: BLE001 — naming is beside the sync
        logger.debug("broker sync: naming skipped: %s", e)


def _shock_trigger(user, now) -> None:
    """The fast path of the share allocator: a shock plan the moment the
    sync that saw the shock has stored its reading, not up to four hours
    later at the next :05 beat (2026-09-12). Cheap on purpose — the 24 h
    drop and the drawdown off the rows just written, no brain context —
    and once per SHOCK_TRIGGER_COOLDOWN_S per user through cache.add, so
    a 15-minute beat on a bad day does not write a plan per beat. Gated
    on the allocator's own component: when the proposer is off, nothing
    proposes. Wrapped whole: a failed proposal must never fail the sync
    whose reading the pools are being re-sized from.
    """
    try:
        from django.core.cache import cache

        from core.platform_control import is_component_enabled

        from . import share_allocator
        if not is_component_enabled("pipeline_share_allocator"):
            return
        if not share_allocator.shock_detected(user, now=now):
            return
        # ONE PLAN PER SHOCK (2026-10-03). The shock reads true for the
        # whole 24 h the drop stays in the window, and the hourly cooldown
        # above let this path propose a NEW plan — and say "Shock plan
        # proposed" again — every hour while the first one sat unanswered
        # on /shares/ (the operator: "this message keeps popping up"). A
        # shock plan still PROPOSED inside the hold is the answer already
        # given: nothing new is proposed, nothing is said again. A plan the
        # admin applied, rejected or that expired no longer holds the door.
        from datetime import timedelta as _td

        from .share_models import SharePlan
        pending = (SharePlan.objects
                   .filter(user=user, mode=SharePlan.MODE_SHOCK,
                           state=SharePlan.STATE_PROPOSED,
                           proposed_at__gte=now - _td(
                               hours=share_allocator.SHOCK_HOLD_HOURS))
                   .order_by("-proposed_at").first())
        if pending is not None:
            logger.info("[shares] shock still on for %s; plan #%s is "
                        "proposed and unanswered — nothing new proposed",
                        user.username, pending.pk)
            return
        if not cache.add(f"shares:shock:{user.pk}", "1",
                         timeout=share_allocator.SHOCK_TRIGGER_COOLDOWN_S):
            return
        plan, reason = share_allocator.propose_share_plan_with_reason(
            user, now=now)
        if plan is None:
            logger.info("[shares] shock detected for %s but nothing "
                        "proposed: %s", user.username, reason)
            return
        current = plan.current_shares or {}
        n = 0
        for k, target in (plan.targets or {}).items():
            try:
                if current.get(k) is not None \
                        and float(target) < float(current[k]) - 1e-9:
                    n += 1
            except (TypeError, ValueError):
                continue
        from .notifications import notify_staff
        notify_staff(
            title="⚠ Shock plan proposed",
            body=(f"{user.username}: {'; '.join(plan.mode_reasons or [])}; "
                  f"{n} pool(s) to de-risk — open /shares/"),
            url="/shares/", cooldown_hours=1)
    except Exception as e:  # noqa: BLE001 — the sync's reading stands
        logger.warning("[shares] shock proposal failed: %s", e)


# The drawdown governor looks back 90 days; 400 keeps a year of context
# for the operator's eye and bounds the table at ~1 row per sync.
EQUITY_HISTORY_DAYS = 400


def _prune_equity_history(broker: str, account_pk: int, now) -> None:
    """Drop this account's history rows older than EQUITY_HISTORY_DAYS.

    ONE helper for the three walks (2026-09-28): the IBKR walk pruned
    inline and the Saxo and eToro walks never did, so on the box where
    IBKR is being retired the table grew by a row every 900 s for ever —
    some 35,000 rows a year per account. Scoped to the (broker,
    account_pk) the walk just read, never fleet-wide, and called inside
    the walk's history try beside the insert, so a failed prune is the
    same logged warning as a failed insert and never a failed sync.
    """
    from datetime import timedelta

    from .equity_models import BrokerEquityReading
    BrokerEquityReading.objects.filter(
        broker=broker, account_pk=account_pk,
        at__lt=now - timedelta(days=EQUITY_HISTORY_DAYS)).delete()


#: THE eTORO WALK'S BEAT (config/celery.py "sync-etoro-accounts"): every
#: 30 s since 2026-11-13 (the operator: "aussi le refresh etoro par minute
#: est toujours trop long, je suggère 20-30 secondes non?"; every 60 s from
#: 2026-11-06, 300 s from 2026-10-31). What was tuned to the 60 s pass is
#: kept in wall-clock terms from this figure: the history's slack (below),
#: the stall alert's count (BROKER_MISS_ALERT_AFTER_BY_KIND, _beats_missed)
#: and the passes that note the venue's health and ask the shock trigger,
#: one per minute of the clock (ETORO_SYNC_TURN_S).
ETORO_SYNC_BEAT_S = 30

#: THE eTORO WALK'S HISTORY KEEPS ITS FIVE MINUTES (2026-11-06): the walk
#: beats every 60 s and writes its cells and its equity every pass, and a
#: history row at most every ETORO_HISTORY_EVERY_S, the density of its old
#: 300 s beat, less ETORO_HISTORY_SLACK_S so a beat that lands a few
#: seconds early still writes the fifth pass's row. Five rows a beat would
#: make every reader that walks the history five times longer: the 90-day
#: high-water mark every real entry's posture reads
#: (capital_truth.equity_high_water), the shock's 24 h (share_allocator).
#: HALF A BEAT OF SLACK (2026-11-13): at the 30 s beat a 30 s slack made
#: the ninth pass (270 s) due, a row every 270 s; half the beat keeps a row
#: every 300 s on time, and never closer than 285 s after a late pass.
ETORO_HISTORY_EVERY_S = 300
ETORO_HISTORY_SLACK_S = ETORO_SYNC_BEAT_S // 2

#: ONE eTORO PASS AT A TIME (2026-11-13): at 30 s, a pass whose reads time
#: out (two accounts, two reads each, each read and its one retry bounded
#: by the client's 10 s on connect and on read, the retry's 0.8 s between:
#: up to 163 s) would meet the next beats' passes; before this, nothing
#: stopped them stacking up on the worker beside the tick. A beat that
#: finds the lock held is idle (_one_etoro_pass): it sends nothing, counts
#: no miss and writes no component row. The lock outlives the longest
#: failing pass and is given back when the pass ends, however it ends; a
#: pass killed mid-way holds the sync three minutes at most.
#: SIZED FOR TWO KEYED ACCOUNTS ON ONE RESOLVED ADDRESS (review,
#: 2026-11-13): 2 x 2 x (2 x 20 s + 0.8 s) = 163 s. A third account, an
#: API host whose several addresses each eat the 10 s connect, or a DNS or
#: database stall can outlive it; the next beat's pass then starts beside
#: it, never a third, since a pass gives back only its own lock.
ETORO_SYNC_LOCK_KEY = "etoro_sync:pass"
ETORO_SYNC_LOCK_S = 180
#: THE VENUE'S HEALTH FROM ONE PASS A MINUTE PER ACCOUNT (2026-11-13,
#: venue_health.old_beat_turn): the first pass of each minute of the clock
#: (a window of the old 60 s beat), the minute its beat sent it in
#: (_beat_sent_at). A failing pass is two failed reads (the aggregate and
#: /portfolio), and three inside 180 s make eToro SICK for ten minutes;
#: noted from every 30 s pass, a 30 s hiccup would make eToro sick from the
#: sync alone (simulated 57 %, 0 % at 60 s). The same turn asks the shock
#: trigger (the final check, F4, 2026-11-13: sync_etoro_accounts). ON A
#: FIXED GRID since the third round (2026-11-13): until then the turn came
#: back 55 s after the last one, and a late or long pass moved every turn
#: after it.
ETORO_SYNC_TURN_S = 60
ETORO_SYNC_NOTE_KEY = "etoro_sync:noting:{pk}"


def _etoro_history_due(account_pk, now) -> bool:
    """True when the eToro account's newest history row is at least
    ETORO_HISTORY_EVERY_S old (less the slack), or none is stored. Raises
    what the read raises (the caller's history try)."""
    from .equity_models import BrokerEquityReading
    newest = (BrokerEquityReading.objects
              .filter(broker="etoro", account_pk=account_pk)
              .order_by("-at").values_list("at", flat=True).first())
    if newest is None:
        return True
    return ((now - newest).total_seconds()
            >= ETORO_HISTORY_EVERY_S - ETORO_HISTORY_SLACK_S)


def _follow_the_account(user, value, currency) -> None:
    """Retune every pool that OPTED IN to follow the broker's reading.

    Phase B, operator-requested: "trade on the available funds, not the
    number I typed once." The opt-in lives in
    extras["capital_tracks_broker"], and the ONLY writer is this sync —
    the same beat that stored the reading, so the pool and the reading
    can never quote two different syncs. The entry paths freeze an
    opted-in pool when the reading goes stale
    (capital_truth.tracking_freeze_reason): following an account nobody
    can read is following a memory.

    Each follower takes a SHARE of the reading — explicit, or an equal
    split of what the explicit ones leave (capital_truth.allocate_shares).
    Shares that do not fit in one account retune NOTHING and raise one
    alert per six hours: writing them would size every pool against money
    the others already claim. With shared capital ON (shared_capital_live,
    2026-10-01) every follower is written the WHOLE base, or its explicit
    share as its own ceiling: one pool, first come first served, and the
    account's limits at the order (cash, MAX ACCOUNT PLEDGED, the daily
    loss) are what bind.

    WITHDRAWALS ASKED FOR IN ADVANCE (2026-09-28). The shares apply to the
    reading LESS what is held back for withdrawals (withdrawals.held_back:
    every request still reserved, plus any withdrawal paid since this
    reading was taken), floored at zero, taken off ONCE before any share
    is applied. So every follower shrinks by the same proportion, the
    shares themselves are untouched, and this path — as ever — only saves
    `capital` (and its label, below): nothing is sold to find the money,
    it simply stops being deployed and builds up as positions close. What
    was held back is on the INFO line below, beside every pool it shrank.
    If the reserve cannot be read, nothing is retuned: sizing the pools
    from the whole reading would deploy money somebody has asked to take
    out.

    THE LABEL TRAVELS WITH THE FIGURE (2026-11-12). A follower's figure
    is the reading's, in the reading's currency, and this path wrote the
    figure and never its label (`base_currency`): a follower labelled in
    another currency than the account kept the old label for ever, and
    the cash check (AssetBot._cash_gate) refused every eToro order of it,
    "pool in EUR against cash read in USD". The reading's currency is
    written into `base_currency` in the same save as the figure, and a
    follower already at the figure whose label differs is relabelled too.
    A reading with no currency writes no label (the last one a reading
    carried stands); a pool that does not follow the account carries a
    figure typed in its own label and is never relabelled here. The
    operator is told (_alert_relabelled, the review of 2026-11-12): one
    alert for a sync that relabels, naming each pool and its old label,
    because the label is a field he types on /asset-bots/ and the sync
    writes over it within a minute.
    """
    from decimal import Decimal

    from .capital_truth import allocate_shares, followers_of

    try:
        followers = followers_of(user)
        if not followers:
            return
        alloc = allocate_shares(followers)
        if not alloc["ok"]:
            logger.error("broker sync: NO pool retuned for %s — %s",
                         user.username, alloc["reason"])
            _alert_over_allocation(user, alloc["reason"])
            return
        # THE RESERVE, once, before any share: raises into the except
        # below on a failed read, and then nothing is retuned.
        from .withdrawals import deployable
        base, held = deployable(user, value)
        if held > 0:
            logger.info("broker sync: %s — %s %s held back for withdrawal "
                        "requests; the pools follow %s of the %s read",
                        user.username, f"{held:,.2f}", currency or "",
                        f"{base:,.2f}", f"{float(value):,.2f}")
        # WHICH BROKER EACH FOLLOWER ACTUALLY REACHES. One book, one
        # reading, but the router picks per asset class — so a follower that
        # trades somewhere else must not be sized from here. The test is
        # capital_truth.foreign_venue (every symbol, not the first; only a
        # known and different venue refuses), shared since 2026-09-28 with
        # the withdrawals page, so the page's "with the reserve" column and
        # this loop can never disagree about which pools move.
        from .capital_truth import broker_backed, broker_kind, foreign_venue
        _book = broker_backed(user)
        _book_kind = broker_kind(_book) if _book is not None else ""

        # One lookup per SYMBOL per sync, shared across pools: every
        # follower is non-paper, so the routing of a symbol does not differ
        # between them.
        _venue_of: dict = {}
        # The reading's currency, the label every follower's figure is in
        # ("" when the reading carries none: no label is written).
        label = _reading_label(currency)
        relabelled = []

        for cfg in followers:
            foreign = foreign_venue(user, cfg, _book_kind, _venue_of)
            if foreign:
                logger.warning(
                    "broker sync: %s pool %r NOT retuned — it trades at %s "
                    "while the book is %s, and sizing it from the book would "
                    "measure one account and trade another",
                    user.username, cfg.name, foreign, _book_kind)
                continue
            share = float(alloc["plan"].get(cfg.pk, 0.0))
            new = Decimal(str(round(float(base) * share, 2)))
            old_label = str(cfg.base_currency or "")
            relabel = bool(label) and old_label.strip().upper() != label
            if cfg.capital == new and not relabel:
                continue
            old = cfg.capital
            cfg.capital = new
            fields = ["capital"]
            if relabel:
                cfg.base_currency = label
                fields.append("base_currency")
            cfg.save(update_fields=fields)
            logger.info("broker sync: %s pool follows the account at "
                        "%.1f%%: %s -> %s %s%s", cfg.name, share * 100.0,
                        old, new, currency or "",
                        (f" ({held:,.2f} held back for withdrawals)"
                         if held > 0 else ""))
            if relabel:
                logger.warning("broker sync: %s pool relabelled %s -> %s: "
                               "its figure is the account's reading, in %s",
                               cfg.name, old_label or "(none)", label, label)
                relabelled.append(f"{cfg.name}: "
                                  f"{old_label.strip() or '(none)'} -> "
                                  f"{label}")
        if relabelled:
            _alert_relabelled(user, label, relabelled)
    except Exception as e:  # noqa: BLE001 — the stored reading must stand
        logger.warning("broker sync: pool-follow failed: %s", e)


def _alert_relabelled(user, label: str, lines) -> None:
    """One alert to the pools' owner for a sync that relabelled followers
    (the review of 2026-11-12): which pools, from what label to `label`.
    The label is a field the operator types on /asset-bots/, and the sync
    writes over it on a follower within a minute; a log line in the
    worker was its only trace. The owner's own system_health alert, as
    notify_broker_unreachable sends one: the pools are his, and a relabel
    happens once per label written, so it needs no cooldown."""
    try:
        from .notifications import dispatch_notification
        dispatch_notification(
            user, "system_health",
            title=f"Pool label set to {label} by the account sync",
            body=("; ".join(lines)
                  + f". A pool that follows the account holds the "
                    f"account's reading, which is in {label}, so its label "
                    f"is the reading's currency. To keep a label of your "
                    f"own, stop the pool following the account."),
            url="/asset-bots/")
    except Exception as e:  # noqa: BLE001 — an alert must never fail the sync
        logger.warning("broker sync: relabel alert failed: %s", e)


def _reading_label(currency) -> str:
    """The label a reading's currency writes on a follower: its code,
    upper case, or "" when the reading carries none (or one that does not
    fit the column, AssetBotConfig.base_currency, ten characters)."""
    code = str(currency or "").strip().upper()
    return code if 0 < len(code) <= 10 else ""


def _alert_over_allocation(user, reason: str) -> None:
    """Once per six hours: the followers ask for more than one account."""
    try:
        from .notifications import notify_staff
        notify_staff(
            title="⚠ Pools over-allocated — nothing follows the account",
            body=(f"{user.username}: {reason}. No pool was retuned this "
                  f"sync and none will be until the shares fit in 100%. "
                  f"Lower a share on /admin-dashboard/ (manual lane) or "
                  f"/asset-bots/, or stand a follower down."),
            url="/asset-bots/", cooldown_hours=6)
    except Exception as e:  # noqa: BLE001 — an alert must never fail the sync
        logger.warning("broker sync: over-allocation alert failed: %s", e)


# ── The stall alert ───────────────────────────────────────────────────────
# Three consecutive misses (45 minutes) before a word is said, and then one
# word per six hours: a live Gateway restarts for 2FA roughly daily, and an
# alert that fires on every single blip is an alert the operator mutes.
BROKER_MISS_ALERT_AFTER = 3
BROKER_MISS_ALERT_COOLDOWN = 6 * 3600
#: THE eTORO WALK COUNTS FIFTEEN (2026-11-06). It beats every 60 s since
#: the operator's "augmenter to the maximum le taux de refresh", and three
#: of its misses would be three minutes, a blip the alert was written to sit
#: out (three passes were fifteen minutes at its 300 s beat). Fifteen passes
#: keep the fifteen minutes, for the stall alert and the alarm alike
#: (bot_program/alarm.read_brokers). IBKR and Saxo keep three (900 s).
#: THIRTY SINCE 2026-11-13: the walk beats every 30 s ("je suggère 20-30
#: secondes non?"), and thirty of its beats are the fifteen minutes.
ETORO_STALL_AFTER_S = 15 * 60
BROKER_MISS_ALERT_AFTER_BY_KIND = {
    "etoro": ETORO_STALL_AFTER_S // ETORO_SYNC_BEAT_S}
#: A MISS COUNTS THE BEATS IT STOOD FOR (2026-11-13), on the walks that
#: hold a pass lock: a failing eToro pass that outlives its beat (its reads
#: timing out, up to ~163 s) holds the beats behind it, and counted one
#: miss a pass the thirty would take 45 to 90 minutes. Each miss counts the
#: walk's beats since the account's last counted miss (_beats_missed):
#: floor(elapsed / beat), at least one, at most BROKER_MISS_MAX_BEATS (the
#: beats the lock can hold behind a pass, and the pass's own: a worker
#: down an hour sent no pass, and its beats were not eToro's misses). The
#: first miss of a run counts one, and floor never counts a late pass
#: followed by an on-time one as more than two. The count then reads as
#: beats, and every reader of it (this alert, the alarm, the words) is
#: unchanged. IBKR and Saxo count one a miss, as before.
BROKER_MISS_BEAT_S = {"etoro": ETORO_SYNC_BEAT_S}
BROKER_MISS_MAX_BEATS = ETORO_SYNC_LOCK_S // ETORO_SYNC_BEAT_S + 1


def broker_miss_alert_after(kind) -> int:
    """Consecutive missed syncs of `kind`'s walk ("etoro", "saxo", "ibkr")
    before the stall alert and the alarm say so (2026-11-06)."""
    return int(BROKER_MISS_ALERT_AFTER_BY_KIND.get(
        str(kind or ""), BROKER_MISS_ALERT_AFTER))


@shared_task
@guarded_task("broker_account_sync")
def sync_saxo_accounts():
    """Read every Saxo account with a live session: equity, holdings, one
    history row.

    The Saxo twin of sync_etoro_accounts. A row whose session is not alive
    is skipped, not attempted: the keeper (refresh_saxo_sessions) owns the
    session's health and the page already says "sign in again", so
    attempting it here would count a known sign-in as an unreachable
    broker and raise the staff alert twice for one fact.

    `attempted` and `stored` are the gate's work/done counters.
    """
    from django.utils import timezone

    from .engine.saxo_client import SaxoTrader
    from .models import SaxoAccount

    out = {"attempted": 0, "stored": 0, "unreachable": 0, "no_session": 0}
    for acct in SaxoAccount.objects.exclude(app_key_enc=""):
        if not acct.session_alive():
            out["no_session"] += 1
            continue
        user = acct.user
        out["attempted"] += 1
        reading, rows = None, None
        try:
            client = SaxoTrader(acct)
            reading = client.net_liquidation()
            rows = client.broker_portfolio()
        except Exception as e:  # noqa: BLE001 — one account must not stop the rest
            logger.warning("broker sync: %s (saxo) unreadable: %s",
                           acct.label, e)
            reading, rows = None, None

        if reading is None and rows is None:
            out["unreachable"] += 1
            _note_broker_miss(acct, user)
            continue
        _clear_broker_miss(acct)

        now = timezone.now()
        fields = []
        if reading is not None:
            value, currency = reading
            acct.last_equity = value
            acct.last_equity_currency = currency
            acct.last_equity_at = now
            fields += ["last_equity", "last_equity_currency", "last_equity_at"]
        if rows is not None:
            acct.broker_positions = rows
            acct.broker_positions_at = now
            fields += ["broker_positions", "broker_positions_at"]
        acct.connected = True
        acct.last_sync = now
        fields += ["connected", "last_sync"]
        acct.save(update_fields=fields)

        if reading is not None:
            from .equity_models import BrokerEquityReading
            try:
                BrokerEquityReading.objects.get_or_create(
                    broker="saxo", account_pk=acct.pk, at=now,
                    # Saxo's SIM and LIVE are two worlds on ONE row: without
                    # this, a simulated balance and a real one are
                    # indistinguishable in the same account's history.
                    defaults={"value": value, "currency": currency,
                              "env": "paper" if acct.sim else "live",
                              "account": None})
                _prune_equity_history("saxo", acct.pk, now)
            except Exception as e:  # noqa: BLE001 — a history row is not the sync
                logger.warning("broker sync: %s (saxo) history row failed: %s",
                               acct.label, e)

        # The gate's DONE counter: a pass that wrote the cells has stored
        # something whether or not the history row landed and whether or
        # not there was an equity reading. Counting it inside the history
        # try graded the component "handled N rows and stored none".
        out["stored"] += 1

        # A pool that tracks the account is re-sized by the sync and by
        # nothing else, and tracking_freeze_reason refuses every entry
        # once the reading ages past an hour — so a Saxo book that never
        # ran these two would quietly stop trading. Gated on being THE
        # BOOK: two brokers retuning the same pools would fight.
        if reading is not None:
            from .capital_truth import broker_backed
            book = broker_backed(user)
            if book is not None and type(book) is type(acct) \
                    and book.pk == acct.pk:
                _follow_the_account(user, value, currency)
                _shock_trigger(user, now)
    if not out["attempted"]:
        # IDLE (2026-09-26): no keyed Saxo account, or none with a live
        # session — the keeper (refresh_saxo_sessions) owns the session and
        # /brokers/ already says "sign in again". Nothing was read, so the
        # gate writes nothing to the row the three walks share; see the
        # IBKR walk above and core.task_gate.guarded_task.
        out["idle"] = ("no live Saxo session" if out["no_session"]
                       else "no keyed Saxo account")
    return out


@shared_task
def refresh_saxo_sessions():
    """Rotate every Saxo row's tokens. Ungated — see the module note in
    engine/saxo_oauth.py and the docstring of this patch.

    The counters are the honest ones for a keeper: `attempted` rows with a
    refresh token, `renewed` rotations that landed, `lost` sessions whose
    refresh token was past its life when the refresh failed. A transient
    failure inside the window counts as neither — it is logged, the session
    is kept, and the next cycle tries again.
    """
    from django.utils import timezone

    from .engine import saxo_oauth
    from .models import SaxoAccount

    out = {"attempted": 0, "renewed": 0, "lost": 0, "retry": 0}
    now = timezone.now()
    for acct in SaxoAccount.objects.exclude(refresh_token_enc=""):
        out["attempted"] += 1
        try:
            payload = saxo_oauth.refresh(acct)
            saxo_oauth.store_tokens(acct, payload, now=now)
            out["renewed"] += 1
        except Exception as e:  # noqa: BLE001 — one row must not stop the rest
            deadline = acct.refresh_expires_at
            if deadline is not None and now < deadline:
                out["retry"] += 1
                logger.warning(
                    "saxo session: %s refresh failed (%s: %s) — the refresh "
                    "token is still alive until %s, retrying next cycle",
                    acct.label, type(e).__name__, e, deadline.isoformat())
                continue
            reason = f"{type(e).__name__}: {e}"[:120]
            # Compare-and-clear: only a row STILL holding the token that
            # just failed is cleared. A concurrent run that rotated it in
            # the meantime keeps its fresh session — this failure was about
            # a token that no longer exists.
            n = SaxoAccount.objects.filter(
                pk=acct.pk, refresh_token_enc=acct.refresh_token_enc,
            ).update(access_token_enc="", refresh_token_enc="",
                     token_expires_at=None, refresh_expires_at=None,
                     connected=False, session_lost_at=now,
                     session_lost_reason=reason)
            if n != 1:
                logger.info("saxo session: %s was rotated by another run "
                            "while this one failed — nothing cleared",
                            acct.label)
                continue
            out["lost"] += 1
            logger.warning(
                "saxo session: %s is LOST (%s) — the refresh token was past "
                "its life. Sign in again at /brokers/. Nothing on Saxo can "
                "be read or traded until then.", acct.label, reason)
            try:
                from .notifications import notify_staff
                notify_staff(
                    title="Saxo session LOST — sign in again at /brokers/",
                    body=f"{acct.label}: {reason}", url="/brokers/",
                    cooldown_hours=6)
            except Exception as alert_err:  # noqa: BLE001 — an alert must never fail the keeper
                logger.warning("saxo session: staff alert failed (%s: %s)",
                               type(alert_err).__name__, alert_err)
    return out


#: Row class -> the `broker` value its readings and miss keys are filed
#: under. A class missing here would file as "ibkr" and its outage would
#: count against IBKR's alert — so every account row that the sync can
#: reach belongs in this table.
_BROKER_KINDS = {"EtoroAccount": "etoro", "SaxoAccount": "saxo"}


def _users_with_a_broker_row():
    """Every user who has keyed ANY broker, once each.

    One place, because three callers had written "IBKRAccount.objects.
    exclude(account_id_enc='')" and each of them silently skipped a Saxo
    or an eToro book.
    """
    from django.contrib.auth import get_user_model

    from .models import EtoroAccount, IBKRAccount, SaxoAccount

    ids = set(IBKRAccount.objects.exclude(account_id_enc="")
              .values_list("user_id", flat=True))
    ids |= set(EtoroAccount.objects.exclude(api_key_enc="")
               .values_list("user_id", flat=True))
    ids |= set(SaxoAccount.objects.exclude(app_key_enc="")
               .values_list("user_id", flat=True))
    return (get_user_model().objects
            .filter(pk__in=[i for i in ids if i]).order_by("username"))


def _broker_kind(acct) -> str:
    """The `broker` value this row's readings and miss keys are filed under.
    Mirrors capital_truth.broker_kind; duplicated here rather than imported
    so the miss helpers stay importable when capital_truth is not."""
    return _BROKER_KINDS.get(type(acct).__name__, "ibkr")


def _one_etoro_pass(fn):
    """ONE eTORO PASS AT A TIME (2026-11-13, ETORO_SYNC_LOCK_KEY), between
    the gate and the walk. A beat that finds a pass running returns `idle`
    (core.task_gate writes no component row for it), reads nothing and
    counts no miss; the lock is given back however the pass ends. A lock
    that cannot be read runs the pass, as before the lock: the request
    budget asks no account read while its cache is down anyway.

    GIVEN BACK BY ITS OWNER ONLY (review, 2026-11-13): the lock holds the
    pass's own token, and the pass deletes it only while it still holds
    that token. A pass can outlive the lock's ETORO_SYNC_LOCK_S (an API
    host whose several addresses each eat the 10 s connect, a stalled DNS
    or database); the next beat's pass then takes the lock, and the first,
    ending, freed THAT pass's lock, so the beat after started a third
    beside it. Now at most two ever overlap, and only past the lock's
    three minutes."""
    import functools
    import uuid

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        from django.core.cache import cache
        token = f"{timezone_now_iso()} {uuid.uuid4().hex[:12]}"
        try:
            held = cache.add(ETORO_SYNC_LOCK_KEY, token, ETORO_SYNC_LOCK_S)
        except Exception as e:  # noqa: BLE001 — no lock: the pass as before
            logger.warning("broker sync (etoro): the pass lock could not be "
                           "read (%s); the pass runs without it",
                           type(e).__name__)
            held = None
        if held is False:
            logger.info("broker sync (etoro): a pass is still running — this "
                        "beat reads nothing")
            return {"idle": "an eToro pass is still running; this beat reads "
                            "nothing"}
        try:
            return fn(*args, **kwargs)
        finally:
            if held:
                try:
                    if cache.get(ETORO_SYNC_LOCK_KEY) == token:
                        cache.delete(ETORO_SYNC_LOCK_KEY)
                    else:
                        logger.warning(
                            "broker sync (etoro): this pass outlived its "
                            "lock (%d s); the lock is gone or another "
                            "pass's, and is left as it is",
                            ETORO_SYNC_LOCK_S)
                except Exception:  # noqa: BLE001 — it expires on its own
                    pass
    return wrapper


def _beat_sent_at(task, beat: str, now: float) -> float:
    """THE INSTANT THE BEAT SENT THIS RUN (the third round, 2026-11-13):
    what the old beats' turns are keyed on (venue_health.old_beat_turn), so
    a run the worker starts late keeps the window its beat was sent in. The
    database scheduler gives each run the entry's expiry (expire_seconds,
    config/celery.py `beat`'s options), Celery stamps it as the send
    instant plus that expiry (the `expires` header, the run's
    request.expires), and the worker drops the run once it is past: the
    send instant is `expires` less the expiry. `now` (epoch seconds, the
    wall clock at the run's start) stands in for a run with no expiry or
    called directly (tests, the shell), and for one whose expiry does not
    fit its start (sent after it, or more than the expiry and 5 s before
    it: an expiry an admin changed on the stored row, say). Never
    raises."""
    try:
        from datetime import datetime as _dt
        expires = getattr(task.request, "expires", None)
        if not expires:
            return now
        when = (expires if isinstance(expires, _dt)
                else _dt.fromisoformat(str(expires)))
        if when.tzinfo is None:
            return now
        expiry = float(
            task.app.conf.beat_schedule[beat]["options"]["expire_seconds"])
        sent = when.timestamp() - expiry
        if sent > now + 1.0 or sent < now - expiry - 5.0:
            return now
        return sent
    except Exception:  # noqa: BLE001 — unread: the wall clock, as before
        return now


def _quiet_between_noting_passes(client, account_pk, at=None) -> bool:
    """THE VENUE'S HEALTH FROM ONE PASS A MINUTE (2026-11-13): a pass that
    does not hold the account's turn (venue_health.old_beat_turn: the
    first pass of its minute of the clock, ETORO_SYNC_TURN_S, keyed on
    `at`, epoch seconds: the instant its beat sent it, _beat_sent_at, or
    its start) reads, writes and counts its miss as every pass does, and
    its client notes no READ failure (EtoroTrader.health_quiet).
    True when this pass holds the turn: it notes, and it alone asks the
    shock trigger (the final check, F4: sync_etoro_accounts). Never raises:
    a turn that cannot be read notes and asks, as before the turns
    (True)."""
    try:
        from django.utils import timezone

        from . import venue_health
        if at is None:
            at = timezone.now().timestamp()
        noting = venue_health.old_beat_turn(
            ETORO_SYNC_NOTE_KEY.format(pk=account_pk),
            ETORO_SYNC_TURN_S, at=at)
        client.health_quiet = (
            "" if noting else
            f"the account sync notes the venue's health from one pass a "
            f"minute; this {ETORO_SYNC_BEAT_S} s pass reads only")
        return bool(noting)
    except Exception as e:  # noqa: BLE001 — unread: noted, as before
        logger.debug("broker sync: the noting slot was not read (%s)",
                     type(e).__name__)
        return True


@shared_task
@guarded_task("broker_account_sync")
@_one_etoro_pass
def sync_etoro_accounts():
    """Read every keyed eToro account: equity, holdings, one history row.

    The eToro twin of sync_broker_account, and deliberately NOT a branch
    inside it — that loop leases IBKR session slots and carries a year of
    2FA-shaped guards. Same component switch, same five cells, same history
    shape keyed (broker="etoro", account_pk). One switch governs "does the
    platform read its brokers"; one row shape means the drawdown governor
    and the preflight read eToro exactly as they read IBKR.

    Not gated on broker_backed(): a keyed row's equity is a fact worth
    storing whether or not that row is currently "the book". The page
    shows last_sync for it either way.

    `attempted` and `stored` are the gate's work/done counters, so a walk
    that read N accounts and stored nothing is judged as such rather than
    returning a clean dict.

    EVERY 30 s since 2026-11-13 (ETORO_SYNC_BEAT_S; the operator: "aussi le
    refresh etoro par minute est toujours trop long, je suggère 20-30
    secondes non?"), one pass at a time (_one_etoro_pass), each account's
    read failures noted on the venue's health from one pass a minute, the
    first of the minute of the clock its beat sent it in (_quiet_between_
    noting_passes, _beat_sent_at), the shock trigger asked from that same
    pass only (the old 60 s beat's pace, below), a miss counting the beats
    it stood for (_beats_missed), the history one row in five minutes.
    """
    from django.utils import timezone

    from .engine import etoro_budget
    from .engine.etoro_client import EtoroTrader
    from .models import EtoroAccount

    out = {"attempted": 0, "stored": 0, "unreachable": 0, "cells_unread": 0}
    # THE INSTANT THE BEAT SENT THIS PASS (the third round, 2026-11-13):
    # every account's turn is the minute of the clock it falls in, however
    # late the worker started the pass and whenever the walk reaches the
    # account (_beat_sent_at, venue_health.old_beat_turn); the pass's start
    # when the run carries no expiry.
    started_at = _beat_sent_at(sync_etoro_accounts, "sync-etoro-accounts",
                               timezone.now().timestamp())
    # REAL FIRST (review, 2026-11-13): one key pair opens both worlds and
    # both spend one request budget, so whatever runs short in a pass (the
    # account minute's tokens, a lock that runs out, an exception that
    # stops the walk) reaches DEMO first, never REAL. SAID WHOLE (the final
    # check, 2026-11-13): main walked them with no ORDER BY, in whatever
    # order the database returned (Postgres moves a row with its updates).
    # Measured on the third round's code (the noting turns on the clock's
    # grid, venue_health.old_beat_turn): against a main that read REAL
    # first, a 5xx or 429 hiccup turns eToro sick with main's odds over
    # the clock's phases, each incident up to 30 s either way or on one
    # side only (timeouts: config/celery.py). Against one that read DEMO
    # first, REAL's reads come a DEMO read earlier in the pass: the same
    # odds under 5xx and 429s, each incident sooner in 558 of 1728 runs
    # (by up to 32.4 s) and later in 231; under timeouts sick more often
    # in 45 and 60 s hiccups (connect 37.5 and 50.0 % against 0 and
    # 16.7 %), up to 50.8 s sooner: new real entries are then held ten
    # minutes sooner, the cautious way. Closes and stop moves are never
    # held.
    for acct in (EtoroAccount.objects.exclude(api_key_enc="")
                 .order_by("demo", "pk")):
        user = acct.user
        k, u = acct.get_credentials()
        if not (k and u):
            continue
        out["attempted"] += 1
        reading, rows, margin, cells = None, None, None, CELLS_UNOFFERED
        read_at = None
        book_deferred = aggregate_sent = False
        holds_turn = True
        try:
            client = EtoroTrader(k, u, env="demo" if acct.demo else "live")
            holds_turn = _quiet_between_noting_passes(client, acct.pk,
                                                      at=started_at)
            # THE STAMP IS TAKEN BEFORE THE READ (2026-10-31). The cells
            # are dated by the instant the GET left, not by the end of the
            # pass: AssetBot._pledged_since charges every row opened AFTER
            # last_margin_at, so a fill whose row landed between the read
            # and a later stamp was in neither the cells nor the charge.
            # Stamped first, such a row is charged (and, when the payload
            # already carried it, counted twice until the next read — the
            # safe way round).
            read_at = timezone.now()
            # P2 IN THE eTORO REQUEST BUDGET (2026-11-01, engine/
            # etoro_budget): an account read, taken while the key's
            # account minute keeps its floor for the drain and the orders.
            with etoro_budget.at_priority(etoro_budget.P2, "account sync"):
                reading, margin, cells = _read_etoro_aggregate(client)
                aggregate_sent = True
                try:
                    _warm_etoro_names(client, user, acct.demo)
                    rows = client.broker_portfolio()
                except Exception as e:  # noqa: BLE001
                    if not (getattr(e, "budget_refused", False)
                            and cells == CELLS_READ):
                        raise
                    # THE AGGREGATE ANSWERED, THE BOOK WAS NOT SENT
                    # (2026-11-02, completes E1): the cash, the used margin
                    # and the equity it answered are written as a pass's
                    # (they were thrown away, and the cash gate judged the
                    # next entries on cells a pass older); the holdings
                    # keep their own stamp, and nothing is a miss.
                    rows, book_deferred = None, True
                    out["book_deferred"] = out.get("book_deferred", 0) + 1
                    logger.info("broker sync: %s (etoro) holdings not read "
                                "this pass — %s; the cells it answered are "
                                "written", acct.label, e)
        except Exception as e:  # noqa: BLE001 — one account must not stop the rest
            if getattr(e, "budget_refused", False):
                # THE BUDGET DID NOT SEND THE READ (2026-11-01): a
                # deferral, never a miss. No stall count, no alert, no
                # field written: the cells, the equity and last_sync keep
                # their age, and the next pass reads them.
                out["attempted"] -= 1
                out["deferred"] = out.get("deferred", 0) + 1
                logger.info("broker sync: %s (etoro) not read this pass — "
                            "%s; it keeps its last reading", acct.label, e)
                _note_deferred_beat(acct)
                if not aggregate_sent and read_at is not None:
                    # AND ITS eTORO ENTRIES WAIT FOR THE NEXT READ
                    # (2026-11-02, completes E1): the cells and the equity
                    # this pass did not read would have been fresher, and
                    # an entry they would have refused must not go on the
                    # older ones (AssetBot._cash_gate reads this note)
                    from . import etoro_cells
                    etoro_cells.note_sync_deferred(acct.pk, read_at)
                continue
            logger.warning("broker sync: %s (etoro) unreadable: %s",
                           acct.label, e)
            reading, rows = None, None
            if cells == CELLS_READ:
                # the aggregate answered and a later read raised: the cells
                # in hand are a measurement, but this pass is a miss
                margin, cells = None, CELLS_UNOFFERED

        if reading is None and rows is None and not book_deferred:
            out["unreachable"] += 1
            _note_broker_miss(acct, user)
            continue
        if cells == CELLS_FAILED:
            # A pass whose cash and used margin did not answer is a MISSED
            # sync for the stall alert too (2026-10-31): those are the
            # cells every eToro order is judged on, and a holdings list
            # that answered beside them used to clear the count, so a
            # failing aggregate read never reached the operator. Said as
            # what it is (review, 2026-10-31): eToro answered this pass,
            # so the alert names the cells, never "unreachable" or keys.
            _note_broker_miss(acct, user, cells_only=True,
                              holdings_answered=rows is not None)
        else:
            _clear_broker_miss(acct)

        now = read_at or timezone.now()
        fields = []
        if cells == CELLS_FAILED:
            # THE CASH AND THE MARGIN DID NOT ANSWER (2026-10-31): the
            # equity and last_sync are not refreshed alone. Refreshing
            # them made every page that dates the account by last_sync
            # read current while the cash gate went on judging from cells
            # one, two, four syncs old, up to the hour that refuses every
            # eToro order. The holdings snapshot keeps its own stamp.
            out["cells_unread"] += 1
            reading = None
            logger.warning(
                "broker sync: %s (etoro) answered no cash / used margin "
                "this pass — the equity, the cells and last_sync stay at "
                "their last reading", acct.label)
        if reading is not None:
            value, currency = reading
            fields += _etoro_equity_fields(acct, reading, now)
        if rows is not None:
            acct.broker_positions = rows
            acct.broker_positions_at = now
            fields += ["broker_positions", "broker_positions_at"]
        acct.connected = True
        fields.append("connected")
        if cells != CELLS_FAILED:
            acct.last_sync = now
            fields.append("last_sync")
        if margin is not None:
            fields += _etoro_margin_fields(acct, client, margin, now)
        acct.save(update_fields=fields)

        if reading is not None:
            from .equity_models import BrokerEquityReading
            try:
                # ONE HISTORY ROW IN FIVE MINUTES (2026-11-06): the walk
                # beats every 60 s (every 30 s since 2026-11-13), its cells
                # and equity are written every pass, and the history keeps
                # the 300 s beat's density, so the readers that walk it
                # (the high-water mark over 90 days on every real entry's
                # posture, the shock's 24 h) read what they read before.
                if _etoro_history_due(acct.pk, now):
                    BrokerEquityReading.objects.get_or_create(
                        broker="etoro", account_pk=acct.pk, at=now,
                        defaults={"value": value, "currency": currency,
                                  "env": "paper" if acct.demo else "live"})
                    _prune_equity_history("etoro", acct.pk, now)
            except Exception as e:  # noqa: BLE001 — the cell is written; history must not fail the sync
                logger.warning("broker sync: %s (etoro) history row failed: "
                               "%s", acct.label, e)

        # Same two corrections as the Saxo walk, for the same reasons: the
        # gate's DONE counter belongs to the pass, and a pool that tracks
        # an eToro book has never been re-sized by anything.
        out["stored"] += 1
        if reading is not None:
            from .capital_truth import broker_backed
            book = broker_backed(user)
            if book is not None and type(book) is type(acct) \
                    and book.pk == acct.pk:
                _follow_the_account(user, value, currency)
                # THE SHOCK TRIGGER KEEPS THE OLD 60 s BEAT (the final
                # check, F4, 2026-11-13). A shock plan is an automated
                # money path: share_allocator_auto_derisk and the LIVE
                # mode on, it is applied with no human. It must not change
                # sensitivity as a side effect of a display refresh: asked
                # from every 30 s pass, it read the equity twice as often,
                # and a dip shorter than a minute was caught up to twice
                # as often. Asked only by the pass that holds the
                # account's turn (_quiet_between_noting_passes): the first
                # pass of each minute of the clock, the minute its beat
                # sent it in (_beat_sent_at), never two in one minute. A
                # pass that holds the turn and reads nothing (a miss, a
                # budget deferral) spends it, as the old beat's did; a beat
                # the lock idles holds none, and a minute whose first beat
                # it idled is asked by its second, 30 s later. ON A FIXED
                # GRID (the third round, 2026-11-13; until then a turn came
                # 55 s after the last, and with passes 0 to 24 s late it
                # was asked 15 % less often than at 60 s). Measured on the
                # real code (the PR's third round), REAL's asks: on time
                # one a minute, 60 s apart, at the 60 s beat's instants or
                # 30 s off them as the beat's phase falls on the clock, a
                # dip shorter than a minute caught exactly as often as at
                # 60 s at every phase; with passes 0 to 24 s late one a
                # minute, 36 to 84 s apart (at 60 s 37 to 84 s), a 10, 30
                # and 59 s dip caught 18.9, 48.3 and 90.0 % of the time
                # over the clock's phases against 17.8, 43.3 and 88.9 %, as
                # often within sampling (the 60 s beat's very runs in half
                # the phases; in the other half the asks sit on the beats
                # between, late by their own draws: over nine draws 14.4,
                # 53.3 and 90.0 % against 17.0, 49.6 and 88.9 %); where a
                # slow pass idles a minute's first beat (a 40 s stalled
                # read every third beat), asks 30 to 90 s apart, a 59 s dip
                # caught 83.3 % against 100 %, and with passes also 0 to
                # 24 s late both beats of a minute can find the lock held,
                # that minute unasked: asks 7 to 142 s apart, 80.0 %
                # against 91.1 %. The operator decides any change to it.
                # The pools above are still resized from every pass.
                if holds_turn:
                    _shock_trigger(user, now)
    if out["cells_unread"]:
        # Said on the component row in words: the holdings may have landed,
        # but the cells the cash gate reads did not (2026-10-31).
        out["status"] = "warning"
        out["reason"] = (f"{out['cells_unread']} eToro account(s) answered "
                         f"no cash / used margin; their equity, cells and "
                         f"last sync stay at the last reading")
    elif out.get("deferred") and not out["attempted"]:
        # Every keyed account deferred by the budget (2026-11-01): NOT A
        # RUN of the component, so the gate's `idle` (core/task_gate.
        # guarded_task) and the reason in words. broker_account_sync is the
        # row three walks share, and it keeps the verdict of the last pass
        # that read an account: a "skipped" status here was judged a
        # success (review), which turned an eToro error on that row green
        # and cleared the digest's fault. A walk the budget defers for a
        # whole day leaves the row unwritten, and the digest then says it
        # stopped: it read nothing that day.
        out["idle"] = (f"the eToro request budget deferred "
                       f"{out['deferred']} account read(s) to the next "
                       f"pass; each keeps its last reading")
        out["reason"] = out["idle"]
    return out


# ── The account's money cells, from one aggregate read (2026-10-31) ──────
#: What _read_etoro_aggregate learnt about the cash and the used margin:
#: read (a dict with at least one figure), failed (the one read failed, or
#: answered neither figure), or unoffered (an adapter, or a test double,
#: that states no cells at all: the equity is written as before).
CELLS_READ = "read"
CELLS_FAILED = "failed"
CELLS_UNOFFERED = "unoffered"
#: The rest of the aggregate payload, by the margin dict's key and the
#: EtoroAccount cell it is stored in (2026-10-31): display only, written
#: with the cells and never read by a gate.
DISPLAY_FIGURES = {"pnl": "last_pnl", "frozen_cash": "last_frozen_cash",
                   "balance": "last_balance"}


def _read_etoro_aggregate(client):
    """(reading, margin, state) from ONE aggregate-portfolio GET.

    The adapter's account_snapshot answers both from one payload. An
    adapter or a double without it is asked net_liquidation and
    margin_cells, as the sync asked before; a margin_cells that answers
    None there is a failed read, and anything else that is not a dict
    states no cells. Raises what the reads raise."""
    snap_fn = getattr(client, "account_snapshot", None)
    snap = snap_fn() if callable(snap_fn) else ...
    if snap is None:
        return None, None, CELLS_FAILED
    if isinstance(snap, dict) and "reading" in snap and "margin" in snap:
        reading = snap.get("reading")
        reading = (tuple(reading) if isinstance(reading, (tuple, list))
                   and len(reading) == 2 else None)
        margin = snap.get("margin")
        margin = margin if isinstance(margin, dict) else None
        # THE REST OF THE SAME PAYLOAD (2026-10-31): the P&L, the frozen
        # cash and the balance travel with the cells, so _etoro_margin_
        # fields writes them under the cells' one stamp. Display only.
        figures = snap.get("figures")
        if margin is not None and isinstance(figures, dict):
            margin = dict(margin, **{k: figures.get(k)
                                     for k in DISPLAY_FIGURES})
    else:
        reading = client.net_liquidation()
        _mc = getattr(client, "margin_cells", None)
        margin = _mc() if callable(_mc) else ...
        if margin is ...:
            return reading, None, CELLS_UNOFFERED
        if margin is not None and not isinstance(margin, dict):
            return reading, None, CELLS_UNOFFERED
    if not isinstance(margin, dict) or (
            margin.get("available_cash") is None
            and margin.get("used_margin") is None):
        return reading, None, CELLS_FAILED
    return reading, margin, CELLS_READ


def _etoro_equity_fields(acct, reading, at) -> list:
    """Write the equity cells of `reading` on `acct`; the fields to save."""
    value, currency = reading
    acct.last_equity = value
    acct.last_equity_currency = currency
    acct.last_equity_at = at
    return ["last_equity", "last_equity_currency", "last_equity_at"]


def _etoro_margin_fields(acct, client, margin, at) -> list:
    """Write the margin cells of `margin` on `acct`; the fields to save.

    THE MARGIN CELLS (2026-09-23), each on its own: a payload that carries
    one figure and not the other writes the one it carries. In the sync,
    the same save and the same `at` as the equity; the re-read after an
    order writes them alone under its own stamp, so the headroom gate
    dates the equity by last_equity_at as well (2026-10-31).

    THE CASH A READ DID NOT CARRY IS WRITTEN None (review, 2026-11-01).
    The stamp below dates both cells, so an older cash left under it read
    as seconds old: at 100% (base.free_cash_decides_alone) the cash is
    the gate's only money input, and a read that carried the used margin
    alone let through an order eToro's free cash may no longer cover. The
    gate refuses a cash its reading did not carry (AssetBot._cash_gate),
    at every ceiling, until a read carries one. The used margin a read
    did not carry still keeps its last figure (the ratio below 100% and
    Morgul's G6 read it; unchanged here)."""
    fields = []
    if margin.get("available_cash") is not None:
        acct.last_available_cash = margin["available_cash"]
        fields.append("last_available_cash")
    if margin.get("used_margin") is not None:
        acct.last_used_margin = margin["used_margin"]
        fields.append("last_used_margin")
    if fields:
        if "last_available_cash" not in fields:
            acct.last_available_cash = None
            fields.append("last_available_cash")
        acct.last_margin_at = at
        fields.append("last_margin_at")
        # THE WORLD THE CELLS WERE READ IN (2026-09-26): the client's own
        # (`EtoroTrader.demo`, the segment it POSTs to); the row's when a
        # double states none — the client was built from acct.demo, so on
        # a real read the two never differ. Read by _leverage_headroom.
        _demo = getattr(client, "demo", None)
        if not isinstance(_demo, bool):
            _demo = bool(acct.demo)
        acct.last_margin_world = "demo" if _demo else "live"
        fields.append("last_margin_world")
        # THE P&L, THE FROZEN CASH AND THE BALANCE (2026-10-31), from the
        # same payload and dated by the same stamp, so a figure this read
        # did not carry is written None rather than an older one left
        # under a new date. Only when the reader states them at all (the
        # adapter's account_snapshot does; a double without them leaves
        # the cells as they were). Display only (bot_program.etoro_used).
        for key, cell in DISPLAY_FIGURES.items():
            if key in margin:
                setattr(acct, cell, margin.get(key))
                fields.append(cell)
    return fields


@shared_task
def refresh_etoro_cells(account_pk: int, why: str = "") -> dict:
    """Re-read ONE eToro account's money right after the platform's own
    order or close (2026-10-31, bot_program.etoro_cells queues it).

    The operator: "wait 15min to make another trade". A close frees cash
    at eToro within the same second (MEASURED 2026-09-23: the margin
    cells move with the fill), and the gate that judges the next order
    (AssetBot._leverage_headroom) read it only from the sync's cells, up
    to a sync old: the freed cash was refused until the next beat.

    ONE aggregate-portfolio GET (account_snapshot), the sync's own read,
    and only that: the cash, the used margin and their world, written in
    one save under one stamp taken BEFORE the GET (the sync's rule). NOT
    the equity or its stamp: the pools that follow the account are
    retuned from that reading by the sync alone, and their entries freeze
    on its age (capital_truth.tracking_freeze_reason), so a re-read that
    refreshed it would hide a sync that stopped retuning them. The gate's
    pledge ratio divides by the sync's equity and dates it by its own
    stamp (review, 2026-10-31): past TRACKING_FRESH_SECONDS the gate
    refuses whatever the cells' age (AssetBot._cash_gate), so a re-read
    never makes an old equity pass there either — the equity is a beat
    old only while the sync runs.
    Not /portfolio, which lags fills and closes by about 60 s
    (PORTFOLIO_LAG_S): a holdings snapshot read 3 s after a close would
    still list it; the sync's beat reads it. Not last_sync, the history
    row or the shock plan: those stay the sync's too.

    Under the sync's own switches (platform_master, broker_account_sync),
    asked inline rather than through guarded_task: the component's row is
    the sync's verdict, and a re-read every few seconds must not overwrite
    it. A failed read writes nothing: the old cells keep their age, never
    a zero. Never raises."""
    from django.utils import timezone

    from core.platform_control import is_component_enabled

    from .models import EtoroAccount

    out = {"account": account_pk, "why": str(why or "")[:40], "read": False}
    try:
        if not (is_component_enabled("platform_master")
                and is_component_enabled("broker_account_sync")):
            out["skipped"] = "broker_account_sync is off"
            return out
        from . import etoro_cells
        etoro_cells.note_read_started(account_pk)
        acct = EtoroAccount.objects.filter(pk=account_pk).exclude(
            api_key_enc="").first()
        if acct is None:
            out["skipped"] = "no keyed eToro account"
            return out
        k, u = acct.get_credentials()
        if not (k and u):
            out["skipped"] = "the stored key could not be read"
            return out
        from .engine import etoro_budget
        from .engine.etoro_client import EtoroTrader
        client = EtoroTrader(k, u, env="demo" if acct.demo else "live")
        at = timezone.now()                # BEFORE the GET (see the sync)
        # P2 in the eToro request budget (2026-11-01): a read the budget
        # does not send writes nothing, and says so below.
        with etoro_budget.at_priority(etoro_budget.P2, "account re-read"):
            _reading, margin, cells = _read_etoro_aggregate(client)
        if cells != CELLS_READ or margin is None:
            logger.warning("eToro re-read (%s): %s answered no cash / used "
                           "margin — the cells keep their last reading",
                           out["why"] or "after an order", acct.label)
            return out
        fields = _etoro_margin_fields(acct, client, margin, at)
        # a save of the cells alone, never the whole row: the sync may be
        # writing the holdings at the same moment
        EtoroAccount.objects.filter(pk=acct.pk).update(
            **{f: getattr(acct, f) for f in fields})
        out["read"] = True
        logger.info("eToro re-read (%s): %s cash %s, used %s", out["why"]
                    or "after an order", acct.label,
                    margin.get("available_cash"), margin.get("used_margin"))
    except Exception as e:  # noqa: BLE001 — a re-read is beside the trade
        if getattr(e, "budget_refused", False):
            # not sent (2026-11-01): the cells keep their last reading and
            # their age, as after a failed read, and nothing is noted
            out["skipped"] = f"not asked: {getattr(e, 'why', '') or e}"
            logger.info("eToro re-read of account %s %s — the cells keep "
                        "their last reading", account_pk, out["skipped"])
            return out
        logger.warning("eToro re-read of account %s failed: %s",
                       account_pk, e)
    return out


@shared_task
def refresh_etoro_quotes() -> dict:
    """eToro's own quotes for the open real positions, every 30 s
    (2026-11-06; every 15 s since 2026-11-13, etoro_quotes.BEAT_S,
    bot_program/etoro_quotes.py): bid, ask and last for the instruments of
    the open real eToro rows, written to LiveQuote under the source
    "etoro", at P3 in the eToro request budget.

    Under the sync's own switches (platform_master, broker_account_sync),
    asked inline as refresh_etoro_cells asks them rather than through
    guarded_task: the component row is the sync's verdict, and a beat every
    15 s must not overwrite it. Never raises. Its turns on the venue's
    health are keyed on the instant the beat sent this run (_beat_sent_at,
    the third round, 2026-11-13)."""
    from .etoro_quotes import _now, refresh
    return refresh(at=_beat_sent_at(refresh_etoro_quotes,
                                    "refresh-etoro-quotes", _now()))


def _beats_missed(cache, kind, pk) -> int:
    """How many beats of `kind`'s walk this miss of account `pk` stands for
    (2026-11-13, BROKER_MISS_BEAT_S): one on a walk that holds no pass lock
    (IBKR, Saxo) and for the first miss of a run; else the beats since the
    account's last counted pass (a miss, or a deferral: _note_deferred_
    beat), floor(elapsed / beat), between one and BROKER_MISS_MAX_BEATS.
    The instant is kept beside the count, and cleared with it
    (_clear_broker_miss). Never raises: unread, one."""
    beat = BROKER_MISS_BEAT_S.get(str(kind or ""))
    if not beat:
        return 1
    try:
        import math

        from django.utils import timezone
        now = timezone.now().timestamp()
        at_key = f"broker_sync:miss_at:{kind}:{pk}"
        last = cache.get(at_key)
        cache.set(at_key, now, 24 * 3600)
        if last is None:
            return 1
        n = int(math.floor((now - float(last)) / float(beat)))
        return max(1, min(BROKER_MISS_MAX_BEATS, n))
    except Exception:  # noqa: BLE001 — a count is never worth a failed sync
        return 1


def _note_deferred_beat(acct) -> None:
    """A pass the request budget deferred is NEVER a miss (2026-11-01): in
    a run of misses its beat must not be counted by the next one
    (_beats_missed), so the run's instant moves to it (2026-11-13). Outside
    a run nothing is written. Never raises."""
    kind = _broker_kind(acct)
    if not BROKER_MISS_BEAT_S.get(kind):
        return
    try:
        from django.core.cache import cache
        from django.utils import timezone
        at_key = f"broker_sync:miss_at:{kind}:{acct.pk}"
        if cache.get(at_key) is not None:
            cache.set(at_key, timezone.now().timestamp(), 24 * 3600)
    except Exception:  # noqa: BLE001 — the next miss counts one more beat
        pass


def _note_broker_miss(acct, user, *, cells_only=False,
                      holdings_answered=False) -> None:
    """Count one missed sync of `acct`, log it, and on the third running
    (the fifteenth on the eToro walk's 60 s beat, 2026-11-06: fifteen
    minutes, as three passes were at 300 s; the thirtieth BEAT on its 30 s
    since 2026-11-13, a miss counting the beats its pass stood for,
    _beats_missed) send the stall alert.

    `cells_only` (eToro, 2026-10-31, review): the account answered this
    pass but its cash and used margin did not. It counts as a miss like
    any other, and is said as what it is: the log line and the alert name
    the cells and their age, and send nobody to re-save keys that just
    answered. A run with one pass that answered nothing at all keeps the
    unreachable alert, keys and all."""
    from django.core.cache import cache

    from .notifications import (notify_broker_cells_unanswered,
                                notify_broker_unreachable)

    key = f"broker_sync:miss:{_broker_kind(acct)}:{acct.pk}"
    beats = _beats_missed(cache, _broker_kind(acct), acct.pk)
    misses = int(cache.get(key) or 0) + beats
    cache.set(key, misses, 24 * 3600)
    # a miss that stands for several beats says so (2026-11-13)
    held = ("" if beats <= 1 else
            f" (counted as {beats} beats of "
            f"{BROKER_MISS_BEAT_S.get(_broker_kind(acct), 0)} s: the beats "
            f"since the last miss ran no pass of their own)")
    # whether a pass of this run answered nothing at all
    silent_key = f"broker_sync:miss_silent:{_broker_kind(acct)}:{acct.pk}"
    if not cells_only:
        cache.set(silent_key, 1, 24 * 3600)

    # EVERY miss is written down, with its true consecutive number, before
    # any decision about alerting (2026-09-15).
    #
    # This used to be silent, and the silence was the defect. The caller
    # logged from its `except`, but neither read raises: `account_values()`
    # and `broker_portfolio()` both return None from
    # `if not self._connect()` without a word, and "None means UNREADABLE"
    # is their documented contract — a good one, argued for at length in
    # `account_values`. The caller had simply relied on an exception it was
    # never promised.
    #
    # So the case the whole ibkr-doctor exists for, a Gateway that is UP and
    # not logged in, was the one case that produced no log line at all. The
    # live box showed misses = 8 against zero matches in six hours of worker
    # logs, while every equity figure on every page quietly aged.
    #
    # The notification below waits for the third miss and then goes quiet
    # for six hours. The log does neither: a failure an operator can only
    # learn about from an alert they have already been shown is a failure
    # they cannot follow.
    _kind = _broker_kind(acct)
    _WHERE = {
        "ibkr": "Check `dc ps` for (unhealthy) and `./deploy/ibkr-doctor`",
        "saxo": "Check the session on /brokers/ — the refresh token lives "
                "40 minutes and rotates, so a box down longer than that "
                "needs a new sign-in",
        "etoro": "Re-save the keys on /brokers/ — the probe answers ok, "
                 "refused or unverified",
    }
    if cells_only:
        _at = getattr(acct, "last_margin_at", None)
        logger.warning(
            "broker sync: %s [%s] answered no cash / used margin — "
            "consecutive miss %d%s. %s, so the keys answered; the cells "
            "every eToro order is judged on stay at their last reading (%s), "
            "and past an hour every eToro order is refused.",
            acct.label, _kind, misses, held,
            "The holdings answered beside them" if holdings_answered
            else "The aggregate read answered without them",
            _at.isoformat() if _at else "never read")
    else:
        logger.warning(
            "broker sync: %s [%s] (%s) returned no equity AND no holdings — "
            "consecutive miss %d%s. Neither read raised; both answered None, "
            "which is what an unauthenticated session looks like at any of "
            "the three venues. %s",
            acct.label, _kind,
            f"{getattr(acct, 'host', '')}:{getattr(acct, 'port', '')}"
            if _kind == "ibkr"
            else "no socket — a session, a key or a sign-in",
            misses, held, _WHERE.get(_kind, _WHERE["ibkr"]))

    # thirty beats for the eToro walk's 30 s (fifteen of its 60 s from
    # 2026-11-06), three for the others (BROKER_MISS_ALERT_AFTER_BY_KIND)
    if misses < BROKER_MISS_ALERT_AFTER_BY_KIND.get(_kind,
                                                    BROKER_MISS_ALERT_AFTER):
        return
    gate = f"broker_sync:alerted:{_broker_kind(acct)}:{acct.pk}"
    if cache.get(gate):
        return
    try:
        if cells_only and not cache.get(silent_key):
            notify_broker_cells_unanswered(
                user, label=acct.label, misses=misses,
                cells_at=getattr(acct, "last_margin_at", None),
                broker=_kind, holdings_answered=holdings_answered)
        else:
            notify_broker_unreachable(user, label=acct.label,
                                      host=getattr(acct, "host", "api"),
                                      port=getattr(acct, "port", 0),
                                      misses=misses, broker=_kind)
        cache.set(gate, 1, BROKER_MISS_ALERT_COOLDOWN)
    except Exception as e:  # noqa: BLE001 — an alert must never fail the sync
        logger.warning("broker sync: stall alert failed for %s: %s",
                       acct.label, e)


def _clear_broker_miss(acct) -> None:
    from django.core.cache import cache

    cache.delete(f"broker_sync:miss:{_broker_kind(acct)}:{acct.pk}")
    cache.delete(f"broker_sync:miss_at:{_broker_kind(acct)}:{acct.pk}")
    cache.delete(f"broker_sync:miss_silent:{_broker_kind(acct)}:{acct.pk}")
    cache.delete(f"broker_sync:alerted:{_broker_kind(acct)}:{acct.pk}")


# ─── The share allocator ─────────────────────────────────────────────────

@shared_task
@guarded_task("pipeline_share_allocator")
def propose_share_plans() -> dict:
    """Every four hours: a SharePlan per broker-backed user, in shadow.

    Runs at :05 so the :00 sync has stored a fresh reading first — a
    proposal needs one under TRACKING_FRESH_SECONDS old, and a stale one
    proposes nothing (counted in `not_proposed`, never invented). Before
    proposing it expires the plans nobody decided on and grades the ones
    whose 24h window has closed, so the housekeeping runs even on a day
    with no reading. Writes a SharePlan row and nothing else: the share
    on a config changes only when an admin applies a plan
    (share_allocator.apply_share_plan), and this task never calls it.

    The return dict carries no top-level `skipped` key and none of the
    gate's work/done counters (parsed, attempted, stored, ...): task_gate
    .judge_result reads a truthy `skipped` as "not configured" and a
    zero `stored` as "produced nothing", and a user with a stale reading
    is neither — it is the allocator declining, which is the design
    (2026-09-12).
    """
    from .capital_truth import broker_backed
    from .models import IBKRAccount
    # Lazily: share_allocator imports _follow_the_account from this module
    # at apply time, so a top-level import here would close the cycle.
    from .share_allocator import (expire_stale_plans, grade_plans,
                                  propose_share_plan_with_reason)

    expired = expire_stale_plans()
    graded = grade_plans()
    users = proposals = not_proposed = errors = 0
    last_error = ""
    # Every user with an INTERFACED BROKER ROW, not just an IBKR one:
    # walking IBKRAccount alone meant the allocator was silently dead for
    # a Saxo or an eToro book. broker_backed() is still the real gate.
    for user in _users_with_a_broker_row():
        if broker_backed(user) is None:
            continue
        users += 1
        try:
            plan, reason = propose_share_plan_with_reason(user)
        except Exception as e:  # noqa: BLE001 — one user's failure must not
            # silence the next user's plan, but it must not pass as ok either
            errors += 1
            last_error = f"{user.username}: {e}"
            logger.exception("[shares] user %s: proposal failed: %s",
                             user.username, e)
            continue
        if plan is None:
            not_proposed += 1
        else:
            proposals += 1
    out = {"status": "ok", "users": users, "proposals": proposals,
           "graded": graded, "expired": expired, "not_proposed": not_proposed}
    if errors:
        out.update({"status": "error", "errors": errors,
                    "error": f"{errors} proposal(s) raised — last: {last_error}"})
    return out


@shared_task
@guarded_task("pipeline_capital_desk")
def grade_capital_desk() -> dict:
    """Nightly: price what the capital desk refused, then score its plans.

    Two passes, in this order and never the other way round. The resolver
    walks every decision whose horizon has closed — a taken entry against
    its own trade, a displaced one against the bars it never got to trade —
    and only then does the grader subtract the two sets, because a plan
    graded before its rows are priced would book the missing ones as
    ungradeable forever.

    THIS IS THE NUMBER THE LIVE SWITCH WAITS ON. `capital_desk_mode_live`
    turns the plan into orders; the bar for flipping it is weeks of positive
    edge_r in shadow, the same bar the share allocator had to clear. Until
    then this task is the only thing measuring whether the ranking is worth
    obeying (2026-09-12).

    The return dict carries `resolved` and `graded` and none of the gate's
    work/done counters: a night on which nothing had closed is the desk
    being patient, not a task that handled rows and stored none.
    """
    from . import capital_desk

    resolved = capital_desk.resolve_counterfactuals()
    graded = capital_desk.grade_plans()
    return {"status": "ok", "resolved": resolved, "graded": graded}


# ─── 2026-09-15: the watchdog for a paper campaign ──────────────────────────

#: IT SPEAKS WHEN SOMETHING CHANGES, NOT BECAUSE A DAY PASSED (2026-11-12).
#: The cooldown used to be a cache key that lived 24 hours, on a schedule of
#: 24 hours. The next morning's check landed a moment before the key expired
#: or a moment after, so a fault that stood came back every one to two days,
#: for ever, under a comment that promised "one notification per cold spell".
#:
#: The memory is now WHAT was said and the day it was said, with no expiry.
#: The same set of faults stays quiet; a different set speaks at once; a
#: fault that still stands is recalled once after this long. The set is read
#: off the findings' KEYS, never off their sentences
#: (campaign_readiness.Finding): three sentences carry a number that moves
#: every morning, and a memory of sentences would call a stale bar a new
#: fault each day it grew a day older. Cleared the moment the chain is
#: complete, so a NEW cold spell speaks immediately.
#:
#: Counted in calendar days (UTC), not in seconds: the run of the seventh
#: morning starts a few seconds before or after the 168th hour, by however
#: long the sends took, which is exactly how the old key missed.
CHAIN_REMIND_AFTER = timedelta(days=7)

#: AN ALARM THE PHONE REFUSED IS TRIED AGAIN THE NEXT MORNING. The bell row
#: is written whatever Telegram answers and the notifier answers True for
#: it, so an alarm Telegram refused was remembered as said: the phone then
#: stayed silent for the week of the reminder, where the 24-hour key let
#: the next run through. Such a memory carries "heard": False and holds for
#: this long only. Telegram not ASKED (quiet hours, no token, no chat id,
#: another channel) is not a refusal: the bell row is the message, as
#: before.
CHAIN_RETRY_AFTER = timedelta(days=1)

#: Where the alarm's memory lives: {"fp": fingerprint, "day": ISO date},
#: with "heard": False when no phone took it (CHAIN_RETRY_AFTER) and
#: "feeds": {symbol: its newest bar} when every fault said was a stopped
#: bar feed (_waits_for_the_open).
CHAIN_SAID_KEY = "campaign_watch:said"

#: The 24-hour key of before 2026-11-12. Redis keeps its keys across a
#: deploy, so every run deletes it: nothing reads it any more.
CHAIN_OLD_KEY = "campaign_watch:alerted"


def _chain_fingerprint(findings) -> str:
    """The SET of faults as one word: a hash of the findings' keys, sorted.

    Never of their sentences. A finding with no key (the tests refuse one)
    counts as one fixed key: it can then hide a change, and it cannot bring
    back a daily alarm.
    """
    import hashlib
    keys = sorted(repr(tuple(getattr(f, "key", None) or ("unkeyed",)))
                  for f in findings)
    return hashlib.sha1("|".join(keys).encode("utf-8")).hexdigest()[:12]


def _chain_already_said(said, fingerprint: str, today) -> bool:
    """True while this same set of faults was said less than
    CHAIN_REMIND_AFTER ago, or less than CHAIN_RETRY_AFTER ago when no
    phone took it. A memory that cannot be read (another shape, a day in
    the future) was not said."""
    if not isinstance(said, dict) or said.get("fp") != fingerprint:
        return False
    try:
        day = date.fromisoformat(str(said.get("day") or ""))
    except ValueError:
        return False
    wait = (CHAIN_RETRY_AFTER if said.get("heard") is False
            else CHAIN_REMIND_AFTER)
    return timedelta(0) <= (today - day) < wait


def _stopped_feeds(findings, report) -> dict:
    """{symbol: its newest 4h bar} when EVERY finding is a stopped bar
    feed, {} otherwise: what _waits_for_the_open compares on a morning
    with no fault."""
    bars = report.get("bar_state") or {}
    feeds: dict = {}
    for finding in findings:
        key = getattr(finding, "key", None)
        if not (isinstance(key, tuple) and len(key) == 3
                and key[0] == "bars_stopped"):
            return {}
        for symbol in key[2]:
            feeds[str(symbol)] = str(
                (bars.get(symbol) or {}).get("newest") or "")
    return feeds


def _waits_for_the_open(said, report) -> bool:
    """A morning with no fault that proves no repair: keep the memory.

    A feed that died on Thursday is alarmed on Friday. On Saturday its
    market is shut and its bar is "correct for a shut market"
    (preflight_live._bar_verdict, shut_stale): no fault that morning. The
    memory was cleared, and Monday alarmed the same dead feed again, three
    days into the week the reminder waits. Nothing was repaired; it could
    not be judged before the open.

    True only when the alarm said named stopped feeds and nothing else,
    and each of them, this morning, sits in a shut market with the SAME
    newest bar the alarm saw. A bar written since is a repair (forgotten,
    so the feed dying again speaks at once), and so is a link put back ON.
    It cannot hold for long: past the grace of a shut market the verdict is
    a fault again (shut_dead), under the same key.
    """
    feeds = said.get("feeds") if isinstance(said, dict) else None
    if not isinstance(feeds, dict) or not feeds:
        return False
    bars = report.get("bar_state") or {}
    for symbol, newest in feeds.items():
        state = bars.get(symbol) or {}
        if (not newest or state.get("verdict") != "shut_stale"
                or state.get("newest") != newest):
            return False
    return True


def _live_notice_fingerprint(armed) -> str:
    """The "live by decision" notice is said once per SET of armed
    live-action switches: this names the set."""
    import hashlib
    word = "live_by_decision|" + ",".join(sorted(str(k) for k in armed))
    return hashlib.sha1(word.encode("utf-8")).hexdigest()[:12]


def _say_live_by_decision(report, recipients) -> int:
    """Tell each staff account, once, that the paper checks stand down
    because a bot is armed for real money. Returns how many were told now.

    For a live operation only, and only when there is something to say: a
    live-action switch is ON, or no paper bot is on. Said once per set of
    armed switches. THE BELL TABLE IS THE MEMORY, as notify_staff's is: a
    row that carries the fingerprint means that account was told, so an
    emptied cache cannot repeat it, and a staff account that arrives later
    is told once. A muted bot feed gets no row and no message, as for the
    alarm.
    """
    if report.get("campaign") != "live":
        return 0
    fleet = report.get("fleet") or {}
    armed = list(report.get("armed") or [])
    if not armed and fleet.get("paper_bots"):
        return 0
    fingerprint = _live_notice_fingerprint(armed)
    from alerts.models import Notification

    from .notifications import notify_live_by_decision
    told = 0
    for user in recipients:
        try:
            if Notification.objects.filter(
                    user=user, data__fingerprint=fingerprint).exists():
                continue
            if notify_live_by_decision(
                    user, armed=armed,
                    live_configs=int(fleet.get("live_bots") or 0),
                    demo_configs=int(fleet.get("demo_bots") or 0),
                    hand_lanes=int(fleet.get("hand_lanes") or 0),
                    paper_configs=int(fleet.get("paper_bots") or 0),
                    paper_lanes=int(fleet.get("paper_lanes") or 0),
                    fingerprint=fingerprint):
                told += 1
        except Exception as e:  # noqa: BLE001 — a notice never stops the watch
            logger.warning("[campaign watch] live-by-decision notice failed "
                           "for %s: %s", user.id, e)
    return told


@shared_task
@guarded_task("pipeline_campaign_watch")
def watch_evidence_chain():
    """Is the paper-campaign evidence chain still complete? Say so if not.

    `paper_readiness` answers the question the moment an operator asks it.
    This asks on their behalf, daily, because the failure mode is silence:
    a campaign that starts green and goes cold on day twelve spends
    seventy-eight days producing nothing, and `guarded_task` no-ops without
    raising on a component that is off or has no row.

    The cost of a cold link is zero today and the whole campaign in ninety
    days, which is exactly the shape of failure this platform keeps finding
    — the funding feed that wrote nothing, the broker sync that missed eight
    times in silence, the backtester that priced an absent bar at zero.

    A DECISION IS SAID ONCE, A FAULT IS ALARMED (2026-11-12). The operator
    trades real money by decision, and this alarmed on it every one to two
    days: "The evidence chain is broken", with every link ON. It now alarms
    on `blockers` as readiness() defines them: for a live operation the
    chain's own faults (a link OFF or with NO ROW, an unticked beat entry,
    closed signals with no result, bars missing or stale, no symbol) and a
    rule stuck at the paper stage with no paper bot. That a live-action
    switch is ON, or that no paper bot is on, is said once as a notice
    (_say_live_by_decision). A paper campaign keeps every check.

    THE MASTER SWITCH IS NOT ITS TO ALARM ON. With platform_master off the
    guard above skips this task like every other, before it reads
    anything. readiness() lists that switch for `paper_readiness`, which
    an operator runs by hand; the pause itself is the alarm bot's line
    (bot_program/alarm, "Automation paused"). So the notice does not
    promise to watch it.

    READ-ONLY. It measures and it notifies; it turns nothing on. A watchdog
    that repaired the chain would be a watchdog nobody could trust to report
    it honestly, and switching a pipeline back on is an operator's decision.
    """
    from django.contrib.auth.models import User
    from django.core.cache import cache
    from django.utils import timezone

    from .campaign_readiness import readiness

    today = timezone.now().date()
    report = readiness()
    cold = report["cold_links"]
    blockers = report["blockers"]
    out = {"status": "ok", "cold_links": cold,
           "blockers": len(blockers), "notified": 0,
           "campaign": report["campaign"], "noticed": 0}
    cache.delete(CHAIN_OLD_KEY)

    recipients = list(User.objects.filter(is_staff=True, is_active=True))
    try:
        out["noticed"] = _say_live_by_decision(report, recipients)
    except Exception as e:  # noqa: BLE001 — a notice never stops the alarm
        logger.warning("[campaign watch] live-by-decision notice failed: %s",
                       e)

    if not blockers:
        # A complete chain clears the memory, so the next cold spell is
        # heard at once rather than taken for the last one. Unless nothing
        # was repaired: a stopped feed whose market is shut this morning.
        if _waits_for_the_open(cache.get(CHAIN_SAID_KEY), report):
            logger.info("[campaign watch] no fault this morning, and the "
                        "feed that was alarmed sits in a shut market with "
                        "the same last bar: its alarm is not forgotten")
        else:
            cache.delete(CHAIN_SAID_KEY)
        return out

    fingerprint = _chain_fingerprint(blockers)
    if _chain_already_said(cache.get(CHAIN_SAID_KEY), fingerprint, today):
        # "cooldown" is the word the result has always carried for a run
        # that found a fault and kept quiet about it.
        out["status"] = "cooldown"
        return out

    if not recipients:
        # Not an error and not a success: the check ran, the chain is cold,
        # and there is nobody configured to tell. Said plainly rather than
        # returned as a clean dict.
        logger.warning(
            "[campaign watch] chain is cold (%s) and no active staff user "
            "exists to notify", ", ".join(cold) or "blockers with no key")
        out["status"] = "nobody_to_tell"
        return out

    # The chain's own faults first, whatever order the checks ran in: the
    # message shows the first finding and counts the rest, and its title is
    # the first finding's. A dead feed must not sit behind a switch.
    chain = {id(f) for f in report["chain_faults"]}
    ordered = ([f for f in blockers if id(f) in chain]
               + [f for f in blockers if id(f) not in chain])

    from .notifications import notify_evidence_chain_cold
    sent = refused = False      # what Telegram answered, over every account
    for user in recipients:
        receipt: dict = {}
        try:
            if notify_evidence_chain_cold(user, cold=cold, blockers=ordered,
                                          receipt=receipt):
                out["notified"] += 1
        except Exception as e:  # noqa: BLE001 — one failure must not eat the rest
            logger.warning("[campaign watch] notify failed for %s: %s",
                           user.id, e)
        sent = sent or receipt.get("external") == "sent"
        refused = refused or receipt.get("external") == "refused"

    if out["notified"]:
        # Remembered only once somebody was told: an alarm nobody received
        # is tried again at the next run, not held for a week. A bell row
        # with every phone refused is held for a day (CHAIN_RETRY_AFTER).
        said = {"fp": fingerprint, "day": today.isoformat()}
        if refused and not sent:
            said["heard"] = False
        feeds = _stopped_feeds(blockers, report)
        if feeds:
            said["feeds"] = feeds
        cache.set(CHAIN_SAID_KEY, said, None)
    logger.warning(
        "[campaign watch] evidence chain is cold: %s — %d blocker(s), "
        "%d operator(s) told", ", ".join(cold) or "see blockers",
        len(blockers), out["notified"])
    return out


# ── The Morgul guards (2026-09-26) ───────────────────────────────────────
# Ten read-only guards over the book (bot_program/morgul.py). Their one
# write besides the group's messages is the brake, behind its own switch.

@shared_task
@guarded_task("morgul_guards")
def run_morgul_guards() -> dict:
    """Every 5 min on the fast queue: run every guard, tell the group.

    Gated by the morgul_guards component, OFF on arrival. Reads the
    database and the cache: no broker call, no order, no close. The brake
    (enabled = False on the offending configs, through the Eye's own
    apply_brake) acts only while the morgul_brake component is ON.

    Then the alarm bot hears the run (2026-09-28, bot_program/alarm.py):
    its critical findings, a critical guard that could not run and the
    brake having acted, to the alarm chat, on the alarm bot's own switch
    and memory. Fenced: nothing there changes what Morgul did or returns.
    """
    from .morgul import cycle
    report = cycle(send=True)
    try:
        from .alarm import relay_morgul
        relay_morgul(report)
    except Exception as e:  # noqa: BLE001 — the relay never breaks Morgul
        logger.warning("[telegram alarm] the Morgul run was not relayed "
                       "(%s)", type(e).__name__, exc_info=True)
    return report.result


# ── The demo short proofs (2026-10-31) ───────────────────────────────────
# The platform proves each unproven class's short itself, on eToro's DEMO
# account only (bot_program/short_proofs.py), one step a run.

@shared_task
@guarded_task("short_proofs_demo")
def run_short_proofs_demo() -> dict:
    """Every 15 min on the slow queue: ONE step of the demo short proofs —
    close a demo position the runner holds, or prove the next class whose
    short no code pins (a SELL of the venue minimum, filled, closed and
    recorded) while its market is open and the live lane leaves eToro's
    quota free. Gated by short_proofs_demo, ON by default (it only ever
    touches the demo account). A step in doubt answers "error": the
    runner stays stopped until a superuser clears it on /short-proofs/."""
    from .short_proofs import run_once
    return run_once()


# ── The Telegram eye (2026-09-26) ────────────────────────────────────────
# The group "Sauron Vision" asks, Sauron answers: in English, to the
# configured chat only, and its one write is the brake (bots OFF, never
# on). The whole of it is bot_program/telegram_eye.py; these are its two
# Celery doors.

@shared_task
@guarded_task("telegram_eye")
def poll_telegram_eye() -> dict:
    """Every 15 s on the fast queue: read the group, answer, confirm.

    Gated by the telegram_eye component, OFF on arrival. One poll at a
    time handles a batch: telegram_eye.poll takes a Postgres advisory
    lock without waiting, and a second worker skips at once (not the
    component row, which the gate's mark_run writes after every run).
    """
    from .telegram_eye import poll
    return poll()


@shared_task
def answer_telegram_question(pending_id: int) -> dict:
    """One question from the group, answered on the ai queue.

    Not gated, like brain.tasks.answer_research_question: the poll that
    queued it was, and a skip here would leave the research row PENDING
    for ever. The ai queue because one LLM turn takes tens of seconds and
    the fast queue carries the quote poller.
    """
    from .telegram_eye import answer_question
    return answer_question(pending_id)


# ── The alarm bot (2026-09-28) ───────────────────────────────────────────
# A second Telegram bot in a second group, the operator and the keeper:
# critical problems only, never an all-clear, and two commands, /status
# and /stopall. The whole of it is bot_program/alarm.py; these are its
# two Celery doors, both gated by the alarm bot's OWN switch (alarm_task:
# telegram_alarm, OFF on arrival) and never by the master switch, whose
# pause is one of the things it reports. The flatten's announcement is
# not a task: the two kill-switch views send it themselves on the commit
# (alarm.after_kill_switch), never behind a worker that may be down.

@shared_task
@alarm_task
def poll_telegram_alarm() -> dict:
    """Every 15 s on the fast queue: read the alarm chat, answer /status
    and /stopall, confirm after the commit.

    One poll at a time: alarm.poll takes an advisory lock of its own
    without waiting (not the Eye's: a /stopall must never wait behind the
    Eye's batch). A poll that read nothing is idle, and the row keeps the
    sentinel's last verdict.
    """
    from .alarm import poll
    return poll()


@shared_task
@alarm_task
def run_alarm_sentinel() -> dict:
    """Every 10 min: read what is critically wrong (the pause, abandoned
    closes, safety-critical components and feeds, live broker accounts
    that stopped answering) and tell the alarm chat what is due.

    One pass at a time (a cache lock): a backlog never sends twice. A
    pass whose alarm Telegram refused is an error on the row.
    """
    from .alarm import sentinel
    return sentinel()


# ── ARAGORN AND THE CRISIS MODE (2026-10-02) ───────────────────────────

@shared_task
@guarded_task("crisis_mode")
def read_market_stress() -> dict:
    """Every 15 min: score the market's stress and step the posture
    (bot_program/market_stress.py). An escalation tells the alarm chat."""
    from .market_stress import evaluate
    r = evaluate()
    return {"level": r.level, "score": r.score, "raw": r.raw_level,
            "saved": 1}


@shared_task
@guarded_task("aragorn")
def run_aragorn() -> dict:
    """Every 4 h: Aragorn's pass (bot_program/aragorn.py) — bench the
    losing pairs, graduate or bench the ones on probation, bring proven
    ones back to real money. Every move is journaled."""
    from .aragorn import evaluate
    moves = evaluate(apply=True)
    return {"moves": len(moves),
            "kinds": sorted({m["kind"] for m in moves}),
            "errors": sum(1 for m in moves if m.get("error"))}


@shared_task
@guarded_task("aragorn")
def aragorn_daily_report() -> dict:
    """07:10 UTC: Aragorn's state and its last 24 h, to every staff
    login's channels (posture, pairs, moves, care closes)."""
    from django.contrib.auth import get_user_model

    from .notifications import dispatch_notification
    from .aragorn import report_lines
    lines = report_lines()
    sent = 0
    for user in get_user_model().objects.filter(is_staff=True,
                                                is_active=True):
        try:
            if dispatch_notification(user, "system_health",
                                     title="Aragorn daily report",
                                     body="\n".join(lines)[:3800]):
                sent += 1
        except Exception as e:  # noqa: BLE001 — one login, not the report
            logger.warning("[aragorn] report to %s failed: %s", user, e)
    return {"sent": sent, "lines": len(lines)}
