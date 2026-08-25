"""Emergency kill switch — disable every bot and flatten all open positions.

This is the operational "stop everything now" path. Its first and most important
job is to DISABLE every bot config (legacy crypto *and* multi-asset) so no new
entries can open. It then makes a best-effort attempt to close open trades at the
broker. Broker-close failures never abort the sweep — they are recorded in
``errors`` so the operator knows which symbols may still be open at the broker and
must be reconciled/closed manually.

Covers both execution stacks:
  - legacy crypto  : ``BotConfig`` / ``BotTrade``        (routed via ``_client_for``)
  - multi-asset    : ``AssetBotConfig`` / ``AssetBotTrade`` (routed via ``client_for_symbol``)
"""
import logging
from decimal import Decimal

from django.utils import timezone

logger = logging.getLogger(__name__)


def _push_close_event(user, trade, kind):
    """A kill-switch close is still a close — the dashboards must hear
    it the same way they hear the engine's own. Guarded like every
    other hook in this sweep: one deaf channel never aborts a flatten.
    """
    try:
        from dashboard.consumers import push_eye_event
        payload = {"source": "kill_switch"}
        if trade is not None:
            payload.update({
                "trade_id": trade.id,
                "asset_class": getattr(trade, "asset_class", "crypto"),
                "symbol": trade.symbol,
            })
        push_eye_event(user, kind, payload)
    except Exception as e:  # noqa: BLE001
        logger.warning("[KILL SWITCH] eye push failed: %s", e)


def execute_kill_switch(user=None, reason="manual"):
    """Emergency: disable all bots and close all open positions.

    Args:
        user: if given, scope the sweep to this user; otherwise platform-wide.
        reason: free-text reason recorded in the notification + logs.

    Returns a results dict summarising what was disabled/closed and any errors.
    """
    from bot_program.models import BotConfig, BotTrade, AssetBotConfig, AssetBotTrade
    from portfolio.models import Position

    results = {
        "bots_disabled": 0,
        "asset_bots_disabled": 0,
        "positions_closed": 0,
        "asset_positions_closed": 0,
        "portfolio_positions_closed": 0,
        "errors": [],
    }
    now = timezone.now()

    # ── 1. Disable every bot config first (stops new entries) ────────────────
    legacy_configs = BotConfig.objects.filter(enabled=True)
    if user:
        legacy_configs = legacy_configs.filter(user=user)
    for config in legacy_configs:
        config.enabled = False
        config.save(update_fields=["enabled"])
        results["bots_disabled"] += 1
        logger.warning("[KILL SWITCH] Disabled BotConfig %s (user=%s)", config.id, config.user)

    asset_configs = AssetBotConfig.objects.filter(enabled=True)
    if user:
        asset_configs = asset_configs.filter(user=user)
    for config in asset_configs:
        config.enabled = False
        config.save(update_fields=["enabled", "updated_at"])
        results["asset_bots_disabled"] += 1
        logger.warning(
            "[KILL SWITCH] Disabled AssetBotConfig %s (%s, user=%s)",
            config.id, config.asset_class, config.user,
        )

    # ── 2. Close open legacy (crypto) trades ─────────────────────────────────
    open_legacy = BotTrade.objects.filter(status="OPEN")
    if user:
        open_legacy = open_legacy.filter(config__user=user)
    for trade in open_legacy:
        try:
            _close_legacy_trade(trade, now)
            results["positions_closed"] += 1
            _push_close_event(trade.config.user, trade, "fill_close")
        except Exception as e:  # noqa: BLE001 — never let one trade abort the sweep
            msg = f"legacy trade {trade.id} ({trade.symbol}): {e}"
            results["errors"].append(msg)
            logger.error("[KILL SWITCH] %s", msg)

    # ── 3. Close open multi-asset trades ─────────────────────────────────────
    open_asset = AssetBotTrade.objects.filter(status__in=("OPEN", "CLOSE_PENDING"))
    if user:
        open_asset = open_asset.filter(config__user=user)
    for trade in open_asset:
        try:
            _close_asset_trade(trade, now)
            results["asset_positions_closed"] += 1
            _push_close_event(trade.config.user, trade, "fill_close")
        except Exception as e:  # noqa: BLE001
            msg = f"asset trade {trade.id} ({trade.symbol}): {e}"
            results["errors"].append(msg)
            logger.error("[KILL SWITCH] %s", msg)
            # The partial-fill branch SAVES CLOSE_PENDING and then
            # raises — the one close state this sweep can strand is the
            # one the success path could never announce. Refresh from
            # the DB (the in-memory row predates the save) and tell the
            # pages a close is in trouble.
            try:
                trade.refresh_from_db(fields=["status"])
                if trade.status == "CLOSE_PENDING":
                    _push_close_event(trade.config.user, trade,
                                      "close_pending")
            except Exception:  # noqa: BLE001
                pass

    # ── 4. Mark portfolio positions closed ───────────────────────────────────
    positions = Position.objects.filter(closed_at__isnull=True)
    if user:
        from portfolio.services import get_or_create_default_portfolio
        portfolio = get_or_create_default_portfolio(user=user)
        positions = positions.filter(portfolio=portfolio)
    for pos in positions:
        pos.closed_at = now
        pos.save(update_fields=["closed_at"])
        results["portfolio_positions_closed"] += 1
    if results["portfolio_positions_closed"] and user is not None:
        # Position rows carry no user FK; the initiating operator is the
        # one watching. A global sweep (user=None) has no address — those
        # pages converge on the slow sweep instead.
        _push_close_event(user, None, "fill_close")

    # ── 5. Notify ────────────────────────────────────────────────────────────
    from alerts.models import Notification
    title = f"KILL SWITCH ACTIVATED — {reason}"
    body = (
        f"Disabled {results['bots_disabled']} crypto + "
        f"{results['asset_bots_disabled']} asset bots. "
        f"Closed {results['positions_closed']} crypto + "
        f"{results['asset_positions_closed']} asset positions."
    )
    if results["errors"]:
        body += (
            f" ▲ {len(results['errors'])} broker-close error(s) — these symbols "
            f"may still be OPEN at the broker and need manual reconciliation."
        )
    try:
        if user:
            Notification.create_for_user(user, "system", title, body)
        else:
            Notification.create_for_all("system", title, body)
    except Exception as e:  # noqa: BLE001 — notification must never block the kill
        logger.error("[KILL SWITCH] notification failed: %s", e)

    logger.critical("[KILL SWITCH] Executed: %s", results)
    return results


