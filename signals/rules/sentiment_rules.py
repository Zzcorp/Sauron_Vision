"""Sentiment-based signal rules: mention velocity z-score."""
from datetime import timedelta
from django.utils import timezone


class SentimentVelocityRule:
    name = "sentiment_velocity_spike"
    signal_type = "sentiment"

    def evaluate(self, instrument):
        """Detect abnormal mention-velocity vs 7-day baseline.

        Tolerant to schema differences across SocialPost / Mention models.
        Returns None silently if the relevant tables don't exist.
        """
        symbol = getattr(instrument, "symbol", None) or getattr(instrument, "ticker", None)
        if not symbol:
            return None
        try:
            from scraping.models import SocialPost  # may not exist in all installs
        except Exception:
            return None

        now = timezone.now()
        try:
            recent_count = SocialPost.objects.filter(
                created_at__gte=now - timedelta(hours=1),
                content__icontains=symbol,
            ).count()
            baseline = SocialPost.objects.filter(
                created_at__gte=now - timedelta(days=7),
                created_at__lt=now - timedelta(hours=1),
                content__icontains=symbol,
            ).count()
        except Exception:
            return None

        baseline_per_hour = baseline / (7 * 24) if baseline else 0
        if baseline_per_hour < 1:
            return None
        z = (recent_count - baseline_per_hour) / max(baseline_per_hour, 1)
        if z < 3:
            return None

        return {
            "symbol": symbol,
            "rule": self.name,
            "direction": "LONG",
            "score": min(0.7, 0.3 + z * 0.05),
            "headline": f"{symbol} · Mention velocity spike {z:.1f}x baseline",
            "thesis": (
                f"Social mentions of {symbol} running {z:.1f}x normal in the last hour."
                " Crowd attention surge — contrarian-aware long bias short term."
            ),
        }


def get_rules():
    return [SentimentVelocityRule()]
