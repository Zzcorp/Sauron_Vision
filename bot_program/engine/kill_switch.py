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
from django.utils import timezone

logger = logging.getLogger(__name__)


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
        except Exception as e:  # noqa: BLE001
            msg = f"asset trade {trade.id} ({trade.symbol}): {e}"
            results["errors"].append(msg)
            logger.error("[KILL SWITCH] %s", msg)

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
    raises on broker error so the caller can record it."""
    if not hasattr(client, "market_order"):
        return
    close_side = "SELL" if side == "BUY" else "BUY"
    client.market_order(symbol, close_side, float(qty))


def _close_legacy_trade(trade, now):
    """Close one legacy crypto BotTrade and persist the close on the real schema."""
    from bot_program.engine.runner import _client_for

    # Route to the correct broker (or PaperTrader) BEFORE marking the exit,
    # so the booked price can come from the venue's own tick. The legacy
    # selector takes (user, cfg) — passing the config as the user arg was
    # the original bug.
    try:
        client = _client_for(trade.config.user, trade.config)
        exit_price = _market_exit_price(trade.symbol, trade.entry_price,
                                        client=client)
        _try_broker_close(client, trade.symbol, trade.side, trade.qty)
    except Exception as e:  # noqa: BLE001
        logger.warning("[KILL SWITCH] broker close failed for %s: %s", trade.symbol, e)
        raise

    pnl = (exit_price - float(trade.entry_price)) * float(trade.qty)
    if trade.side == "SELL":
        pnl = -pnl

    trade.exit_price = exit_price
    trade.closed_at = now
    trade.status = "CLOSED"
    trade.pnl_usdt = pnl
    trade.save(update_fields=["exit_price", "closed_at", "status", "pnl_usdt"])


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

    try:
        # Paper trades have no broker-side position to flatten — same rule
        # as AssetBot._close_trade. Submitting anyway can raise (PaperTrader
        # has no option order path) and strand the row OPEN forever.
        if not trade.paper:
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
                submit_option_close(client, trade)
            else:
                _try_broker_close(client, trade.symbol, trade.side, trade.qty)
    except Exception as e:  # noqa: BLE001
        logger.warning("[KILL SWITCH] broker close failed for %s: %s", trade.symbol, e)
        raise

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
    trade.save(update_fields=["exit_price", "closed_at", "status", "outcome", "pnl"])
