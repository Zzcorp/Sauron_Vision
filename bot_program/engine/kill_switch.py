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

from bot_program.engine import etoro_budget
from bot_program.etoro_cells import one_read_per_pass

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


@one_read_per_pass()
@etoro_budget.scoped(etoro_budget.P0, "kill switch")
def execute_kill_switch(user=None, reason="manual"):
    """Emergency: disable all bots and close all open positions.

    The account is read again once the sweep has finished, one read per
    eToro account however many rows it flattened (2026-10-31,
    bot_program.etoro_cells): never between two of its closes.

    P0 in the eToro request budget (2026-11-01, engine/etoro_budget): every
    request of the sweep — its closes, their proofs, the cancels of
    working entries and the marks its exits are booked at — is counted
    once sent, never refused, never delayed and never held by the 429
    pause; a family it takes past its rate logs the overrun once a minute.

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
        # PAPER rows NOT booked because their market is shut (2026-09-26):
        # they stay OPEN; see _paper_booking_waits.
        "paper_waiting": [],
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

    # THE RECORD (2026-10-07, asset_engine/disarm.py). The stop goes
    # through disarm.disable_config, which records it as the kill switch's
    # (who pressed it, and the reason). That record is what keeps these
    # configs' REAL rows UNMANAGED: the runner manages them only for a
    # config a brake stopped, and the real rows this sweep cannot close are
    # left for reconciliation by hand (step 3 below), never for a manage
    # pass to close behind it. A PAPER row has no broker: the one this
    # sweep cannot book (its market shut) is managed by the runner's
    # paper-only pass, exits only (2026-10-08, runner.manage_stopped_paper).
    from bot_program.asset_engine import disarm
    who = getattr(user, "username", "") or "platform-wide"
    asset_configs = AssetBotConfig.objects.filter(enabled=True)
    if user:
        asset_configs = asset_configs.filter(user=user)
    for config in asset_configs:
        if disarm.disable_config(config, by=disarm.BY_KILL_SWITCH,
                                 why=reason, who=who):
            results["asset_bots_disabled"] += 1
            logger.warning(
                "[KILL SWITCH] Disabled AssetBotConfig %s (%s, user=%s)",
                config.id, config.asset_class, config.user,
            )
    # A config a BRAKE had already stopped is still managed by the runner.
    # The kill switch's stop supersedes that record, so its open rows are
    # left alone from here on like every other config's. It is not counted
    # in asset_bots_disabled: it was off already.
    braked = AssetBotConfig.objects.filter(enabled=False)
    if user:
        braked = braked.filter(user=user)
    for config in braked:
        if disarm.keeps_managing(config):
            disarm.disable_config(config, by=disarm.BY_KILL_SWITCH,
                                  why=reason, who=who)

    # THE ORCS (bot_program/orcs, O1): every idea in scope ends here, before
    # the sweep closes its rows, with no re-entry window — whatever the
    # orcs switch says. Orc tables only; a failure never stops the flatten.
    try:
        from bot_program.orcs.lifecycle import kill_all
        kill_all(user, reason=reason)
    except Exception as e:  # noqa: BLE001
        logger.warning("[KILL SWITCH] the Orcs were not ended: %s", e)

    # ── 2. Close open legacy (crypto) trades ─────────────────────────────────
    open_legacy = BotTrade.objects.filter(status="OPEN")
    if user:
        open_legacy = open_legacy.filter(config__user=user)
    for trade in open_legacy:
        waits = _paper_booking_waits(trade)
        if waits:
            results["paper_waiting"].append(waits)
            continue
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
        waits = _paper_booking_waits(trade)
        if waits:
            results["paper_waiting"].append(waits)
            continue
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
    if results["paper_waiting"]:
        body += (
            f" {len(results['paper_waiting'])} paper position(s) were NOT "
            f"booked because their market is shut or has not priced them "
            f"since it reopened: "
            f"{'; '.join(results['paper_waiting'])}. Every bot is disabled "
            f"all the same; the rows stay OPEN — close them from the "
            f"positions page once their market has a price again."
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


def _paper_booking_waits(trade) -> str:
    """"" — or "EURCAD #108: the forex market is shut (reopens Sunday 21:00
    UTC)" for a PAPER row whose market is shut (2026-09-26), or settling
    after its open, or open for less than REOPEN_PRICE_GRACE_SECONDS with
    nothing that prices the row since.

    The switch still disables every bot (step 1 ran before any close) and
    still flattens every LIVE row: a venue decides whether its own close
    fills. Only the paper BOOKING waits, because the only price a shut
    market offers is the last one before it shut, and a flatten booked at
    Friday's price on a Saturday is an exit nobody could have had. The
    same holds in the first hours after a reopen when the paper venue has
    no price of the new session yet: _market_exit_price would fall back to
    a raw LiveQuote or to the ENTRY price. The row stays OPEN, and the
    notification and the results name it. (An options row is marked at
    its premium, which the paper ticker does not price: only the clock is
    asked for it.)"""
    if not getattr(trade, "paper", False):
        return ""
    from bot_program.engine.paper_trader import (
        PaperTrader, paper_awaits_first_price, paper_market_shut)
    cls = getattr(trade, "asset_class", "") or ""
    shut = paper_market_shut(trade.symbol, cls)
    if not shut and cls != "options":
        # The clock first (no price read at all outside the hours after an
        # open, or with the gate off), then whether the paper venue prices
        # the row yet.
        young = paper_awaits_first_price(trade.symbol, cls)
        if young:
            try:
                priced = float((PaperTrader(None).ticker(trade.symbol) or {})
                               .get("lastPrice") or 0) > 0
            except Exception:  # noqa: BLE001 — unreadable is unpriced
                priced = False
            if not priced:
                shut = young
    if not shut:
        return ""
    logger.warning("[KILL SWITCH] paper trade %s (%s) NOT booked: %s — the "
                   "row stays OPEN until its market reopens",
                   trade.id, trade.symbol, shut)
    return f"{trade.symbol} #{trade.id}: {shut}"


def _market_exit_price(symbol, fallback, client=None, trade=None):
    """Best-effort current price for `symbol`; fall back to the trade entry.

    Returns (price, unpriced, mark_age_s): `unpriced` is True when a REAL
    row's price is the entry's stand-in that nothing could price;
    `mark_age_s` is the age of the STALE venue print that priced it, else
    None. WRITES NOTHING ON THE ROW (2026-10-15, re-check): the verdict
    used to be written into trade.metadata here, before any order was
    sent, and every later save persisted it — the CLOSE_PENDING save
    eToro's unproven close lands on first of all — while nothing that
    later priced the row cleared it; the drain then booked a real loss
    beside the flag and the daily stop skipped it. The CLOSED booking in
    _close_asset_trade decides from this verdict and the fills.

    The broker's own tick is asked first — its print is the book the forced
    close will actually fill on (and for paper trades the router hands back
    PaperTrader, whose ticker already enforces quote freshness with a bar
    fallback). The direct LiveQuote read rejects stale rows: the kill switch
    runs precisely when things are broken, which is when a dead poller's
    fossil is most likely to be sitting in the table — booking a forced
    close at a price from an hour ago fabricates P&L.

    A REAL AssetBotTrade (`trade`, 2026-10-08) falls back through the one
    answer, venue_mark.for_booking: its fresh venue stamp first; the
    LiveQuote only where it is the venue's own instrument and fresh; never
    a quote of another instrument — Gold Spot booked at GC=F, the future,
    would book the basis as P&L. A STALE venue print only where
    venue_mark.bookable allows it (within an hour, or the venue's price at
    the close of a shut market: the ticker that failed here is what stopped
    the stamps, so a fresh one is rare exactly when this runs). With
    nothing bookable the row's exit is UNPRICED (the booking writes
    `exit_price_unavailable`, pnl NULL), never the entry's confident zero:
    a forced close of a real loser is not a scratch.
    """
    from bot_program.engine.paper_trader import PaperTrader

    real = trade is not None and not getattr(trade, "paper", True)
    if client is not None and hasattr(client, "ticker"):
        try:
            last = float((client.ticker(symbol) or {}).get("lastPrice", 0) or 0)
            if last > 0:
                return last, False, None
        except Exception as e:  # noqa: BLE001
            logger.warning("[KILL SWITCH] ticker(%s) failed, falling back "
                           "to LiveQuote: %s", symbol, e)

    try:
        from django.utils import timezone as tz
        from market_data.models import LiveQuote
        quote = LiveQuote.objects.filter(instrument__symbol=symbol).first()
        if real:
            from bot_program import venue_mark
            mk = venue_mark.for_booking(trade, quote)
            if mk is None:
                return float(fallback), True, None
            # The age rides with ANY booked mark older than a live one: a
            # stale venue print, or a quote taken at a shut market's close
            # (2026-10-15, re-check: a fifteen-hour quote booked over a
            # weekend is otherwise indistinguishable from a fresh fill).
            age = (int(round(mk.age_s))
                   if mk.age_s is not None
                   and (mk.source == venue_mark.VENUE_STALE
                        or mk.age_s > venue_mark.MAX_AGE_S) else None)
            return float(mk.price), False, age
        if quote and quote.last:
            age = (tz.now() - quote.updated_at).total_seconds()
            if age <= PaperTrader.MAX_QUOTE_AGE_SECONDS:
                return float(quote.last), False, None
    except Exception as e:  # noqa: BLE001
        logger.warning("[KILL SWITCH] %s: the fallback mark could not be "
                       "read: %s", symbol, e)
    # The entry stands in. For a real row that is an UNPRICED exit, and the
    # booking records the P&L as unmeasured, never as a scratch.
    return float(fallback), real, None


def _claim_in_flight(meta) -> bool:
    """Does `meta` (a row's metadata as the database holds it) carry a
    FRESH close claim (manual_close.CLAIM_KEY, the one the CLOSE button,
    the pending-close drain and the reconcile take)? A stale claim — its
    worker died — is not one."""
    from bot_program.manual_close import CLAIM_KEY, _stale
    held = (meta or {}).get(CLAIM_KEY) if isinstance(meta, dict) else None
    return bool(held) and not _stale(str(held))


def _locked_merge(trade, ours: dict, *, closing: bool):
    """Under the row lock (the caller's transaction): re-read the row, and
    give back its CURRENT metadata with `ours` laid over it — never the
    snapshot the sweep loaded, so a key another writer put there meanwhile
    survives. None (write nothing) when the row was CLOSED elsewhere while
    the switch was at the broker, or when another close holds its claim.
    `closing` says which save asks: the CLOSE_PENDING save RAISES in both
    cases (the switch's own close may still be working at the broker, and
    the sweep's `errors` is where the operator reads that); the CLOSED
    booking returns None for a row closed elsewhere (that close keeps its
    own words and its single grade) and raises for a claim held."""
    from bot_program.reconcile_asset import UNPRICED_EXIT_KEY
    row = (type(trade).objects.select_for_update().filter(pk=trade.pk)
           .values_list("status", "metadata").first())
    status, current = row if row else (None, {})
    if status not in ("OPEN", "CLOSE_PENDING"):
        if not closing:
            raise RuntimeError(
                f"trade {trade.id} ({trade.symbol}) was closed elsewhere "
                f"({status}) while the switch's own close was answered "
                f"unfinished — that close may still be working at the "
                f"broker; check the broker's order list")
        logger.info("[KILL SWITCH] trade %s was closed elsewhere (%s) "
                    "while it was being flattened — left as that close "
                    "wrote it", trade.id, status)
        return None
    if _claim_in_flight(current):
        raise RuntimeError(
            f"trade {trade.id} ({trade.symbol}): another close took the row "
            f"while the switch was at the broker — the switch's own close was "
            f"sent and is NOT booked here; that close books the row. Check "
            f"the broker's order list")
    merged = {**(current if isinstance(current, dict) else {}), **ours}
    merged.pop(UNPRICED_EXIT_KEY, None)
    merged.pop("exit_mark_age_s", None)
    return merged


def _kill_order_id(trade) -> str:
    """A stable name for "flatten THIS row", so a repeat is a copy."""
    from bot_program.engine.idempotency import make_client_order_id
    try:
        return make_client_order_id(
            config_id=int(getattr(trade, "config_id", 0) or 0),
            symbol=str(trade.symbol), signal_id=str(trade.id),
            intent="KILL")
    except Exception:  # pragma: no cover - never block a flatten
        return ""


def _try_broker_close(client, symbol, side, qty, client_order_id="",
                      trade=None):
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
    # THE VENUE DECIDES WHAT A CLOSE IS. On eToro market_order only ever
    # OPENS — a SELL is `sellShort` — and under Saxo's FifoEndOfDay an
    # opposite order leaves both lots live. This is the worst place in the
    # platform to get that wrong: the switch fires because something is
    # already wrong, and the "flatten" would have doubled the exposure it was
    # pressed to remove. `trade` is threaded in for the position id; without
    # one venue_close raises and the caller records the failure, exactly as
    # it already does for a broker refusal.
    if trade is not None:
        from bot_program.engine.venue_close import close_or_refuse
        return close_or_refuse(trade, client, float(qty),
                               close_side=close_side,
                               client_order_id=client_order_id)
    # The kill switch is the WORST place to send an anonymous order.
    # It fires when something is already wrong, it can be triggered
    # twice by two operators or by a retry, and it flattens at
    # market. Every other exit path here stamps a deterministic
    # client_order_id so the broker itself refuses the second copy;
    # this one sent none, so two overlapping flattens meant two
    # full-size market orders - and the second one is a reversal.
    kwargs = {}
    if client_order_id:
        kwargs["client_order_id"] = client_order_id
    return client.market_order(symbol, close_side, float(qty), **kwargs)


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
        exit_price, _unpriced, _age = _market_exit_price(
            trade.symbol, trade.entry_price, client=client)
        result = _try_broker_close(
            client, trade.symbol, trade.side, trade.qty,
            client_order_id=_kill_order_id(trade), trade=trade)
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
    from bot_program.engine.broker_router import session_busy
    from bot_program.pending_closes import is_paper_client
    if not trade.paper and is_paper_client(client):
        if session_busy(client):
            # BUSY, not broken. The IBKR trading session is exclusive (one
            # clientId, because an order is visible only to the session
            # that placed it) and another process is holding it. Telling
            # the operator the broker is unavailable would point them at
            # the HQ disconnect, which really would put every live path on
            # paper. Say what is true, and name the retry.
            raise RuntimeError(
                f"live trade {trade.id} ({trade.symbol}) could not be "
                f"flattened: the exclusive IBKR trading session is held by "
                f"another process (a bot tick or a close in flight). NOTHING "
                f"was sent and the broker is fine — press EMERGENCY FLATTEN "
                f"again in a few seconds, or close it at the broker")
        raise RuntimeError(
            f"live trade {trade.id} ({trade.symbol}) routed to PaperTrader "
            f"(broker unavailable) — no close was sent and the position is "
            f"still open at the broker; close it manually")

    # A CLOSE ALREADY IN FLIGHT ELSEWHERE (2026-10-15, re-check). The CLOSE
    # button, the pending-close drain and the reconcile all take one claim
    # (manual_close.CLAIM_KEY) before they act on a row; the switch neither
    # took nor honoured it, so it could send a second close on top of one
    # in flight and then write its own CLOSE_PENDING over a row the
    # reconcile had just booked CLOSED. A row whose claim is held and fresh
    # is left to that close and named in `errors`, as the reconcile does.
    if _claim_in_flight(type(trade).objects.filter(pk=trade.pk)
                        .values_list("metadata", flat=True).first()):
        raise RuntimeError(
            f"trade {trade.id} ({trade.symbol}) is being closed elsewhere "
            f"right now (the CLOSE button, the pending-close drain or the "
            f"reconcile holds it) — the switch sent nothing for it rather "
            f"than stack a second close; if it is still open in a few "
            f"minutes, press EMERGENCY FLATTEN again")

    # A WORKING entry is a queued ORDER, not a position. Flattening it would
    # send a market order against a position that does not exist yet — and
    # leave the queued parent to fill afterwards, opening a position DURING
    # an emergency stop. Withdraw it instead; that is what "flatten" means
    # for an order.
    from bot_program.asset_engine.base import (cancel_working_entry,
                                               is_entry_working)
    if is_entry_working(trade):
        if cancel_working_entry(trade, client,
                                reason="EMERGENCY FLATTEN"):
            return
        raise RuntimeError(
            f"trade {trade.id} ({trade.symbol}) is an unfilled entry that "
            f"could not be withdrawn — it may still fill; cancel the order "
            f"at the broker by hand")

    # A LEFTOVER VERDICT NEVER DECIDES THIS ATTEMPT (2026-10-15, re-check):
    # a CLOSE_PENDING row may carry the flag an earlier attempt wrote (the
    # code before this date wrote it before the order was sent). Cleared in
    # memory here; the booking below writes its own verdict, and every
    # save on the way (the cancel of a working close, the partial branch)
    # carries the row without it.
    from bot_program.reconcile_asset import UNPRICED_EXIT_KEY
    if UNPRICED_EXIT_KEY in (trade.metadata or {}) \
            or "exit_mark_age_s" in (trade.metadata or {}):
        _clean = dict(trade.metadata or {})
        _clean.pop(UNPRICED_EXIT_KEY, None)
        _clean.pop("exit_mark_age_s", None)
        trade.metadata = _clean

    # The mark's verdict: `unpriced` means a REAL row's exit is the entry's
    # stand-in that nothing priced; `mark_age` the age of the stale venue
    # print that priced it (None otherwise). Both stay OUT of the row
    # until the CLOSED booking below decides with the fills.
    unpriced, mark_age = False, None
    if is_options:
        # Premium-denominated trade: LiveQuote holds the UNDERLYING's price,
        # which is the wrong scale — mark at the option's own premium. With
        # none the entry premium stands in, and a REAL row is then UNPRICED
        # like any other real row nothing priced (2026-10-15): a forced
        # close of a real option at its entry premium is not a scratch.
        from bot_program.asset_engine.options_bot import (
            current_premium_for_trade, submit_option_close,
            option_pnl_multiplier,
        )
        premium = current_premium_for_trade(trade)
        if premium:
            exit_price = float(premium)
        else:
            exit_price, unpriced = float(trade.entry_price), not trade.paper
    else:
        exit_price, unpriced, mark_age = _market_exit_price(
            trade.symbol, trade.entry_price, client=client, trade=trade)

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
    # Protective legs a cancel could not take off the book: carried onto
    # the row by the saves below (they merge onto the locked row).
    left_resting = []
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
            # which is the same oversell the cancel was meant to avoid. The
            # units it finds filled are priced at THIS switch's mark, with
            # its verdict (2026-10-15, re-check): the ticker that just failed
            # is not asked again, and a slice at the entry's stand-in is
            # marked unpriced — a real row already flat at the venue is
            # never booked as a confident scratch.
            _reconcile_filled_against_broker(
                trade, client, mark=Decimal(str(exit_price)),
                unpriced=unpriced)
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
            # AND READ THE ANSWER. SaxoTrader.cancel_order returns a bool
            # for exactly this reason — a dict is always truthy, and a stop
            # still resting that reads as cancelled is the failure the return
            # type exists to prevent. Throwing the answer away made the
            # switch book the row CLOSED over a stop that was never cancelled.
            left_resting = []
            for oid in (trade.metadata or {}).get("protective_order_ids") or []:
                cancel = getattr(client, "cancel_order", None)
                if callable(cancel):
                    try:
                        answer = cancel(oid)
                    except Exception as e:  # noqa: BLE001
                        logger.warning("[KILL SWITCH] cancel %s failed: %s", oid, e)
                        left_resting.append(str(oid))
                        continue
                    # False is a REFUSAL, not a cancel. None is an adapter
                    # that does not say, which is the old behaviour and stays
                    # trusted: only an explicit no counts as a no.
                    if answer is False:
                        logger.error("[KILL SWITCH] %s refused the cancel of "
                                     "%s — the leg is still resting",
                                     trade.symbol, oid)
                        left_resting.append(str(oid))
            if left_resting:
                # The flatten still goes ahead: a live position during a kill
                # is the larger risk. But an unflagged resting stop fires
                # against a flat book and OPENS a reverse position, so the
                # row carries it and the log names it.
                meta = trade.metadata or {}
                meta["kill_left_resting_orders"] = left_resting
                trade.metadata = meta
                logger.error("[KILL SWITCH] %s: flattening with %d protective "
                             "order(s) still resting (%s) — they fire against "
                             "a flat book and OPEN a reverse position. Cancel "
                             "them at the broker NOW",
                             trade.symbol, len(left_resting),
                             ", ".join(left_resting))
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
                result = _try_broker_close(
                    client, trade.symbol, trade.side, outstanding,
                    client_order_id=_kill_order_id(trade), trade=trade)
    except Exception as e:  # noqa: BLE001
        logger.warning("[KILL SWITCH] broker close failed for %s: %s", trade.symbol, e)
        raise

    # Book the exit through the shared step, so a forced flatten is not the
    # one close whose price is an assumption. `result` stays None for a paper
    # row (nothing was submitted) and for a client with no market_order —
    # both resolve to the mark above and are stamped as such.
    from django.db import transaction

    from bot_program.pending_closes import (CLOSE_FILLS_KEY,
                                            EXIT_SOURCE_BROKER,
                                            UNPRICED_SLICE_KEY,
                                            booking_unpriced,
                                            resolve_exit_fill)
    _prior_fills = len((trade.metadata or {}).get(CLOSE_FILLS_KEY) or [])
    fill = resolve_exit_fill(trade, result, mark=Decimal(str(exit_price)))
    exit_price = float(fill["price"])
    # PER FILL (2026-10-15): the slice THIS attempt added at an unpriced
    # mark is marked so in the ledger — the broker's own avgPrice on it is
    # a price, the entry stand-in is not. The CLOSED booking below reads
    # the ledger; a CLOSE_PENDING row carries the marked slice, never the
    # row-level flag.
    _fills = fill["metadata"].get(CLOSE_FILLS_KEY) or []
    if unpriced and len(_fills) > _prior_fills \
            and _fills[-1].get("source") != EXIT_SOURCE_BROKER:
        _fills[-1][UNPRICED_SLICE_KEY] = True
    # What THIS attempt writes, laid over the row as the database holds it
    # at the save (`_locked_merge`), never over the snapshot the sweep
    # loaded: the switch was at the broker meanwhile, and another writer's
    # keys survive.
    ours = dict(fill["metadata"])
    if left_resting:
        ours["kill_left_resting_orders"] = left_resting

    if not fill["complete"]:
        # Part of the position is STILL LIVE at the broker. Leave the row
        # CLOSE_PENDING with the residual recorded — the retry beat task and
        # reconciliation both scan that status — and raise so the sweep
        # records the symbol in `errors`, which is where the operator reads
        # "these may still be open at the broker". UNDER THE ROW LOCK with a
        # status check, like the CLOSED booking (2026-10-15, re-check): a
        # row the reconcile booked CLOSED while eToro answered this close
        # PENDING is never turned back to CLOSE_PENDING — that took a
        # measured loss out of the daily stop and booked the row twice.
        with transaction.atomic():
            trade.metadata = _locked_merge(trade, ours, closing=False)
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
    # What a scale-out banked (position_care, 2026-10-04): already in base
    # currency, added outside the multipliers, as AssetBot._realised_pnl does.
    try:
        from bot_program.asset_engine.base import AssetBot
        pnl += float(AssetBot.banked_pnl(trade))
    except Exception:  # noqa: BLE001
        pass

    trade.exit_price = exit_price
    trade.closed_at = now
    trade.status = "CLOSED"
    trade.outcome = "manual_close"
    # THE BOOKING DECIDES PER FILL (2026-10-15, re-check). A real row is
    # UNPRICED — the flag, pnl NULL, never the entry's zero, as the
    # reconcile books an orphan — only when the blended exit is not the
    # broker's own fill and NO slice in the ledger was priced (each slice
    # at an entry stand-in is marked `unpriced` above). `exit_mark_age_s`
    # rides the row only when a STALE venue print priced the exit the
    # fills did not: a fresh print and the broker's fill carry no age. The
    # rule is pending_closes.booking_unpriced, the one the drain's finaliser
    # and the reconcile's orphan close ask too.
    # WRITTEN ONLY OVER A ROW STILL OPEN, checked under the row lock (the
    # reconcile's rule, 2026-10-15 here): a close that landed while the
    # broker was being asked keeps its own words and its single grade.
    from bot_program.pending_closes import EXIT_FILL_SOURCE_KEY
    with transaction.atomic():
        _meta = _locked_merge(trade, ours, closing=True)
        if _meta is None:
            return
        _by_broker = (str(_meta.get(EXIT_FILL_SOURCE_KEY) or "")
                      == EXIT_SOURCE_BROKER)
        if booking_unpriced(_meta):
            _meta[UNPRICED_EXIT_KEY] = True
            pnl = None
        elif not _by_broker and mark_age is not None and not unpriced:
            _meta["exit_mark_age_s"] = int(mark_age)
        trade.metadata = _meta
        trade.pnl = pnl
        trade.save(update_fields=["exit_price", "closed_at", "status",
                                  "outcome", "pnl", "metadata"])
        # The account is read again once this commits (2026-10-31,
        # bot_program.etoro_cells): the sweep holds the ask, and asks one
        # read per account however many rows it flattens, once it has
        # finished (execute_kill_switch). Fenced inside.
        from bot_program import etoro_cells
        etoro_cells.refresh_for_trade(trade, why="kill switch")
