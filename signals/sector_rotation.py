"""Sector rotation model — track money flow between sectors."""
import logging
import numpy as np
from collections import defaultdict

logger = logging.getLogger(__name__)


class SectorRotationModel:
    """Track and predict sector rotation patterns."""

    # Typical business cycle sector order
    CYCLE_ORDER = [
        'Technology', 'Consumer Discretionary', 'Industrials',
        'Materials', 'Energy', 'Financial Services',
        'Consumer Staples', 'Healthcare', 'Utilities', 'Real Estate',
    ]

    def analyze(self, lookback_days=30):
        """Analyze current sector rotation.

        Returns dict with:
            sector_performance: dict of {sector: return_pct}
            rotation_direction: str (risk_on, risk_off, late_cycle, etc.)
            leading_sectors: list
            lagging_sectors: list
            suggested_rotation: list of {from, to, reason}
        """
        sector_returns = self._get_sector_returns(lookback_days)

        if not sector_returns:
            return {'error': 'insufficient sector data'}

        # Sort by performance
        sorted_sectors = sorted(sector_returns.items(), key=lambda x: x[1], reverse=True)
        leading = [s[0] for s in sorted_sectors[:3]]
        lagging = [s[0] for s in sorted_sectors[-3:]]

        # Detect rotation direction
        direction = self._detect_direction(sector_returns)

        # Momentum analysis
        momentum = self._momentum_analysis(lookback_days)

        # Suggest rotation trades
        suggestions = self._suggest_rotation(sector_returns, momentum)

        return {
            'sector_performance': {k: round(v, 4) for k, v in sector_returns.items()},
            'rotation_direction': direction,
            'leading_sectors': leading,
            'lagging_sectors': lagging,
            'momentum': momentum,
            'suggestions': suggestions,
            'lookback_days': lookback_days,
        }

    def _get_sector_returns(self, lookback_days):
        """Calculate sector returns over lookback period."""
        from instruments.models import Instrument
        from market_data.models import PriceData
        from django.utils import timezone
        from datetime import timedelta

        cutoff = timezone.now() - timedelta(days=lookback_days)
        sector_returns = defaultdict(list)

        instruments = Instrument.objects.filter(
            is_active=True, asset_class='stock', sector__isnull=False
        ).exclude(sector='')

        for inst in instruments:
            prices = list(PriceData.objects.filter(
                instrument=inst, timeframe='1d', timestamp__gte=cutoff
            ).order_by('timestamp').values_list('close', flat=True))

            if len(prices) >= 2:
                ret = (float(prices[-1]) / float(prices[0]) - 1)
                sector_returns[inst.sector].append(ret)

        # Average return per sector
        return {
            sector: np.mean(returns) if returns else 0
            for sector, returns in sector_returns.items()
        }

    def _detect_direction(self, sector_returns):
        """Detect rotation direction based on sector leadership."""
        if not sector_returns:
            return 'unknown'

        sorted_by_return = sorted(sector_returns.items(), key=lambda x: x[1], reverse=True)
        top_sectors = set(s[0] for s in sorted_by_return[:3])

        risk_on = {'Technology', 'Consumer Discretionary', 'Industrials', 'Financial Services'}
        risk_off = {'Consumer Staples', 'Healthcare', 'Utilities', 'Real Estate'}
        late_cycle = {'Energy', 'Materials', 'Industrials'}

        on_count = len(top_sectors & risk_on)
        off_count = len(top_sectors & risk_off)
        late_count = len(top_sectors & late_cycle)

        if on_count >= 2:
            return 'risk_on'
        elif off_count >= 2:
            return 'risk_off'
        elif late_count >= 2:
            return 'late_cycle'
        else:
            return 'transitioning'

    def _momentum_analysis(self, lookback_days):
        """Compare short-term vs long-term sector momentum."""
        short_returns = self._get_sector_returns(min(lookback_days, 5))
        long_returns = self._get_sector_returns(lookback_days)

        momentum = {}
        for sector in set(short_returns.keys()) | set(long_returns.keys()):
            short = short_returns.get(sector, 0)
            long = long_returns.get(sector, 0)

            if short > long and short > 0:
                momentum[sector] = 'accelerating'
            elif short < long and long > 0:
                momentum[sector] = 'decelerating'
            elif short > 0 and long < 0:
                momentum[sector] = 'reversing_up'
            elif short < 0 and long > 0:
                momentum[sector] = 'reversing_down'
            else:
                momentum[sector] = 'stable'

        return momentum

    def _suggest_rotation(self, returns, momentum):
        """Suggest sector rotation trades."""
        suggestions = []

        sorted_sectors = sorted(returns.items(), key=lambda x: x[1], reverse=True)

        for i, (sector, ret) in enumerate(sorted_sectors):
            mom = momentum.get(sector, 'stable')

            # Suggest rotating INTO sectors that are accelerating and leading
            if i < 3 and mom == 'accelerating':
                suggestions.append({
                    'action': 'overweight',
                    'sector': sector,
                    'reason': f"Leading sector with accelerating momentum (+{ret*100:.1f}%)",
                })

            # Suggest rotating OUT of sectors that are decelerating or reversing down
            if i >= len(sorted_sectors) - 3 and mom in ('decelerating', 'reversing_down'):
                suggestions.append({
                    'action': 'underweight',
                    'sector': sector,
                    'reason': f"Lagging sector with {mom} momentum ({ret*100:+.1f}%)",
                })

        return suggestions
