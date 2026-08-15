"""Celery tasks for portfolio — gated."""
from celery import shared_task
from core.task_gate import guarded_task
import logging

logger = logging.getLogger(__name__)

# A position mark accepts data up to a day old: this runs hourly for
# valuation, not for stop management, so "the freshest print we have" beats
# "nothing" — but a weeks-dead feed must not keep repainting the same price.
MARK_MAX_AGE_HOURS = 24


def _mark_for(instrument):
    """Freshest usable price for an instrument, or None to leave the mark."""
    from datetime import timedelta
    from django.utils import timezone
    from market_data.models import LiveQuote, PriceData

    cutoff = timezone.now() - timedelta(hours=MARK_MAX_AGE_HOURS)
    try:
        lq = LiveQuote.objects.filter(instrument=instrument).first()
        if lq and lq.last and lq.updated_at >= cutoff:
            return lq.last
    except Exception:
        pass
    try:
        pd = (PriceData.objects
              .filter(instrument=instrument, timestamp__gte=cutoff)
              .order_by("-timestamp").first())
        if pd:
            return pd.close
    except Exception:
        pass
    return None


def mark_positions_to_market(positions) -> int:
    """Refresh current_price + unrealized P&L on open positions. Returns the
    number of rows marked.

    Position.unrealized_pnl had a writer NOBODY scheduled (the manual eToro
    sync) and a model default of 0 — so every dashboard that summed it
    rendered +0.00 forever, and core/context_processors.py grew a parallel
    AssetBotTrade path just to avoid it. The sign convention is the one the
    closed-trade recompute paths already use: (mark - entry) * qty, negated
    for direction="short".
    """
    marked = 0
    for pos in positions:
        mark = _mark_for(pos.instrument) if pos.instrument else None
        if mark is None:
            continue
        entry = pos.entry_price or 0
        pnl = (mark - entry) * pos.quantity
        if (pos.direction or "").lower() == "short":
            pnl = -pnl
        pos.current_price = mark
        pos.unrealized_pnl = pnl
        pos.unrealized_pnl_pct = (
            float((mark - entry) / entry * 100) if entry else 0.0)
        if (pos.direction or "").lower() == "short":
            pos.unrealized_pnl_pct = -pos.unrealized_pnl_pct
        pos.save(update_fields=["current_price", "unrealized_pnl",
                                "unrealized_pnl_pct"])
        marked += 1
    return marked


@shared_task
@guarded_task("pipeline_exposure")
def recalculate_exposure():
    """Tier 3: mark open positions to market, then recalculate exposure."""
    logger.info("Recalculating portfolio exposure")

    from portfolio.services import get_or_create_default_portfolio
    from portfolio.models import Position
    from decimal import Decimal

    portfolio = get_or_create_default_portfolio()
    positions = Position.objects.filter(
        portfolio=portfolio, closed_at__isnull=True
    ).select_related("instrument")

    # Mark first, so the exposure sums below read today's prices rather
    # than whatever the row was created with.
    marked = mark_positions_to_market(positions)

    exposure_by_asset_class = {}
    exposure_by_sector = {}
    exposure_by_currency = {}
    total_position_value = Decimal("0")

    for pos in positions:
        value = pos.quantity * pos.current_price
        total_position_value += value

        # Asset class
        asset_class = pos.instrument.asset_class if pos.instrument else "unknown"
        exposure_by_asset_class[asset_class] = float(
            Decimal(str(exposure_by_asset_class.get(asset_class, 0))) + value
        )

        # Sector
        sector = (pos.instrument.sector or "unknown") if pos.instrument else "unknown"
        exposure_by_sector[sector] = float(
            Decimal(str(exposure_by_sector.get(sector, 0))) + value
        )

        # Currency
        currency = (pos.instrument.currency or "USD") if pos.instrument else "USD"
        exposure_by_currency[currency] = float(
            Decimal(str(exposure_by_currency.get(currency, 0))) + value
        )

    # Update portfolio current_value = cash + positions
    portfolio.current_value = portfolio.cash_available + total_position_value
    portfolio.save(update_fields=["current_value", "updated_at"])

    logger.info(
        "Exposure recalculated: total_value=%.2f positions=%.2f cash=%.2f",
        float(portfolio.current_value),
        float(total_position_value),
        float(portfolio.cash_available),
    )

    # "marked" is deliberately NOT a task-gate count key: a day with zero
    # open positions is a healthy no-op, not "ran and produced nothing".
    return {
        "status": "ok",
        "portfolio_id": portfolio.id,
        "current_value": float(portfolio.current_value),
        "cash": float(portfolio.cash_available),
        "position_count": positions.count(),
        "marked": marked,
        "exposure_by_asset_class": exposure_by_asset_class,
        "exposure_by_sector": exposure_by_sector,
        "exposure_by_currency": exposure_by_currency,
    }


