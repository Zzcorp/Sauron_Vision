import logging

from celery import shared_task
from core.task_gate import guarded_task

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

    from .capital_truth import broker_backed
    from .engine.ibkr_client import is_ibkr_available
    from .engine.ibkr_sessions import acquire_trader
    from .models import IBKRAccount

    out = {"attempted": 0, "stored": 0, "unreachable": 0}
    if not is_ibkr_available():
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
                from datetime import timedelta
                from decimal import Decimal

                from .equity_models import BrokerEquityReading
                BrokerEquityReading.objects.create(
                    broker="ibkr", account_pk=acct.pk,
                    account=acct, value=Decimal(str(round(float(value), 2))),
                    currency=currency or "", env=acct.env or "", at=now)
                BrokerEquityReading.objects.filter(
                    broker="ibkr", account_pk=acct.pk,
                    account=acct,
                    at__lt=now - timedelta(days=EQUITY_HISTORY_DAYS)
                ).delete()
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
    return out


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
    the others already claim.
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
        for cfg in followers:
            share = float(alloc["plan"].get(cfg.pk, 0.0))
            new = Decimal(str(round(float(value) * share, 2)))
            if cfg.capital == new:
                continue
            old = cfg.capital
            cfg.capital = new
            cfg.save(update_fields=["capital"])
            logger.info("broker sync: %s pool follows the account at "
                        "%.1f%%: %s -> %s %s", cfg.name, share * 100.0,
                        old, new, currency or "")
    except Exception as e:  # noqa: BLE001 — the stored reading must stand
        logger.warning("broker sync: pool-follow failed: %s", e)


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


@shared_task
@guarded_task("broker_account_sync")
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
    """
    from django.utils import timezone

    from .engine.etoro_client import EtoroTrader
    from .models import EtoroAccount

    out = {"attempted": 0, "stored": 0, "unreachable": 0}
    for acct in EtoroAccount.objects.exclude(api_key_enc=""):
        user = acct.user
        k, u = acct.get_credentials()
        if not (k and u):
            continue
        out["attempted"] += 1
        reading, rows = None, None
        try:
            client = EtoroTrader(k, u, env="demo" if acct.demo else "live")
            reading = client.net_liquidation()
            rows = client.broker_portfolio()
        except Exception as e:  # noqa: BLE001 — one account must not stop the rest
            logger.warning("broker sync: %s (etoro) unreadable: %s",
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
            fields += ["last_equity", "last_equity_currency",
                       "last_equity_at"]
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
                    broker="etoro", account_pk=acct.pk, at=now,
                    defaults={"value": value, "currency": currency,
                              "env": "paper" if acct.demo else "live"})
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
                _shock_trigger(user, now)
    return out


def _note_broker_miss(acct, user) -> None:
    from django.core.cache import cache

    from .notifications import notify_broker_unreachable

    key = f"broker_sync:miss:{_broker_kind(acct)}:{acct.pk}"
    misses = int(cache.get(key) or 0) + 1
    cache.set(key, misses, 24 * 3600)

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
    logger.warning(
        "broker sync: %s (%s:%s) returned no equity AND no holdings — "
        "consecutive miss %d. Neither read raised; both answered None, "
        "which is what an unauthenticated Gateway looks like. Check "
        "`dc ps` for (unhealthy) and `./deploy/ibkr-doctor`",
        acct.label, getattr(acct, "host", "api"),
        getattr(acct, "port", ""), misses)

    if misses < BROKER_MISS_ALERT_AFTER:
        return
    gate = f"broker_sync:alerted:{_broker_kind(acct)}:{acct.pk}"
    if cache.get(gate):
        return
    try:
        notify_broker_unreachable(user, label=acct.label,
                                  host=getattr(acct, "host", "api"),
                                  port=getattr(acct, "port", 0),
                                  misses=misses)
        cache.set(gate, 1, BROKER_MISS_ALERT_COOLDOWN)
    except Exception as e:  # noqa: BLE001 — an alert must never fail the sync
        logger.warning("broker sync: stall alert failed for %s: %s",
                       acct.label, e)


def _clear_broker_miss(acct) -> None:
    from django.core.cache import cache

    cache.delete(f"broker_sync:miss:{_broker_kind(acct)}:{acct.pk}")
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

#: One notification per cold spell, not one per day. A chain that stays cold
#: for a week is one problem, and seven identical alerts is how an operator
#: learns to ignore the eighth. Cleared the moment the chain is complete, so
#: a NEW cold spell speaks immediately.
CHAIN_COLD_ALERT_COOLDOWN = 24 * 3600


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

    READ-ONLY. It measures and it notifies; it turns nothing on. A watchdog
    that repaired the chain would be a watchdog nobody could trust to report
    it honestly, and switching a pipeline back on is an operator's decision.
    """
    from django.contrib.auth.models import User
    from django.core.cache import cache

    from .campaign_readiness import readiness

    report = readiness()
    cold = report["cold_links"]
    blockers = report["blockers"]
    out = {"status": "ok", "cold_links": cold,
           "blockers": len(blockers), "notified": 0}

    if not blockers:
        # A complete chain clears the gate, so the next cold spell is heard
        # at once rather than swallowed by a cooldown from the last one.
        cache.delete("campaign_watch:alerted")
        return out

    if cache.get("campaign_watch:alerted"):
        out["status"] = "cooldown"
        return out

    recipients = list(User.objects.filter(is_staff=True, is_active=True))
    if not recipients:
        # Not an error and not a success: the check ran, the chain is cold,
        # and there is nobody configured to tell. Said plainly rather than
        # returned as a clean dict.
        logger.warning(
            "[campaign watch] chain is cold (%s) and no active staff user "
            "exists to notify", ", ".join(cold) or "blockers with no key")
        out["status"] = "nobody_to_tell"
        return out

    from .notifications import notify_evidence_chain_cold
    for user in recipients:
        try:
            if notify_evidence_chain_cold(user, cold=cold, blockers=blockers):
                out["notified"] += 1
        except Exception as e:  # noqa: BLE001 — one failure must not eat the rest
            logger.warning("[campaign watch] notify failed for %s: %s",
                           user.id, e)

    if out["notified"]:
        cache.set("campaign_watch:alerted", 1, CHAIN_COLD_ALERT_COOLDOWN)
    logger.warning(
        "[campaign watch] evidence chain is cold: %s — %d blocker(s), "
        "%d operator(s) told", ", ".join(cold) or "see blockers",
        len(blockers), out["notified"])
    return out
