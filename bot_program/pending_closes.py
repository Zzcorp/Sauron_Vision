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
# Stop resubmitting after this many failures. A close that can never succeed
# (delisted symbol, revoked credentials, closed account) must not fire a live
# market order every 5 minutes forever, nor storm the alert channel; the row
# moves to ERROR for a human instead.
MAX_RETRY_ATTEMPTS = 12


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
    elif trade.asset_class == "forex":
        # Same entry-time conversion as every other close path — yen must
        # not land unconverted in the column the USD daily-loss gate sums.
        try:
            from bot_program.asset_engine.forex_bot import forex_usd_multiplier
            pnl *= forex_usd_multiplier(trade)
        except Exception:
            pass
    return pnl


def broker_still_holds(trade, client):
    """Does the broker still report this position? None = cannot tell.

    Resubmitting a market close blindly is how a retry turns into a NEW
    naked position in the opposite direction: if the original close
    actually filled (and only the response was lost), or a protective leg
    fired in between, the account is already flat.
    """
    fn = getattr(client, "get_positions", None)
    if not callable(fn):
        return None
    try:
        positions = list(fn() or [])
    except Exception as e:
        logger.warning("close retry: get_positions() failed for %s: %s",
                       trade.symbol, e)
        return None

    symbols, opt_underlyings, typed = set(), set(), False
    for p in positions:
        sym = (p.get("symbol") if isinstance(p, dict)
               else getattr(p, "symbol", None))
        sec = (p.get("sec_type") if isinstance(p, dict)
               else getattr(p, "sec_type", None))
        if not sym:
            continue
        symbols.add(str(sym).upper())
        if sec is not None:
            typed = True
            if str(sec).upper() == "OPT":
                opt_underlyings.add(str(sym).upper())

    if trade.asset_class == "options":
        occ = str((trade.metadata or {}).get("occ_symbol") or "").upper()
        if occ and occ in symbols:
            return True
        if trade.symbol.upper() in opt_underlyings:
            return True
        # Same rule as reconciliation: without an OCC symbol or a sec-typed
        # feed we cannot see options at all — don't guess.
        return False if (occ or typed) else None
    return trade.symbol.upper() in symbols


def _submit_close(trade, client) -> None:
    """Resubmit the broker close. Raises on failure."""
    from bot_program.engine.idempotency import make_client_order_id

    # Stable across retries (unlike a minute bucket), so a broker that
    # dedups on client order id rejects a duplicate close instead of
    # opening a reverse position.
    client_order_id = make_client_order_id(
        config_id=trade.config_id, symbol=trade.symbol,
        signal_id=str(trade.id), intent="EXIT",
        bar_ts="retry",
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


def _finalise_closed(trade, client, *, reason: str) -> None:
    """Mark the row CLOSED at the current mark and run the close hooks."""
    price = _mark_price(trade, client)
    trade.exit_price = price
    trade.pnl = _pnl(trade, price)
    trade.status = "CLOSED"
    trade.closed_at = timezone.now()
    trade.reason = ((trade.reason or "") + f" | closed:{reason}").strip()[:1000]
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


def _give_up(trade, error: str) -> None:
    """Terminal state after MAX_RETRY_ATTEMPTS — stop firing live orders."""
    trade.status = "ERROR"
    trade.reason = ((trade.reason or "")
                    + " | close-abandoned").strip()[:1000]
    trade.save(update_fields=["status", "reason"])
    try:
        from alerts.models import Notification
        Notification.objects.create(
            user=trade.config.user, notification_type="bot",
            title=f"⛔ Close abandoned: {trade.symbol}",
            body=(f"{trade.asset_class} trade #{trade.id} failed to close "
                  f"{MAX_RETRY_ATTEMPTS} times and is no longer being retried. "
                  f"Last error: {error[:160]}. Verify and close it manually "
                  f"at the broker."),
            url="/forensics/",
        )
    except Exception as e:
        logger.warning("close-abandoned alert failed for #%s: %s", trade.id, e)


def retry_trade_close(trade) -> bool:
    """Retry one CLOSE_PENDING trade. True when it ended CLOSED."""
    from bot_program.engine.broker_router import client_for_symbol

    client = client_for_symbol(trade.config.user, trade.symbol, trade.config)

    # If the broker says the position is already gone, the original close
    # (or a protective leg) did fill — finalise instead of sending another
    # order that would open a naked reverse position.
    if broker_still_holds(trade, client) is False:
        logger.info("close retry: broker no longer holds #%s (%s) — "
                    "finalising without a new order", trade.id, trade.symbol)
        _finalise_closed(trade, client, reason="RETRY_ALREADY_FLAT")
        return True

    try:
        _submit_close(trade, client)
    except Exception as e:
        attempts = _attempts(trade) + 1
        _record_attempt(trade, ok=False, error=str(e))
        trade.save(update_fields=["metadata"])
        logger.error("close retry #%s failed for trade %s (attempt %d): %s",
                     trade.id, trade.symbol, attempts, e)
        if attempts >= MAX_RETRY_ATTEMPTS:
            logger.error("close retry #%s abandoned after %d attempts",
                         trade.id, attempts)
            _give_up(trade, str(e))
        elif attempts % ALERT_AFTER_ATTEMPTS == 0:
            _alert_stranded(trade, attempts, str(e))
        return False

    _finalise_closed(trade, client, reason="RETRY")
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
