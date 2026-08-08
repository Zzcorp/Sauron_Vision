"""Phase-27 tax-lot accounting models.

A `TaxLot` is created for every long entry (BUY-side AssetBotTrade open).
When the trade closes, `close_lots_for(trade)` walks the user's open lots
in their preferred order (FIFO / LIFO / HIFO) and creates one or more
`TaxLotConsumption` rows, each carrying the realised gain for that slice.

This decouples cost-basis bookkeeping from individual trade rows, which is
what tax software (and humans filling out Form 8949) actually need:
"acquired date, sold date, holding period, cost basis, proceeds, gain/loss."

v1 limitations (documented):
  - Long trades only (BUY-side opens; closes consume). Short trades skipped.
  - No wash-sale detection.
  - Each AssetBotTrade BUY → CLOSE cycle creates exactly one lot + one
    consumption (since bot trades aren't multi-lot averaged in practice).
"""
from decimal import Decimal

from django.conf import settings
from django.db import models


class TaxLot(models.Model):
    """One long-side entry that may be consumed across one or more sales."""

    LOT_METHOD_CHOICES = [
        ("FIFO", "First In, First Out"),
        ("LIFO", "Last In, First Out"),
        ("HIFO", "Highest Cost In, First Out"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="tax_lots",
    )
    asset_class = models.CharField(max_length=12, db_index=True)
    symbol = models.CharField(max_length=40, db_index=True)

    qty_initial = models.DecimalField(max_digits=18, decimal_places=8)
    qty_remaining = models.DecimalField(max_digits=18, decimal_places=8)
    cost_basis_per_unit = models.DecimalField(max_digits=18, decimal_places=8)
    multiplier = models.IntegerField(default=1,
        help_text="Contract multiplier for options/futures (100 for equity options).")

    opened_at = models.DateTimeField(db_index=True)
    closed_at = models.DateTimeField(null=True, blank=True,
        help_text="Set when qty_remaining reaches 0.")

    source_trade = models.ForeignKey(
        "bot_program.AssetBotTrade", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="opened_tax_lots",
    )
    method_at_open = models.CharField(max_length=4, choices=LOT_METHOD_CHOICES, default="FIFO")
    paper = models.BooleanField(default=True, db_index=True,
        help_text="Paper trades tracked for parity; tax export filters by mode.")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-opened_at"]
        indexes = [
            models.Index(fields=["user", "symbol", "asset_class", "qty_remaining"]),
            models.Index(fields=["user", "-opened_at"]),
        ]

    def __str__(self):
        return (f"{self.symbol} {self.qty_remaining}/{self.qty_initial} @ "
                f"{self.cost_basis_per_unit} ({self.opened_at:%Y-%m-%d})")


class TaxLotConsumption(models.Model):
    """A slice of a TaxLot consumed by a sale. Carries realised gain + ST/LT."""

    lot = models.ForeignKey(TaxLot, on_delete=models.CASCADE,
                             related_name="consumptions")
    consuming_trade = models.ForeignKey(
        "bot_program.AssetBotTrade", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="lot_consumptions",
    )

    qty_consumed = models.DecimalField(max_digits=18, decimal_places=8)
    sale_price_per_unit = models.DecimalField(max_digits=18, decimal_places=8)
    sold_at = models.DateTimeField(db_index=True)

    realized_gain = models.DecimalField(max_digits=18, decimal_places=4,
        help_text="(sale - cost) × qty × multiplier. Signed.")
    holding_period_days = models.IntegerField(default=0)
    long_term = models.BooleanField(default=False, db_index=True,
        help_text="True iff holding_period_days >= 365 (US LT capital gains threshold).")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-sold_at"]
        indexes = [
            models.Index(fields=["lot", "-sold_at"]),
        ]

    def __str__(self):
        return (f"{self.lot.symbol} {self.qty_consumed} @ {self.sale_price_per_unit} "
                f"gain {self.realized_gain:+.2f} "
                f"({'LT' if self.long_term else 'ST'})")