def _market_exit_price(symbol, fallback, client=None):
    """Best-effort current price for `symbol`; fall back to the trade entry.

    The broker's own tick is asked first — its print is the book the forced
    close will actually fill on (and for paper trades the router hands back
    PaperTrader, whose ticker already enforces quote freshness with a bar
    fallback). The direct LiveQuote read rejects stale rows: the kill switch
    runs precisely when things are broken, which is when a dead poller's
    fossil is most likely to be sitting in the table — booking a forced
    close at a price from an hour ago fabricates P&L.
    """
    from bot_program.engine.paper_trader import PaperTrader

    if client is not None and hasattr(client, "ticker"):
        try:
            last = float((client.ticker(symbol) or {}).get("lastPrice", 0) or 0)
            if last > 0:
                return last
        except Exception as e:  # noqa: BLE001
            logger.warning("[KILL SWITCH] ticker(%s) failed, falling back "
                           "to LiveQuote: %s", symbol, e)

    try:
        from django.utils import timezone as tz
        from market_data.models import LiveQuote
        quote = LiveQuote.objects.filter(instrument__symbol=symbol).first()
        if quote and quote.last:
            age = (tz.now() - quote.updated_at).total_seconds()
            if age <= PaperTrader.MAX_QUOTE_AGE_SECONDS:
                return float(quote.last)
    except Exception:  # noqa: BLE001
        pass
    return float(fallback)


