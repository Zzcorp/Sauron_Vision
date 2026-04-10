"""Celery tasks for strategies — gated."""
from celery import shared_task
from core.task_gate import guarded_task
import logging

logger = logging.getLogger(__name__)


@shared_task
@guarded_task("agent_strategy")
def suggest_rebalancing():
    """Tier 6: Weekly portfolio rebalancing suggestions."""
    from strategies.models import Strategy, StrategyAdjustment
    from strategies.engine import StrategyEngine
    from portfolio.services import get_or_create_default_portfolio
    from portfolio.models import Position

    logger.info("Generating rebalancing suggestions")

    portfolio = get_or_create_default_portfolio()
    open_positions = list(
        Position.objects.filter(
            portfolio=portfolio,
            closed_at__isnull=True,
        ).select_related("instrument")
    )

    # Calculate current exposure by asset class (as % of portfolio value)
    portfolio_value = float(portfolio.current_value) if portfolio.current_value else 0.0
    exposure_by_asset_class: dict[str, float] = {}
    if portfolio_value > 0:
        for pos in open_positions:
            asset_class = getattr(pos.instrument, "asset_class", "unknown") or "unknown"
            position_value = float(pos.current_price) * float(pos.quantity)
            exposure_by_asset_class[asset_class] = (
                exposure_by_asset_class.get(asset_class, 0.0) + position_value
            )
        exposure_by_asset_class = {
            k: round((v / portfolio_value) * 100, 2)
            for k, v in exposure_by_asset_class.items()
        }

    active_strategies = list(
        Strategy.objects.filter(status="active").prefetch_related("legs__instrument")
    )

    engine = StrategyEngine()
    created_adjustments = 0
    strategy_summaries = []

    for strategy in active_strategies:
        current_data = {
            "portfolio_value": portfolio_value,
            "exposure_by_asset_class": exposure_by_asset_class,
            "open_positions": [
                {
                    "instrument_id": pos.instrument_id,
                    "symbol": pos.instrument.symbol,
                    "direction": pos.direction,
                    "quantity": float(pos.quantity),
                    "entry_price": float(pos.entry_price),
                    "current_price": float(pos.current_price),
                    "unrealized_pnl_pct": pos.unrealized_pnl_pct,
                }
                for pos in open_positions
            ],
        }

        result = engine.suggest_adjustments(strategy, current_data)
        adjustments = result.get("adjustments", [])

        for adj in adjustments:
            StrategyAdjustment.objects.create(
                strategy=strategy,
                adjustment_type=adj.get("type", "review"),
                reason=adj.get("reason", ""),
                details=adj.get("details", {}),
                applied=False,
            )
            created_adjustments += 1

        strategy_summaries.append({
            "strategy": strategy.name,
            "n_adjustments": len(adjustments),
            "note": result.get("note", ""),
        })

    # Flag overexposed asset classes regardless of individual strategies
    max_sector_pct = float(portfolio.max_sector_exposure_pct) if portfolio.max_sector_exposure_pct else 30.0
    overexposed = {
        asset_class: pct
        for asset_class, pct in exposure_by_asset_class.items()
        if pct > max_sector_pct
    }
    if overexposed and active_strategies:
        # Attach a portfolio-level overexposure adjustment to the first active strategy
        anchor = active_strategies[0]
        for asset_class, pct in overexposed.items():
            StrategyAdjustment.objects.create(
                strategy=anchor,
                adjustment_type="reduce_exposure",
                reason=(
                    f"Portfolio overexposed to {asset_class}: "
                    f"{pct:.1f}% vs {max_sector_pct:.1f}% limit"
                ),
                details={
                    "asset_class": asset_class,
                    "current_exposure_pct": pct,
                    "limit_pct": max_sector_pct,
                },
                applied=False,
            )
            created_adjustments += 1

    logger.info(
        "Rebalancing complete: %d strategies reviewed, %d adjustments created",
        len(active_strategies),
        created_adjustments,
    )

    return {
        "status": "ok",
        "strategies_reviewed": len(active_strategies),
        "adjustments_created": created_adjustments,
        "exposure_by_asset_class": exposure_by_asset_class,
        "overexposed_asset_classes": overexposed,
        "strategy_summaries": strategy_summaries,
    }
