"""THE VENUE MARK (2026-10-05): a real row is valued at its venue's own rate.

The operator bought WTI and silver at eToro and the positions page showed a
gain at the open. The row's entry was eToro's fill (the CFD's rate, off the
order's answer); the page marked it at the platform's own quote — for a
commodity Yahoo's front-month future or the spot, minutes old — and the basis
between the two rendered as P&L. The engine never had the problem: the
manage tick marks a REAL row at the venue's ticker (client_for_symbol ->
eToro's rates), so every stop and every care decision read the venue's
price. Only the pages and the book value read the LiveQuote.

Now the manage tick STAMPS the venue's mark on a real row each time it reads
one (metadata["venue_mark"]: price, at, source — the adapter's key), and
portfolio.services._trade_to_position prefers a stamp younger than MAX_AGE_S
over the LiveQuote for a real row (mark_source "venue"), falling back to the
quote ("quote") when the stamp is stale or absent. A paper row's quote IS its
venue, so it is never stamped. The positions page says which mark it shows.
The same print is not rewritten within REWRITE_AFTER_S. Never raises.
"""
import logging

from django.utils import timezone
from django.utils.dateparse import parse_datetime

logger = logging.getLogger(__name__)

#: A venue mark older than this is not preferred over the platform's quote.
MAX_AGE_S = 900
#: The same price is rewritten no more often than this (the tick's cadence
#: keeps the stamp fresh; a changed price is always written).
REWRITE_AFTER_S = 240


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def _when(s):
    if not s:
        return None
    try:
        return parse_datetime(str(s))
    except (TypeError, ValueError):
        return None


def stamp(trade, price, *, source="", now=None) -> bool:
    """Write the venue's mark on a REAL row (metadata["venue_mark"]), read
    fresh under a row lock so no other writer's keys are lost. True when
    written. A paper row, a bad price, or the same price written within
    REWRITE_AFTER_S: nothing."""
    try:
        if getattr(trade, "paper", True):
            return False
        p = _f(price)
        if p is None or p <= 0:
            return False
        now = now or timezone.now()
        prev = (getattr(trade, "metadata", None) or {}).get("venue_mark") or {}
        prev_at = _when(prev.get("at"))
        if (_f(prev.get("price")) == p and prev_at is not None
                and 0 <= (now - prev_at).total_seconds() < REWRITE_AFTER_S):
            return False
        from django.db import transaction

        from bot_program.asset_models import AssetBotTrade
        value = {"price": p, "at": now.isoformat(), "source": str(source or "")}
        with transaction.atomic():
            row = AssetBotTrade.objects.select_for_update().get(pk=trade.pk)
            meta = dict(row.metadata or {})
            meta["venue_mark"] = value
            row.metadata = meta
            row.save(update_fields=["metadata"])
        trade.metadata = meta
        return True
    except Exception as e:  # noqa: BLE001 — a mark not stamped is the quote
        logger.info("[venue mark] %s #%s not stamped: %s",
                    getattr(trade, "symbol", "?"), getattr(trade, "id", "?"), e)
        return False


def fresh(trade, *, now=None, max_age_s=MAX_AGE_S):
    """The venue's mark on `trade` while it is younger than `max_age_s`:
    {price, at, source, age_s} — or None (absent, unreadable, stale, or a
    paper row)."""
    try:
        if getattr(trade, "paper", True):
            return None
        vm = (getattr(trade, "metadata", None) or {}).get("venue_mark") or {}
        p = _f(vm.get("price"))
        at = _when(vm.get("at"))
        if p is None or p <= 0 or at is None:
            return None
        now = now or timezone.now()
        age = max(0.0, (now - at).total_seconds())
        if age > max_age_s:
            return None
        return {"price": p, "at": at, "source": str(vm.get("source") or ""),
                "age_s": age}
    except Exception:  # noqa: BLE001
        return None
