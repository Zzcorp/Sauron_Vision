"""Drain trades stuck in CLOSE_PENDING.

A CLOSE_PENDING AssetBotTrade means the bot decided to flatten but the
broker order failed. The position is therefore **still open at the broker**
while the bot believes it should be flat — the most dangerous state in the
system, and the one the old code hid by marking the row CLOSED regardless.

This module resubmits the close on a 5-minute cadence. A row leaves
CLOSE_PENDING only when the broker accepts the close (-> CLOSED, graded) or
when reconciliation observes the position is genuinely gone.

Escalation: after `ALERT_AFTER_ATTEMPTS` failures the user is alerted again
(a stranded live position needs human eyes, not silent retries).
"""
from __future__ import annotations

import logging
from decimal import Decimal

from django.utils import timezone

logger = logging.getLogger(__name__)

# Alert again after this many consecutive failed retries.
ALERT_AFTER_ATTEMPTS = 3


def _mark_price(trade, client) -> Decimal:
    """Best-effort current price on the trade's own scale."""
    if trade.asset_class == "options":
        try:
            from bot_program.asset_engine.options_bot import current_premium_for_trade
            return current_premium_for_trade(trade) or trade.entry_price
        except Exception:
            return trade.entry_price
    try:
        tk = client.ticker(trade.symbol) or {}
        last = float(tk.get("lastPrice", 0) or 0)
        if last > 0:
            return Decimal(str(last))
    except Exception:
        pass
    return trade.entry_price


def _pnl(trade, price: Decimal) -> Decimal:
    if trade.side == "BUY":
        pnl = (price - trade.entry_price) * trade.qty
    else:
        pnl = (trade.entry_price - price) * trade.qty
    if trade.asset_class == "options":
        try:
            from bot_program.asset_engine.options_bot import option_pnl_multiplier
            pnl *= option_pnl_multiplier(trade)
        except Exception:
            pass
    return pnl


def _submit_close(trade, client) -> None:
    """Resubmit the broker close. Raises on failure."""
    from bot_program.engine.idempotency import make_client_order_id

    client_order_id = make_client_order_id(
        config_id=trade.config_id, symbol=trade.symbol,
        signal_id=str(trade.id), intent="EXIT",
        bar_ts=timezone.now().strftime("%Y%m%d%H%M"),
    )
    if trade.asset_class == "options":
        from bot_program.asset_engine.options_bot import submit_option_close
        submit_option_close(client, trade, client_order_id=client_order_id)
        return
    close_side = "SELL" if trade.side == "BUY" else "BUY"
    client.market_order(trade.symbol, close_side, float(trade.qty),
                        client_order_id=client_order_id)


def _attempts(trade) -> int:
    return int((trade.metadata or {}).get("close_retry_attempts") or 0)


def _record_attempt(trade, *, ok: bool, error: str = "") -> None:
    meta = dict(trade.metadata or {})
    meta["close_retry_attempts"] = 0 if ok else _attempts(trade) + 1
    meta["close_retry_last_at"] = timezone.now().isoformat()
    if error:
        meta["close_retry_last_error"] = error[:300]
    trade.metadata = meta


def _alert_stranded(trade, attempts: int, error: str) -> None:
    try:
        from alerts.models import Notification
        Notification.objects.create(
            user=trade.config.user, notification_type="bot",
            title=f"🚨 Stranded position: {trade.symbol}",
            body=(f"{trade.asset_class} trade #{trade.id} has failed to close "
                  f"{attempts} times and is STILL OPEN at the broker. "
                  f"Last error: {error[:160]}. Close it manually at the broker "
                  f"if this persists."),
            url="/eye/fills/",
        )
    except Exception as e:
        logger.warning("stranded-position alert failed for #%s: %s", trade.id, e)


def retry_trade_close(trade) -> bool:
    """Retry one CLOSE_PENDING trade. True when it ended CLOSED."""
    from bot_program.engine.broker_router import client_for_symbol

    client = client_for_symbol(trade.config.user, trade.symbol, trade.config)
    try:
        _submit_close(trade, client)
    except Exception as e:
        attempts = _attempts(trade) + 1
        _record_attempt(trade, ok=False, error=str(e))
        trade.save(update_fields=["metadata"])
        logger.error("close retry #%s failed for trade %s (attempt %d): %s",
                     trade.id, trade.symbol, attempts, e)
        if attempts % ALERT_AFTER_ATTEMPTS == 0:
            _alert_stranded(trade, attempts, str(e))
        return False

    price = _mark_price(trade, client)
    trade.exit_price = price
    trade.pnl = _pnl(trade, price)
    trade.status = "CLOSED"
    trade.closed_at = timezone.now()
    trade.reason = ((trade.reason or "") + " | closed:RETRY").strip()[:1000]
    _record_attempt(trade, ok=True)
    trade.save()

    # Grade + audit + tax lots, same as a first-attempt close. Never fatal.
    try:
        from bot_program.bot_grading import grade_bot_trade
        grade_bot_trade(trade)
    except Exception as e:
        logger.warning("close retry grading failed for #%s: %s", trade.id, e)
    try:
        from bot_program.audit import record_trade_close
        record_trade_close(trade.config.user, trade=trade)
    except Exception as e:
        logger.warning("close retry audit failed for #%s: %s", trade.id, e)
    try:
        from bot_program.tax_lots import close_lots_for
        close_lots_for(trade)
    except Exception as e:
        logger.warning("close retry tax_lots failed for #%s: %s", trade.id, e)

    logger.info("close retry succeeded for trade #%s (%s)", trade.id, trade.symbol)
    return True


def retry_all_pending_closes() -> dict:
    """Retry every CLOSE_PENDING live trade. Paper rows never reach this
    state (they have no broker order to fail)."""
    from bot_program.models import AssetBotTrade

    qs = (AssetBotTrade.objects
          .filter(status="CLOSE_PENDING", paper=False)
          .select_related("config", "config__user"))
    out = {"pending": 0, "closed": 0, "still_pending": 0}
    for trade in qs:
        out["pending"] += 1
        try:
            if retry_trade_close(trade):
                out["closed"] += 1
            else:
                out["still_pending"] += 1
        except Exception as e:
            logger.exception("close retry crashed for #%s: %s", trade.id, e)
            out["still_pending"] += 1
    return out
