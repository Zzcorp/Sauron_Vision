"""Position sizing engine — Kelly criterion, volatility-based, and fixed risk."""
import numpy as np
import logging

logger = logging.getLogger(__name__)


class PositionSizer:
    """Calculate optimal position sizes."""

    def __init__(self, portfolio):
        self.portfolio = portfolio

    def kelly_criterion(self, win_rate, avg_win_pct, avg_loss_pct):
        """Kelly criterion position size.

        Returns fraction of capital to risk (0-1).
        Half-Kelly is commonly used for safety.
        """
        if avg_loss_pct == 0:
            return 0

        b = avg_win_pct / abs(avg_loss_pct)  # Win/loss ratio
        p = win_rate
        q = 1 - p

        kelly = (b * p - q) / b
        half_kelly = kelly / 2

        return {
            'full_kelly': round(max(0, min(kelly, 1)), 4),
            'half_kelly': round(max(0, min(half_kelly, 1)), 4),
            'recommended': round(max(0, min(half_kelly, 0.25)), 4),  # Cap at 25%
            'win_loss_ratio': round(b, 4),
        }

    def volatility_based(self, instrument, risk_pct=0.02, lookback_days=20):
        """Calculate position size based on volatility (ATR).

        risk_pct: max % of portfolio to risk on this trade
        """
        from market_data.models import PriceData
        from django.utils import timezone
        from datetime import timedelta

        cutoff = timezone.now() - timedelta(days=lookback_days + 10)
        prices = PriceData.objects.filter(
            instrument=instrument, timeframe='1d', timestamp__gte=cutoff
        ).order_by('timestamp').values('high', 'low', 'close')

        prices = list(prices)
        if len(prices) < lookback_days:
            return {'error': 'insufficient price data', 'position_size': 0}

        # Calculate ATR
        trs = []
        for i in range(1, len(prices)):
            h = float(prices[i]['high'])
            l = float(prices[i]['low'])
            pc = float(prices[i - 1]['close'])
            tr = max(h - l, abs(h - pc), abs(l - pc))
            trs.append(tr)

        atr = np.mean(trs[-lookback_days:])
        current_price = float(prices[-1]['close'])
        portfolio_value = float(self.portfolio.current_value)

        # Risk amount
        risk_amount = portfolio_value * risk_pct

        # Position size = risk_amount / ATR
        if atr > 0:
            shares = risk_amount / atr
            position_value = shares * current_price
            position_pct = position_value / portfolio_value
        else:
            shares = 0
            position_value = 0
            position_pct = 0

        # Apply portfolio limits
        max_position_pct = float(self.portfolio.max_single_position_pct) / 100
        if position_pct > max_position_pct:
            position_pct = max_position_pct
            position_value = portfolio_value * position_pct
            shares = position_value / current_price if current_price > 0 else 0

        return {
            'shares': round(shares, 4),
            'position_value': round(position_value, 2),
            'position_pct': round(position_pct * 100, 2),
            'atr': round(atr, 6),
            'current_price': current_price,
            'risk_amount': round(risk_amount, 2),
            'stop_loss_distance': round(atr, 6),
            'suggested_stop': round(current_price - atr, 6),
        }

    def correlation_aware_scale(self, candidate_instrument, lookback_days=90):
        """Return a 0..1 scale factor for sizing based on correlation to the open book.

        Reads `Portfolio.max_correlation_threshold` (default 0.7). If the candidate's
        peak absolute correlation to an existing position exceeds the threshold, the
        scale factor is reduced linearly down to a floor of 0.25 at correlation 1.0.

        Returns dict:
            {
                "scale": float in [0.25, 1.0],
                "max_corr": float | None,
                "peer": str | None,
                "threshold": float,
                "reason": str,
            }
        """
        from portfolio.correlation import max_correlation_to_open_book

        threshold = float(self.portfolio.max_correlation_threshold or 0.7)
        max_corr, peer = max_correlation_to_open_book(
            self.portfolio, candidate_instrument, lookback_days=lookback_days
        )

        if max_corr is None:
            return {"scale": 1.0, "max_corr": None, "peer": None,
                    "threshold": threshold, "reason": "no open positions or insufficient history"}

        abs_corr = abs(max_corr)
        if abs_corr <= threshold:
            return {"scale": 1.0, "max_corr": round(max_corr, 4), "peer": peer,
                    "threshold": threshold,
                    "reason": f"correlation {abs_corr:.2f} within threshold {threshold:.2f}"}

        # Linear scale from 1.0 at threshold → 0.25 at corr=1.0.
        excess = abs_corr - threshold
        room = max(1.0 - threshold, 1e-6)
        scale = max(0.25, 1.0 - 0.75 * (excess / room))
        return {
            "scale": round(scale, 4),
            "max_corr": round(max_corr, 4),
            "peer": peer,
            "threshold": threshold,
            "reason": f"correlation {abs_corr:.2f} exceeds threshold {threshold:.2f} "
                      f"(peer: {peer}) — scaling size to {scale:.0%}",
        }

    def fixed_risk(self, entry_price, stop_loss, risk_pct=0.02):
        """Calculate position size for a fixed risk amount.

        Given entry price and stop loss, calculate how many shares to buy
        so that if stopped out, you lose exactly risk_pct of portfolio.
        """
        portfolio_value = float(self.portfolio.current_value)
        risk_amount = portfolio_value * risk_pct
        risk_per_share = abs(float(entry_price) - float(stop_loss))

        if risk_per_share == 0:
            return {'error': 'stop loss equals entry price', 'shares': 0}

        shares = risk_amount / risk_per_share
        position_value = shares * float(entry_price)
        position_pct = position_value / portfolio_value if portfolio_value > 0 else 0

        # Apply limits
        max_pct = float(self.portfolio.max_single_position_pct) / 100
        if position_pct > max_pct:
            shares = (portfolio_value * max_pct) / float(entry_price)
            position_value = shares * float(entry_price)
            position_pct = max_pct

        return {
            'shares': round(shares, 4),
            'position_value': round(position_value, 2),
            'position_pct': round(position_pct * 100, 2),
            'risk_amount': round(risk_amount, 2),
            'risk_per_share': round(risk_per_share, 6),
            'max_loss_if_stopped': round(shares * risk_per_share, 2),
        }
