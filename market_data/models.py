"""Market data models — prices, quotes, economic events, macro data."""
from django.db import models
from instruments.models import Instrument
from core.constants import Timeframe


class PriceData(models.Model):
    """OHLCV price bars — the core market data table."""
    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name="prices")
    timeframe = models.CharField(max_length=5, choices=Timeframe.CHOICES)
    timestamp = models.DateTimeField()
    open = models.DecimalField(max_digits=20, decimal_places=8)
    high = models.DecimalField(max_digits=20, decimal_places=8)
    low = models.DecimalField(max_digits=20, decimal_places=8)
    close = models.DecimalField(max_digits=20, decimal_places=8)
    volume = models.BigIntegerField(default=0)
    source = models.CharField(max_length=50)

    class Meta:
        unique_together = ["instrument", "timeframe", "timestamp"]
        indexes = [
            models.Index(fields=["instrument", "timeframe", "-timestamp"]),
        ]
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.instrument.symbol} {self.timeframe} {self.timestamp}"


class LiveQuote(models.Model):
    """Latest real-time quote — overwritten on each update."""
    instrument = models.OneToOneField(Instrument, on_delete=models.CASCADE, related_name="live_quote")
    bid = models.DecimalField(max_digits=20, decimal_places=8, null=True)
    ask = models.DecimalField(max_digits=20, decimal_places=8, null=True)
    last = models.DecimalField(max_digits=20, decimal_places=8)
    change_pct = models.DecimalField(max_digits=8, decimal_places=4, default=0)
    volume = models.BigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)
    source = models.CharField(max_length=50)

    def __str__(self):
        return f"{self.instrument.symbol}: {self.last}"


class EconomicEvent(models.Model):
    """Economic calendar events."""
    title = models.CharField(max_length=300)
    country = models.CharField(max_length=50)
    datetime = models.DateTimeField()
    impact = models.CharField(max_length=10)
    actual = models.CharField(max_length=50, blank=True)
    forecast = models.CharField(max_length=50, blank=True)
    previous = models.CharField(max_length=50, blank=True)
    currency_affected = models.CharField(max_length=10, blank=True)
    source = models.CharField(max_length=50)

    class Meta:
        ordering = ["datetime"]

    def __str__(self):
        return f"[{self.impact.upper()}] {self.title} ({self.country})"


class MacroIndicator(models.Model):
    """FRED & macro data series definitions."""
    series_id = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=100)
    frequency = models.CharField(max_length=20)
    last_value = models.DecimalField(max_digits=20, decimal_places=6, null=True)
    last_date = models.DateField(null=True)
    metadata = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"{self.series_id}: {self.name}"


class MacroObservation(models.Model):
    """Individual macro data observations."""
    indicator = models.ForeignKey(MacroIndicator, on_delete=models.CASCADE, related_name="observations")
    date = models.DateField()
    value = models.DecimalField(max_digits=20, decimal_places=6)

    class Meta:
        unique_together = ["indicator", "date"]
        ordering = ["-date"]
