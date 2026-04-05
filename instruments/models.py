"""Instrument definitions — what Sauron Vision tracks."""
from django.db import models
from core.constants import AssetClass


class Instrument(models.Model):
    """A tradeable instrument: stock, forex pair, commodity, etc."""
    symbol = models.CharField(max_length=20, unique=True, db_index=True)
    name = models.CharField(max_length=200)
    asset_class = models.CharField(max_length=20, choices=AssetClass.CHOICES)
    exchange = models.CharField(max_length=50, blank=True)
    currency = models.CharField(max_length=10, default="USD")
    sector = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=50, blank=True)

    is_active = models.BooleanField(default=True)
    is_watchlist = models.BooleanField(default=False)

    trading_hours = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["asset_class", "symbol"]

    def __str__(self):
        return f"{self.symbol} ({self.get_asset_class_display()})"