def _try_broker_close(client, symbol, side, qty):
    """Submit a closing market order if the client supports it. Best-effort:
    raises on broker error so the caller can record it.

    Returns the broker's response — or None when the client has no
    ``market_order`` at all — so the caller can book the exit at the fill the
    broker reports rather than at the mark it read a moment earlier. A forced
    flatten is the exit most likely to slip: it fires because something is
    already wrong.
    """
    if not hasattr(client, "market_order"):
        return None
    close_side = "SELL" if side == "BUY" else "BUY"
    return client.market_order(symbol, close_side, float(qty))


def _close_legacy_trade(trade, now):
    """Close one legacy crypto BotTrade and persist the close on the real schema."""
    from bot_program.engine.runner import _client_for
    from bot_program.pending_closes import is_paper_client

    # Route to the correct broker (or PaperTrader) BEFORE marking the exit,
    # so the booked price can come from the venue's own tick. The legacy
    # selector takes (user, cfg) — passing the config as the user arg was
    # the original bug.
    result = None
    try:
        client = _client_for(trade.config.user, trade.config)
        if not trade.paper and is_paper_client(client):
            # A LIVE row routed to the simulator: the broker is unreachable,
            # so nothing here can flatten it. Refusing is the honest answer —
            # the sweep's `errors` channel is precisely "these may still be
            # OPEN at the broker" — where submitting would book a simulated
            # fill on a real position and mark the row CLOSED over it.
            raise RuntimeError(
                "broker unavailable (PaperTrader fallback) — no close was "
                "sent and the position is still open at the broker")
        exit_price = _market_exit_price(trade.symbol, trade.entry_price,
                                        client=client)
        result = _try_broker_close(client, trade.symbol, trade.side, trade.qty)
    except Exception as e:  # noqa: BLE001
        logger.warning("[KILL SWITCH] broker close failed for %s: %s", trade.symbol, e)
        raise

    # Prefer the fill the broker reports over the mark read a moment earlier
    # — the same rule the AssetBotTrade paths use. BotTrade has no metadata
    # column to stamp the source on, so it goes in `reason`, the only place
    # this schema can carry "was this exit measured or assumed".
    #
    # Live only. This path submits to PaperTrader for a paper row too, and
    # PaperTrader's response is a simulation, not a fill — booking it would
    # change what the paper book records for a flatten it already models by
    # marking. Only the LIVE path becomes honest here.
    from bot_program.pending_closes import (
        broker_exit_price, broker_filled_qty, dust_qty,
    )
    if trade.paper:
        result = None
    booked = broker_exit_price(result)
    if booked is not None and booked > 0:
        exit_price = float(booked)
        note = "exit:broker"
    else:
        note = "exit:mark"
    trade.reason = ((trade.reason or "") + f" | {note}").strip()

    # A partial fill has nowhere to live on this schema: BotTrade has no
    # CLOSE_PENDING state and no residual field. Booking CLOSED anyway would
    # hide a live remainder, so the row stays OPEN and the sweep's error
    # channel names the symbol — which is exactly what that channel is for.
    filled = broker_filled_qty(result)
    qty = Decimal(str(trade.qty))
    # BotTrade is the legacy CRYPTO schema — there is no asset_class column
    # because every row on it is crypto, so the crypto dust line is the one
    # that applies.
    if filled is not None and (qty - filled) > dust_qty("crypto"):
        trade.save(update_fields=["reason"])
        raise RuntimeError(
            f"broker filled only {filled} of {qty} — the remainder is STILL "
            f"OPEN at the broker and the legacy schema has no CLOSE_PENDING "
            f"state to hold it; close it manually")

    pnl = (exit_price - float(trade.entry_price)) * float(trade.qty)
    if trade.side == "SELL":
        pnl = -pnl

    trade.exit_price = exit_price
    trade.closed_at = now
    trade.status = "CLOSED"
    trade.pnl_usdt = pnl
    trade.save(update_fields=["exit_price", "closed_at", "status", "pnl_usdt",
                              "reason"])


