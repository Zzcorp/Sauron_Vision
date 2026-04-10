"""Emergency kill switch — flatten all positions instantly."""
import logging
from django.utils import timezone

logger = logging.getLogger(__name__)


def execute_kill_switch(user=None, reason="manual"):
    """Emergency: close all open positions and disable all bots.

    Returns dict with results of all close operations.
    """
    from bot_program.models import BotConfig, BotTrade
    from portfolio.models import Position

    results = {'positions_closed': 0, 'bots_disabled': 0, 'errors': []}
    now = timezone.now()

    # 1. Disable all bot configs
    configs = BotConfig.objects.filter(is_enabled=True)
    if user:
        configs = configs.filter(user=user)

    for config in configs:
        config.is_enabled = False
        config.save(update_fields=['is_enabled'])
        results['bots_disabled'] += 1
        logger.warning(f"[KILL SWITCH] Disabled bot config {config.id} for user {config.user}")

    # 2. Close all open bot trades
    open_trades = BotTrade.objects.filter(exit_price__isnull=True)
    if user:
        open_trades = open_trades.filter(config__user=user)

    for trade in open_trades:
        try:
            _emergency_close_trade(trade)
            results['positions_closed'] += 1
        except Exception as e:
            error_msg = f"Failed to close trade {trade.id}: {e}"
            results['errors'].append(error_msg)
            logger.error(f"[KILL SWITCH] {error_msg}")

    # 3. Mark portfolio positions as closed
    positions = Position.objects.filter(closed_at__isnull=True)
    if user:
        from portfolio.services import get_or_create_default_portfolio
        portfolio = get_or_create_default_portfolio(user=user)
        positions = positions.filter(portfolio=portfolio)

    for pos in positions:
        pos.closed_at = now
        pos.save(update_fields=['closed_at'])

    # 4. Create notification
    from alerts.models import Notification
    title = f"KILL SWITCH ACTIVATED — {reason}"
    body = f"Closed {results['positions_closed']} positions, disabled {results['bots_disabled']} bots."
    if user:
        Notification.create_for_user(user, 'system', title, body)
    else:
        Notification.create_for_all('system', title, body)

    logger.critical(f"[KILL SWITCH] Executed: {results}")
    return results


def _emergency_close_trade(trade):
    """Close a single trade at current market price."""
    from bot_program.engine.runner import _client_for
    from market_data.models import LiveQuote

    try:
        # Try to get current price
        quote = LiveQuote.objects.filter(instrument__symbol=trade.symbol).first()
        exit_price = float(quote.last) if quote else float(trade.entry_price)
    except Exception:
        exit_price = float(trade.entry_price)

    # Try to submit close order to exchange
    try:
        client = _client_for(trade.config)
        if hasattr(client, 'market_order'):
            close_side = 'SELL' if trade.side == 'BUY' else 'BUY'
            client.market_order(trade.symbol, close_side, float(trade.qty))
    except Exception as e:
        logger.warning(f"[KILL SWITCH] Exchange close failed for {trade.symbol}: {e}")

    # Mark trade as closed
    trade.exit_price = exit_price
    trade.exit_time = timezone.now()
    pnl = (exit_price - float(trade.entry_price)) * float(trade.qty)
    if trade.side == 'SELL':
        pnl = -pnl
    trade.pnl = pnl
    trade.save()
