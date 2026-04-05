"""Technical indicator computed values."""
from django.db import models
from instruments.models import Instrument


class TechnicalIndicator(models.Model):
    """Computed technical indicator values per instrument/timeframe."""
    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name="technicals")
    timeframe = models.CharField(max_length=5)
    timestamp = models.DateTimeField()

    # Trend
    sma_20 = models.DecimalField(max_digits=20, decimal_places=8, null=True)
    sma_50 = models.DecimalField(max_digits=20, decimal_places=8, null=True)
    sma_200 = models.DecimalField(max_digits=20, decimal_places=8, null=True)
    ema_12 = models.DecimalField(max_digits=20, decimal_places=8, null=True)
    ema_26 = models.DecimalField(max_digits=20, decimal_places=8, null=True)

    # Momentum
    rsi_14 = models.FloatField(null=True)
    macd_line = models.FloatField(null=True)
    macd_signal = models.FloatField(null=True)
    macd_histogram = models.FloatField(null=True)
    stoch_k = models.FloatField(null=True)
    stoch_d = models.FloatField(null=True)

    # Volatility
    bollinger_upper = models.DecimalField(max_digits=20, decimal_places=8, null=True)
    bollinger_lower = models.DecimalField(max_digits=20, decimal_places=8, null=True)
    atr_14 = models.DecimalField(max_digits=20, decimal_places=8, null=True)

    # Volume
    obv = models.BigIntegerField(null=True)
    vwap = models.DecimalField(max_digits=20, decimal_places=8, null=True)

    class Meta:
        unique_together = ["instrument", "timeframe", "timestamp"]
        indexes = [
            models.Index(fields=["instrument", "timeframe", "-timestamp"]),
        ]
        ordering = ["-timestamp"]
