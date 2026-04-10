"""Strategy engine — builds strategies from signals + portfolio context."""
import logging

logger = logging.getLogger(__name__)


class StrategyEngine:
    """Builds and manages trading strategies from signals + portfolio state."""

    def build_strategy_from_signals(self, signals, portfolio=None):
        """Group signals by direction + asset class, propose a strategy.

        Returns a dict suitable for creating a Strategy row.
        """
        if not signals:
            return None
        long_signals = [s for s in signals if getattr(s, "direction", "") in ("LONG", "long")]
        short_signals = [s for s in signals if getattr(s, "direction", "") in ("SHORT", "short")]

        if len(long_signals) > len(short_signals):
            primary_dir = "long"
            primary = long_signals
        elif short_signals:
            primary_dir = "short"
            primary = short_signals
        else:
            return None

        avg_score = sum(float(getattr(s, "score", 0) or 0) for s in primary) / len(primary)
        symbols = list({getattr(s, "instrument", None) and s.instrument.symbol for s in primary if getattr(s, "instrument", None)})

        return {
            "name": f"Composite {primary_dir} on {', '.join(symbols[:3]) or 'mixed'}",
            "description": f"Built from {len(primary)} aligned signals.",
            "direction": primary_dir,
            "instruments": symbols,
            "confidence": round(avg_score, 3),
            "n_signals": len(primary),
            "time_horizon": "swing",
        }

    def evaluate_strategy_risk(self, strategy, portfolio=None):
        """Check exposure budget vs proposed allocation."""
        try:
            allocation = float(getattr(strategy, "max_portfolio_allocation_pct", 0))
        except (ValueError, TypeError):
            allocation = 0.0
        if allocation > 25:
            return False, "allocation exceeds 25% single-strategy cap"
        return True, "ok"

    def suggest_adjustments(self, strategy, current_data=None):
        """Suggest stop tightening / partial exits based on current data.

        Args:
            strategy: Strategy model instance (must have prefetched legs).
            current_data: optional dict with keys such as:
                - "portfolio_value" (float)
                - "exposure_by_asset_class" (dict[str, float])
                - "open_positions" (list of position dicts)

        Returns:
            {"adjustments": [...], "note": "..."}
            Each adjustment: {"leg": symbol, "type": str, "reason": str, "details": dict}
        """
        from django.utils import timezone

        # Time-horizon overstay thresholds (in days)
        HORIZON_MAX_DAYS = {
            "scalp": 1,
            "intraday": 2,
            "swing": 15,
            "position": 9999,  # no hard limit for position trades
        }

        adjustments = []
        legs = list(strategy.legs.select_related("instrument").all())

        if not legs:
            return {"adjustments": [], "note": "strategy has no legs"}

        now = timezone.now()

        for leg in legs:
            symbol = leg.instrument.symbol if leg.instrument else "unknown"

            if leg.is_entered:
                # ── Entered leg: price-based checks ──────────────────────────
                entry = float(leg.entry_price) if leg.entry_price is not None else None
                stop = float(leg.stop_loss) if leg.stop_loss is not None else None
                target = float(leg.take_profit) if leg.take_profit is not None else None
                current = float(leg.current_price) if leg.current_price is not None else None

                if entry is None or current is None:
                    continue  # not enough price data

                # P&L % from entry (direction-aware)
                if leg.action == "short":
                    pnl_pct = ((entry - current) / entry) * 100
                else:
                    pnl_pct = ((current - entry) / entry) * 100

                # 1. Approaching stop-loss (within 2% of being stopped out)
                if stop is not None:
                    if leg.action == "short":
                        distance_to_stop_pct = ((stop - current) / current) * 100
                    else:
                        distance_to_stop_pct = ((current - stop) / current) * 100

                    if 0 <= distance_to_stop_pct <= 2.0:
                        adjustments.append({
                            "leg": symbol,
                            "type": "tighten_stop_or_exit",
                            "reason": (
                                f"{symbol} is within {distance_to_stop_pct:.2f}% of its stop-loss. "
                                "Consider tightening stop or exiting to protect capital."
                            ),
                            "details": {
                                "action": leg.action,
                                "entry_price": entry,
                                "current_price": current,
                                "stop_loss": stop,
                                "distance_to_stop_pct": round(distance_to_stop_pct, 3),
                                "pnl_pct": round(pnl_pct, 3),
                            },
                        })

                # 2. Past 50% of the way to target — suggest trailing stop / partial exit
                if target is not None and stop is not None:
                    if leg.action == "short":
                        total_move = entry - target
                        captured = entry - current
                    else:
                        total_move = target - entry
                        captured = current - entry

                    if total_move > 0:
                        progress_pct = (captured / total_move) * 100
                        if progress_pct >= 50:
                            adjustments.append({
                                "leg": symbol,
                                "type": "trailing_stop_or_partial_exit",
                                "reason": (
                                    f"{symbol} has reached {progress_pct:.1f}% of its profit target. "
                                    "Consider a trailing stop or partial exit to lock in gains."
                                ),
                                "details": {
                                    "action": leg.action,
                                    "entry_price": entry,
                                    "current_price": current,
                                    "take_profit": target,
                                    "progress_to_target_pct": round(progress_pct, 2),
                                    "pnl_pct": round(pnl_pct, 3),
                                },
                            })

                # 3. Position open too long for its time-horizon
                if leg.entered_at is not None:
                    days_open = (now - leg.entered_at).total_seconds() / 86400
                    max_days = HORIZON_MAX_DAYS.get(strategy.time_horizon, 9999)
                    if days_open > max_days:
                        adjustments.append({
                            "leg": symbol,
                            "type": "time_horizon_exceeded",
                            "reason": (
                                f"{symbol} has been open for {days_open:.1f} days, exceeding the "
                                f"{strategy.time_horizon} horizon limit of {max_days} day(s). "
                                "Review whether the trade thesis still holds."
                            ),
                            "details": {
                                "action": leg.action,
                                "days_open": round(days_open, 1),
                                "max_days_for_horizon": max_days,
                                "time_horizon": strategy.time_horizon,
                                "pnl_pct": round(pnl_pct, 3),
                            },
                        })

            else:
                # ── Not-yet-entered leg: check entry conditions ───────────────
                if strategy.status != "active":
                    continue

                entry_conditions = leg.entry_conditions or {}
                if not entry_conditions:
                    continue

                # Pull live price from current_data if available
                market_price = None
                if current_data:
                    for pos in current_data.get("open_positions", []):
                        if pos.get("symbol") == (leg.instrument.symbol if leg.instrument else None):
                            market_price = pos.get("current_price")
                            break

                # Check a simple price-trigger condition if present
                trigger_price = entry_conditions.get("price_below") or entry_conditions.get("price_above")
                condition_met = False
                condition_detail = {}

                if market_price is not None and trigger_price is not None:
                    trigger_price = float(trigger_price)
                    market_price = float(market_price)
                    if "price_below" in entry_conditions and market_price <= trigger_price:
                        condition_met = True
                        condition_detail = {
                            "condition": "price_below",
                            "trigger": trigger_price,
                            "market_price": market_price,
                        }
                    elif "price_above" in entry_conditions and market_price >= trigger_price:
                        condition_met = True
                        condition_detail = {
                            "condition": "price_above",
                            "trigger": trigger_price,
                            "market_price": market_price,
                        }

                if condition_met:
                    adjustments.append({
                        "leg": symbol,
                        "type": "entry_condition_met",
                        "reason": (
                            f"Entry condition for {symbol} ({leg.action}) appears to be met. "
                            "Consider opening this leg."
                        ),
                        "details": {
                            "action": leg.action,
                            "entry_conditions": entry_conditions,
                            **condition_detail,
                        },
                    })

        if not adjustments:
            note = "all legs within normal parameters, no adjustments needed"
        else:
            note = f"{len(adjustments)} adjustment(s) suggested across {len(legs)} leg(s)"

        return {"adjustments": adjustments, "note": note}
