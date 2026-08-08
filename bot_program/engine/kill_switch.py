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
    open_asset = AssetBotTrade.objects.filter(status="OPEN")
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
            f" ⚠ {len(results['errors'])} broker-close error(s) — these symbols "
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


def _market_exit_price(symbol, fallback):
    """Best-effort current price for `symbol`; fall back to the trade entry."""
    from market_data.models import LiveQuote
    try:
        quote = LiveQuote.objects.filter(instrument__symbol=symbol).first()
        if quote and quote.last:
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

    exit_price = _market_exit_price(trade.symbol, trade.entry_price)

    # Route to the correct broker (or PaperTrader). The legacy selector takes
    # (user, cfg) — passing the config as the user arg was the original bug.
    try:
        client = _client_for(trade.config.user, trade.config)
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

    exit_price = _market_exit_price(trade.symbol, trade.entry_price)

    try:
        client = client_for_symbol(trade.config.user, trade.symbol, trade.config)
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
    trade.outcome = "manual_close"
    trade.pnl = pnl
    trade.save(update_fields=["exit_price", "closed_at", "status", "outcome", "pnl"])
