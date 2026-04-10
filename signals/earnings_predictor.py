"""Earnings reaction predictor — statistical model for post-earnings moves."""
import logging
import numpy as np

logger = logging.getLogger(__name__)


class EarningsPredictor:
    """Predict post-earnings price reactions using historical patterns."""

    def predict_reaction(self, symbol, eps_actual, eps_estimate, revenue_actual=None, revenue_estimate=None):
        """Predict likely price reaction to an earnings report.

        Returns dict with predicted move range, confidence, and historical context.
        """
        surprise_pct = ((eps_actual - eps_estimate) / abs(eps_estimate) * 100) if eps_estimate != 0 else 0

        revenue_surprise = 0
        if revenue_actual and revenue_estimate and revenue_estimate > 0:
            revenue_surprise = (revenue_actual - revenue_estimate) / revenue_estimate * 100

        # Get historical earnings reactions for this stock
        historical = self._get_historical_reactions(symbol)

        # Base prediction from surprise magnitude
        if surprise_pct > 10:
            predicted_move = {'low': 3, 'mid': 7, 'high': 15}
            direction = 'up'
        elif surprise_pct > 5:
            predicted_move = {'low': 1, 'mid': 4, 'high': 8}
            direction = 'up'
        elif surprise_pct > 0:
            predicted_move = {'low': 0, 'mid': 2, 'high': 5}
            direction = 'up'
        elif surprise_pct > -5:
            predicted_move = {'low': -5, 'mid': -2, 'high': 0}
            direction = 'down'
        elif surprise_pct > -10:
            predicted_move = {'low': -8, 'mid': -4, 'high': -1}
            direction = 'down'
        else:
            predicted_move = {'low': -15, 'mid': -7, 'high': -3}
            direction = 'down'

        # Adjust based on historical patterns
        avg_reaction = None
        if historical:
            avg_reaction = np.mean([h['reaction_pct'] for h in historical])
            vol = np.std([h['reaction_pct'] for h in historical])

            # If stock tends to move more than average, widen range
            if vol > 5:
                predicted_move = {k: v * 1.3 for k, v in predicted_move.items()}

        confidence = min(0.85, 0.5 + len(historical) * 0.03)

        return {
            'symbol': symbol,
            'eps_surprise_pct': round(surprise_pct, 2),
            'revenue_surprise_pct': round(revenue_surprise, 2),
            'predicted_direction': direction,
            'predicted_move_pct': {k: round(v, 2) for k, v in predicted_move.items()},
            'confidence': round(confidence, 3),
            'historical_reactions': historical[:5],
            'historical_avg_reaction': round(avg_reaction, 2) if avg_reaction is not None else None,
        }

    def _get_historical_reactions(self, symbol):
        """Get historical earnings reactions for a stock."""
        from market_data.models import PriceData
        from instruments.models import Instrument

        try:
            inst = Instrument.objects.get(symbol=symbol)
        except Instrument.DoesNotExist:
            return []

        # Look for large single-day moves (proxy for earnings days)
        from django.utils import timezone
        from datetime import timedelta

        cutoff = timezone.now() - timedelta(days=365*2)
        prices = list(PriceData.objects.filter(
            instrument=inst, timeframe='1d', timestamp__gte=cutoff
        ).order_by('timestamp').values('timestamp', 'open', 'close', 'volume'))

        if len(prices) < 20:
            return []

        reactions = []
        avg_volume = np.mean([float(p['volume']) for p in prices]) if prices else 1

        for i in range(1, len(prices)):
            prev_close = float(prices[i-1]['close'])
            if prev_close == 0:
                continue
            gap_pct = (float(prices[i]['open']) / prev_close - 1) * 100
            day_return = (float(prices[i]['close']) / prev_close - 1) * 100
            vol_ratio = float(prices[i]['volume']) / avg_volume if avg_volume > 0 else 1

            # Earnings days typically have large gaps and high volume
            if abs(gap_pct) > 3 and vol_ratio > 1.5:
                reactions.append({
                    'date': str(prices[i]['timestamp']),
                    'gap_pct': round(gap_pct, 2),
                    'reaction_pct': round(day_return, 2),
                    'volume_ratio': round(vol_ratio, 2),
                })

        return sorted(reactions, key=lambda x: x['date'], reverse=True)
