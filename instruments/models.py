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

    @property
    def has_page(self) -> bool:
        """True — a saved Instrument has a detail page that will load.

        The flag exists for the templates, and it is POSITIVE on this class
        rather than negative on the stand-in because Django resolves a
        missing attribute to False: a negative flag would silently be False
        on every real row too, and every working link would go dead at once.

        `portfolio.services._InstrumentShim` is the other side of it. When a
        position's symbol matches no row — a bot holding BTCUSDT while the
        table holds BTCUSD — services hands the template that shim instead,
        and `{% url 'instrument_detail' symbol %}` will happily build a URL
        for it, because a route only proves the STRING fits the pattern. It
        proves nothing about the row, and the symbol rendered as a live link
        straight to a 404.

        Unsaved instances answer False: nothing can navigate to a row that
        was never written.
        """
        return self.pk is not None

    def __str__(self):
        return f"{self.symbol} ({self.get_asset_class_display()})"
