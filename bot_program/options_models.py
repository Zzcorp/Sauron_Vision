"""Phase-14 options models.

`OptionContract` represents a specific option (one (underlying, strike, expiry,
right) tuple). The bot looks up or creates these on the fly when scanning a
chain; admin can pre-seed contracts via the dashboard if desired.

Greeks + IV are cached on the row and refreshed on each chain query — the
freshness is best-effort, not guaranteed real-time.
"""
from django.db import models

from instruments.models import Instrument


class OptionContract(models.Model):
    """One specific option contract."""

    RIGHT_CHOICES = [("C", "Call"), ("P", "Put")]

    underlying = models.ForeignKey(
        Instrument, on_delete=models.CASCADE, related_name="option_contracts",
    )
    # Symbol is OCC-style or broker-specific (e.g. "AAPL  240315C00150000").
    # We don't enforce a particular format — broker adapter normalises as needed.
    symbol = models.CharField(max_length=64, blank=True, db_index=True)

    strike = models.DecimalField(max_digits=14, decimal_places=4)
    expiry = models.DateField(db_index=True)
    right = models.CharField(max_length=1, choices=RIGHT_CHOICES)
    multiplier = models.IntegerField(default=100)

    # Cached pricing + Greeks (refreshed from broker on each chain query).
    last_price = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    bid = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    ask = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    iv = models.FloatField(null=True, blank=True, help_text="Implied volatility, decimal (0.30 = 30%).")

    delta = models.FloatField(null=True, blank=True)
    gamma = models.FloatField(null=True, blank=True)
    theta = models.FloatField(null=True, blank=True)
    vega = models.FloatField(null=True, blank=True)

    open_interest = models.IntegerField(default=0)
    volume = models.IntegerField(default=0)

    last_updated = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["underlying", "expiry", "strike", "right"]
        unique_together = [("underlying", "strike", "expiry", "right")]
        indexes = [
            models.Index(fields=["underlying", "expiry"]),
            models.Index(fields=["expiry", "right"]),
        ]

    def __str__(self):
        return (f"{self.underlying.symbol} "
                f"{self.expiry.strftime('%Y-%m-%d')} "
                f"{self.strike} {self.right}")

    @property
    def is_call(self) -> bool:
        return self.right == "C"

    @property
    def is_put(self) -> bool:
        return self.right == "P"
