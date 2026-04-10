"""Composite sentiment index — combines Reddit, StockTwits, news into a proprietary index."""
import logging
from django.utils import timezone
from datetime import timedelta

logger = logging.getLogger(__name__)


class SentimentIndex:
    """Build and maintain a composite market sentiment index."""

    WEIGHTS = {
        'reddit': 0.25,
        'stocktwits': 0.25,
        'news': 0.30,
        'options_flow': 0.20,
    }

    def calculate(self, instrument=None, lookback_hours=24):
        """Calculate composite sentiment index.

        Returns dict with:
            composite_score: float -1 to 1 (-1=extreme fear, 1=extreme greed)
            components: dict with per-source scores
            signal: str (extreme_fear, fear, neutral, greed, extreme_greed)
            breadth: int (number of sources contributing)
        """
        cutoff = timezone.now() - timedelta(hours=lookback_hours)
        components = {}

        # Reddit/StockTwits sentiment
        social_score = self._social_sentiment(instrument, cutoff)
        if social_score is not None:
            components['social'] = social_score

        # News sentiment
        news_score = self._news_sentiment(instrument, cutoff)
        if news_score is not None:
            components['news'] = news_score

        # Options flow sentiment
        flow_score = self._options_flow_sentiment(instrument, cutoff)
        if flow_score is not None:
            components['options_flow'] = flow_score

        if not components:
            return {
                'composite_score': 0,
                'components': {},
                'signal': 'neutral',
                'breadth': 0,
            }

        # Weighted average
        total_weight = sum(self.WEIGHTS.get(k, 0.25) for k in components)
        composite = sum(
            score * self.WEIGHTS.get(k, 0.25) / total_weight
            for k, score in components.items()
        )

        # Classify signal
        if composite <= -0.6:
            signal = 'extreme_fear'
        elif composite <= -0.2:
            signal = 'fear'
        elif composite <= 0.2:
            signal = 'neutral'
        elif composite <= 0.6:
            signal = 'greed'
        else:
            signal = 'extreme_greed'

        return {
            'composite_score': round(composite, 4),
            'components': {k: round(v, 4) for k, v in components.items()},
            'signal': signal,
            'breadth': len(components),
            'instrument': instrument.symbol if instrument else 'market',
        }

    def _social_sentiment(self, instrument, cutoff):
        """Get social media sentiment score (-1 to 1)."""
        from scraping.models import SentimentSnapshot

        qs = SentimentSnapshot.objects.filter(timestamp__gte=cutoff)
        if instrument:
            qs = qs.filter(instrument=instrument)

        snapshots = list(qs.values('composite_score', 'volume'))
        if not snapshots:
            return None

        # Volume-weighted average
        total_volume = sum(s['volume'] for s in snapshots) or 1
        weighted = sum(s['composite_score'] * s['volume'] for s in snapshots) / total_volume
        return max(-1, min(1, weighted))

    def _news_sentiment(self, instrument, cutoff):
        """Get news sentiment score (-1 to 1)."""
        from scraping.models import NewsArticle

        qs = NewsArticle.objects.filter(
            ai_processed_at__isnull=False,
            published_at__gte=cutoff,
        )
        if instrument:
            qs = qs.filter(ai_affected_instruments=instrument)

        scores = list(qs.values_list('ai_sentiment_score', flat=True))
        if not scores:
            return None

        # Filter None values
        scores = [s for s in scores if s is not None]
        if not scores:
            return None

        avg = sum(scores) / len(scores)
        return max(-1, min(1, avg))

    def _options_flow_sentiment(self, instrument, cutoff):
        """Get options flow sentiment score (-1 to 1)."""
        from scraping.models import OptionsFlow

        qs = OptionsFlow.objects.filter(timestamp__gte=cutoff)
        if instrument:
            qs = qs.filter(instrument=instrument)

        flows = list(qs.values('contract_type', 'volume', 'premium', 'is_unusual'))
        if not flows:
            return None

        call_volume = sum(f['volume'] for f in flows if f['contract_type'] == 'CALL')
        put_volume = sum(f['volume'] for f in flows if f['contract_type'] == 'PUT')
        total = call_volume + put_volume

        if total == 0:
            return None

        # Put/call ratio → sentiment (-1 to 1)
        pcr = put_volume / total  # 0 = all calls, 1 = all puts
        # Invert: more calls = bullish
        score = 1 - 2 * pcr

        # Boost if unusual activity
        unusual_count = sum(1 for f in flows if f['is_unusual'])
        if unusual_count > 5:
            score *= 1.2

        return max(-1, min(1, score))
