"""Celery tasks for portfolio — gated."""
from celery import shared_task
from core.task_gate import guarded_task
import logging

logger = logging.getLogger(__name__)


@shared_task
@guarded_task("pipeline_exposure")
def recalculate_exposure():
    """Tier 3: Recalculate portfolio exposure."""
    logger.info("Recalculating portfolio exposure")

    from portfolio.services import get_or_create_default_portfolio
    from portfolio.models import Position
    from decimal import Decimal

    portfolio = get_or_create_default_portfolio()
    positions = Position.objects.filter(
        portfolio=portfolio, closed_at__isnull=True
    ).select_related("instrument")

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

    return {
        "status": "ok",
        "portfolio_id": portfolio.id,
        "current_value": float(portfolio.current_value),
        "cash": float(portfolio.cash_available),
        "position_count": positions.count(),
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
            "correlation_matrix": {},
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
