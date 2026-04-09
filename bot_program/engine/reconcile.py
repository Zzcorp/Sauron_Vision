"""Position reconciliation: sync open positions from Binance against BotTrade.

Catches three classes of drift:
  1. User manually closed a position in the Binance app (BotTrade still OPEN)
  2. Exchange-side liquidation (BotTrade still OPEN)
  3. Worker died mid-order (BotTrade row may not exist for an open exchange position)

Run this every N minutes via Celery.
"""
import logging
from decimal import Decimal
from django.utils import timezone

logger = logging.getLogger(__name__)


def reconcile_user(user_id):
    """Reconcile open BotTrades for one user against Binance live state.

    Returns dict with counts: closed_orphans, found_unknown_positions, ok.
    """
    from django.contrib.auth.models import User
    from ..models import BotTrade, BinanceAccount
    from .runner import _client_for

    try:
        user = User.objects.get(id=user_id)
        cfg = user.bot_config
    except Exception as e:
        return {"error": f"no config for user {user_id}: {e}"}

    if cfg.mode == "paper":
        return {"skipped": "paper mode — nothing to reconcile"}

    try:
        client = _client_for(user, cfg)
    except Exception as e:
        return {"error": f"client init failed: {e}"}

    open_trades = list(BotTrade.objects.filter(config=cfg, status="OPEN"))
    closed_orphans = 0
    found_unknown = 0
    errors = 0

    # Try to fetch current positions
    exchange_positions = {}
    try:
        if cfg.market_type == "futures" and hasattr(client, "positions"):
            for pos in client.positions():
                amt = float(pos.get("positionAmt", 0))
                if abs(amt) > 0:
                    exchange_positions[pos["symbol"]] = {
                        "qty": abs(amt),
                        "side": "BUY" if amt > 0 else "SELL",
                        "entry_price": float(pos.get("entryPrice", 0)),
                    }
    except Exception as e:
        logger.warning("could not fetch exchange positions: %s", e)
        return {"error": "exchange query failed"}

    # 1. Close orphan BotTrades (we have it OPEN but exchange doesn't)
    for t in open_trades:
        if t.symbol not in exchange_positions:
            try:
                tk = client.ticker(t.symbol)
                price = Decimal(str(tk.get("lastPrice", t.entry_price)))
                pnl = (price - t.entry_price) * t.qty if t.side == "BUY" \
                      else (t.entry_price - price) * t.qty
                t.exit_price = price
                t.pnl_usdt = pnl
                t.status = "CLOSED"
                t.closed_at = timezone.now()
                t.reason = (t.reason + " | reconcile:closed_externally").strip()
                t.save()
                closed_orphans += 1
            except Exception as e:
                logger.warning("could not close orphan %s: %s", t.symbol, e)
                errors += 1

    # 2. Flag unknown exchange positions (open on Binance, no BotTrade row)
    known_symbols = {t.symbol for t in open_trades if t.status == "OPEN"}
    for symbol in exchange_positions:
        if symbol not in known_symbols:
            found_unknown += 1
            logger.warning(
                "reconcile: exchange has open %s position for %s with no BotTrade row",
                symbol, user.username,
            )

    return {
        "closed_orphans": closed_orphans,
        "found_unknown_positions": found_unknown,
        "errors": errors,
        "checked_at": timezone.now().isoformat(),
    }
