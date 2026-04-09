"""Trailing stop management for open positions.

Updates BotTrade.stop_loss as the position moves in the favorable direction.
Called from runner._manage_positions() — never relaxes the stop, only tightens.
"""
from decimal import Decimal


def update_trailing_stop(trade, current_price, trail_pct):
    """Tighten the stop if the trade has moved favorably.

    Returns True if the stop was updated.
    """
    if trail_pct <= 0:
        return False
    price = Decimal(str(current_price))
    trail = Decimal(str(trail_pct)) / Decimal("100")

    if trade.side == "BUY":
        candidate = price * (Decimal("1") - trail)
        if candidate > trade.stop_loss:
            trade.stop_loss = candidate
            trade.save(update_fields=["stop_loss"])
            return True
    else:
        candidate = price * (Decimal("1") + trail)
        if candidate < trade.stop_loss:
            trade.stop_loss = candidate
            trade.save(update_fields=["stop_loss"])
            return True
    return False