@shared_task
@guarded_task("pipeline_snapshot")
def create_daily_snapshot():
    """Tier 5: Create end-of-day snapshot."""
    logger.info("Creating daily portfolio snapshot")

    from portfolio.services import get_or_create_default_portfolio
    from portfolio.models import Position, PortfolioSnapshot
    from decimal import Decimal
    from django.utils import timezone
    from datetime import timedelta

    portfolio = get_or_create_default_portfolio()
    today = timezone.now().date()
    yesterday = today - timedelta(days=1)

    # Get all open positions
    positions = Position.objects.filter(
        portfolio=portfolio, closed_at__isnull=True
    ).select_related("instrument")

    # Calculate today's total position value
    total_position_value = sum(
        float(p.quantity * p.current_price) for p in positions
    )
    total_value = float(portfolio.cash_available) + total_position_value

    # Update portfolio current_value
    portfolio.current_value = Decimal(str(total_value))
    portfolio.save(update_fields=["current_value", "updated_at"])

    # Retrieve yesterday's snapshot for daily P&L comparison
    try:
        yesterday_snap = PortfolioSnapshot.objects.get(
            portfolio=portfolio, date=yesterday
        )
        prev_value = float(yesterday_snap.total_value)
    except PortfolioSnapshot.DoesNotExist:
        yesterday_snap = None
        prev_value = float(portfolio.initial_capital)

    daily_pnl = total_value - prev_value
    daily_pnl_pct = (daily_pnl / prev_value * 100) if prev_value != 0 else 0.0

    # Cumulative P&L vs initial capital
    initial = float(portfolio.initial_capital)
    cumulative_pnl_pct = ((total_value - initial) / initial * 100) if initial != 0 else 0.0

    # Max drawdown from all historical snapshots
    all_values = list(
        PortfolioSnapshot.objects.filter(portfolio=portfolio)
        .order_by("date")
        .values_list("total_value", flat=True)
    )
    all_values_f = [float(v) for v in all_values] + [total_value]

    peak = all_values_f[0]
    max_drawdown = 0.0
    for v in all_values_f:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (v - peak) / peak * 100
            if dd < max_drawdown:
                max_drawdown = dd

    # Exposure dicts
    exposure_by_asset_class = {}
    exposure_by_sector = {}
    exposure_by_currency = {}

    for pos in positions:
        value = float(pos.quantity * pos.current_price)

        asset_class = pos.instrument.asset_class if pos.instrument else "unknown"
        exposure_by_asset_class[asset_class] = (
            exposure_by_asset_class.get(asset_class, 0) + value
        )

        sector = (pos.instrument.sector or "unknown") if pos.instrument else "unknown"
        exposure_by_sector[sector] = exposure_by_sector.get(sector, 0) + value

        currency = (pos.instrument.currency or "USD") if pos.instrument else "USD"
        exposure_by_currency[currency] = exposure_by_currency.get(currency, 0) + value

    # Phase-2 addition: compute the correlation matrix across open positions.
    # Best-effort: a degenerate matrix never blocks the snapshot from being written.
    try:
        from portfolio.correlation import portfolio_correlation
        cm = portfolio_correlation(portfolio)
        correlation_matrix = cm.to_dict()
    except Exception as e:
        logger.warning("correlation matrix computation failed: %s — saving empty", e)
        correlation_matrix = {}

    # Create or update the snapshot for today
    snap, created = PortfolioSnapshot.objects.update_or_create(
        portfolio=portfolio,
        date=today,
        defaults={
            "total_value": Decimal(str(round(total_value, 2))),
            "cash": portfolio.cash_available,
            "daily_pnl": Decimal(str(round(daily_pnl, 2))),
            "daily_pnl_pct": round(daily_pnl_pct, 4),
            "cumulative_pnl_pct": round(cumulative_pnl_pct, 4),
            "max_drawdown": round(max_drawdown, 4),
            "sharpe_ratio": None,
            "exposure_by_asset_class": exposure_by_asset_class,
            "exposure_by_sector": exposure_by_sector,
            "exposure_by_currency": exposure_by_currency,
            "correlation_matrix": correlation_matrix,
        },
    )

    action = "created" if created else "updated"
    logger.info(
        "Daily snapshot %s for %s: value=%.2f daily_pnl=%.2f cumulative=%.4f%%",
        action, today, total_value, daily_pnl, cumulative_pnl_pct,
    )

    return {
        "status": "ok",
        "date": str(today),
        "snapshot_id": snap.id,
        "action": action,
        "total_value": round(total_value, 2),
        "cash": float(portfolio.cash_available),
        "daily_pnl": round(daily_pnl, 2),
        "daily_pnl_pct": round(daily_pnl_pct, 4),
        "cumulative_pnl_pct": round(cumulative_pnl_pct, 4),
        "max_drawdown": round(max_drawdown, 4),
        "open_positions": positions.count(),
        "exposure_by_asset_class": exposure_by_asset_class,
        "exposure_by_sector": exposure_by_sector,
        "exposure_by_currency": exposure_by_currency,
    }
