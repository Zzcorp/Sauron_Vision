"""THE SHORTS MEASURED BY HAND (2026-10-31).

The operator, 2026-10-31: "je veux les short possible entierement svp"
(I want shorts fully possible, please). The TAKE TRADE lane sends a SELL
on every class eToro's own eligibility allows, whether or not that class's
short round trip is pinned (asset_engine/base.py ETORO_SHORT_PROVEN), and
reads each such position back from eToro at the fill
(bot_program/short_readback.py). A read-back that found eToro holding
exactly what was sent is one of these rows: the facts a developer pins by
hand in tests/test_etoro_client.py CLASS_SHORT_PROOFS today — the
instrument, the side, the multiplier, the units, the order and position
ids, the open rate, the fees, the times — so the bots' gate can later be
opened on measurements rather than on a sitting (S2).

A row is written only on a CLEAN read-back and never by anything else; it
is a record, read by nothing that sends an order.
"""
from django.db import models
from django.utils import timezone


class EtoroShortObservation(models.Model):
    """One hand-taken eToro short, read back clean right after its fill."""

    trade = models.ForeignKey(
        "bot_program.AssetBotTrade", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="short_observations")
    #: the INSTRUMENT's class, the proof gate's key ("etf", "index", ...)
    asset_class = models.CharField(max_length=12, db_index=True)
    #: the platform's spelling, and eToro's (asset.symbol)
    symbol = models.CharField(max_length=40)
    venue_symbol = models.CharField(max_length=40, blank=True)
    instrument_id = models.BigIntegerField(null=True, blank=True)
    #: "demo" (eToro's virtual segment) or "live" (real money)
    world = models.CharField(max_length=8)
    #: eToro's asset.side ("short") and asset.settlementType ("CFD")
    side = models.CharField(max_length=8)
    settlement = models.CharField(max_length=12, blank=True)
    leverage = models.PositiveSmallIntegerField(default=1)
    units = models.DecimalField(max_digits=24, decimal_places=10)
    order_id = models.CharField(max_length=40)
    position_id = models.CharField(max_length=40)
    #: openingData.avgPrice, openingData.fees, the order's totalCosts and
    #: requestedAmount, the legs eToro holds — as eToro printed them
    open_rate = models.DecimalField(max_digits=24, decimal_places=10,
                                    null=True, blank=True)
    fees = models.DecimalField(max_digits=18, decimal_places=6, null=True,
                               blank=True)
    total_costs = models.DecimalField(max_digits=18, decimal_places=6,
                                      null=True, blank=True)
    requested_amount = models.DecimalField(max_digits=18, decimal_places=6,
                                           null=True, blank=True)
    stop_held = models.DecimalField(max_digits=24, decimal_places=10,
                                    null=True, blank=True)
    target_held = models.DecimalField(max_digits=24, decimal_places=10,
                                      null=True, blank=True)
    #: openingData.openTime and executionTime, and when the platform read
    opened_at = models.DateTimeField(null=True, blank=True)
    executed_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(default=timezone.now, db_index=True)
    #: the whole orders:lookup body as read, less the account's own keys
    lookup = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-read_at"]
        indexes = [models.Index(fields=["asset_class", "world", "-read_at"])]

    def __str__(self):
        return (f"{self.symbol} {self.side} {self.leverage}x "
                f"({self.asset_class}, {self.world})")