def _close_asset_trade(trade, now):
    """Close one multi-asset AssetBotTrade, routing through the broker_router."""
    from bot_program.engine.broker_router import client_for_symbol

    is_options = trade.asset_class == "options"

    # The client is built before the mark so the exit price can come from
    # the broker's own tick (PaperTrader for paper trades, which enforces
    # quote freshness itself). Construction failing aborts this trade's
    # close exactly as a failed submit does — the caller records the error.
    try:
        client = client_for_symbol(trade.config.user, trade.symbol, trade.config)
    except Exception as e:  # noqa: BLE001
        logger.warning("[KILL SWITCH] broker route failed for %s: %s",
                       trade.symbol, e)
        raise

    # A LIVE row handed the simulator. `broker_router` falls back to
    # PaperTrader whenever credentials are missing or a broker library is not
    # installed, and PaperTrader answers `status: FILLED` at a simulated price
    # in exactly a broker's shape — `resolve_exit_fill` cannot tell them apart
    # and would stamp this exit `broker`, the one provenance flag that exists
    # to catch this. Nothing was sent and nothing can be: refuse, so the
    # symbol lands in the sweep's `errors` channel, which is where the
    # operator reads "may still be OPEN at the broker".
    from bot_program.pending_closes import is_paper_client
    if not trade.paper and is_paper_client(client):
        raise RuntimeError(
            f"live trade {trade.id} ({trade.symbol}) routed to PaperTrader "
            f"(broker unavailable) — no close was sent and the position is "
            f"still open at the broker; close it manually")

    if is_options:
        # Premium-denominated trade: LiveQuote holds the UNDERLYING's price,
        # which is the wrong scale — mark at the option's own premium, falling
        # back to the entry premium.
        from bot_program.asset_engine.options_bot import (
            current_premium_for_trade, submit_option_close,
            option_pnl_multiplier,
        )
        exit_price = float(current_premium_for_trade(trade) or trade.entry_price)
    else:
        exit_price = _market_exit_price(trade.symbol, trade.entry_price,
                                        client=client)

    # The sweep also picks up CLOSE_PENDING rows, and one of those may
    # already have had part of its close filled. Flattening `trade.qty` there
    # would sell units the account no longer holds — a kill switch that opens
    # a fresh reverse position is the worst possible outcome of pressing it.
    from bot_program.pending_closes import dust_qty, residual_qty
    outstanding = residual_qty(trade)

    result = None
    # Set when the close finishes while we are cancelling its predecessor:
    # there is then nothing to send, but there IS something to book.
    already_flat = False
    try:
        # Paper trades have no broker-side position to flatten — same rule
        # as AssetBot._close_trade. Submitting anyway can raise (PaperTrader
        # has no option order path) and strand the row OPEN forever.
        if not trade.paper:
            # A CLOSE_PENDING row now means TWO things, and only one of them
            # is safe to send another order on top of.
            #
            # It used to mean the broker REJECTED the close, so nothing was
            # live and a fresh flatten was the right move. The exit-booking
            # work added a second meaning — the broker ACCEPTED the close and
            # it has not printed yet — and on that row a second market order
            # is a second live close for one position, which is how a flatten
            # becomes a naked reverse. The retry loop refuses to stack for
            # exactly this reason; the kill switch was never taught the new
            # state, so it would have stacked. `residual_qty` makes it worse
            # rather than better: an accepted-but-unprinted close reports zero
            # filled, so the residual is the FULL position and the second
            # order is full size.
            #
            # Cancel it first, and refuse to send anything if the cancel
            # cannot be confirmed. A kill switch that leaves the position on
            # and says so in the sweep's `errors` channel is doing its job;
            # one that doubles the position is not.
            from bot_program.pending_closes import (
                _cancel_working_close, _reconcile_filled_against_broker,
            )
            if not _cancel_working_close(trade, client):
                raise RuntimeError(
                    f"trade {trade.id} has a close still working at the "
                    f"broker that could not be cancelled — refusing to send a "
                    f"second one on top of it; the position may still be OPEN "
                    f"and needs closing by hand at the broker")
            # And re-read the size, because the cancel is exactly when units
            # print: `outstanding` above was measured before it. Sending the
            # pre-cancel residual would sell what just filled a second time,
            # which is the same oversell the cancel was meant to avoid.
            _reconcile_filled_against_broker(trade, client)
            outstanding = residual_qty(trade)
            already_flat = outstanding <= dust_qty(
                getattr(trade, "asset_class", ""))
            if already_flat:
                # It finished while we were cancelling. Nothing left to send —
                # and sending a zero-size order is how a flatten becomes an
                # entry. The booking below still runs and prices what filled.
                logger.info("[KILL SWITCH] trade %s completed during the "
                            "cancel — nothing left to flatten", trade.id)
        if not trade.paper and not already_flat:
            # Cancel resting broker-side SL/TP first: a stop left behind after
            # we flatten would fire against a flat book and open a reverse
            # position — the opposite of what a kill switch is for.
            for oid in (trade.metadata or {}).get("protective_order_ids") or []:
                cancel = getattr(client, "cancel_order", None)
                if callable(cancel):
                    try:
                        cancel(oid)
                    except Exception as e:  # noqa: BLE001
                        logger.warning("[KILL SWITCH] cancel %s failed: %s", oid, e)
            if is_options:
                # A plain market_order here would trade the underlying's STOCK,
                # opening a new position instead of closing the option.
                if outstanding != Decimal(str(trade.qty)):
                    # submit_option_close has no size argument — it closes the
                    # whole position — so it cannot express a residual.
                    raise RuntimeError(
                        f"options trade {trade.id} is partly closed "
                        f"({outstanding} of {trade.qty} contracts left) and "
                        f"the option close path cannot submit a residual — "
                        f"close the remainder manually at the broker")
                result = submit_option_close(client, trade)
            else:
                result = _try_broker_close(client, trade.symbol, trade.side,
                                            outstanding)
    except Exception as e:  # noqa: BLE001
        logger.warning("[KILL SWITCH] broker close failed for %s: %s", trade.symbol, e)
        raise

    # Book the exit through the shared step, so a forced flatten is not the
    # one close whose price is an assumption. `result` stays None for a paper
    # row (nothing was submitted) and for a client with no market_order —
    # both resolve to the mark above and are stamped as such.
    from bot_program.pending_closes import resolve_exit_fill
    fill = resolve_exit_fill(trade, result, mark=Decimal(str(exit_price)))
    exit_price = float(fill["price"])

    if not fill["complete"]:
        # Part of the position is STILL LIVE at the broker. Leave the row
        # CLOSE_PENDING with the residual recorded — the retry beat task and
        # reconciliation both scan that status — and raise so the sweep
        # records the symbol in `errors`, which is where the operator reads
        # "these may still be open at the broker".
        trade.metadata = {**(trade.metadata or {}), **fill["metadata"]}
        trade.status = "CLOSE_PENDING"
        trade.save(update_fields=["metadata", "status"])
        raise RuntimeError(
            f"broker filled only {fill['filled_qty']} of {trade.qty} — "
            f"{fill['residual_qty']} still open; left CLOSE_PENDING for the "
            f"retry task")

    trade.metadata = {**(trade.metadata or {}), **fill["metadata"]}
    pnl = (exit_price - float(trade.entry_price)) * float(trade.qty)
    if trade.side == "SELL":
        pnl = -pnl
    if is_options:
        pnl *= float(option_pnl_multiplier(trade))
    elif trade.asset_class == "forex":
        # Same entry-time conversion as the bot's own close path — a forced
        # JPY close must not book yen into the USD P&L column.
        try:
            from bot_program.asset_engine.forex_bot import forex_usd_multiplier
            pnl *= float(forex_usd_multiplier(trade))
        except Exception:  # noqa: BLE001
            pass

    trade.exit_price = exit_price
    trade.closed_at = now
    trade.status = "CLOSED"
    trade.outcome = "manual_close"
    trade.pnl = pnl
    trade.save(update_fields=["exit_price", "closed_at", "status", "outcome",
                              "pnl", "metadata"])
