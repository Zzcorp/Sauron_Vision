"""Live streaming data models — liquidations, funding, L2 snapshots."""
from django.db import models

class LiquidationEvent(models.Model):
    """Forced liquidations from Binance futures @forceOrder stream."""
    SIDE = [("LONG","Long liquidated"),("SHORT","Short liquidated")]
    symbol       = models.CharField(max_length=20, db_index=True)
    side         = models.CharField(max_length=6, choices=SIDE)
    qty          = models.DecimalField(max_digits=24, decimal_places=8)
    price        = models.DecimalField(max_digits=24, decimal_places=8)
    notional_usd = models.DecimalField(max_digits=24, decimal_places=2, default=0)
    timestamp    = models.DateTimeField(db_index=True)
    source       = models.CharField(max_length=24, default="binance_futures")
    class Meta:
        indexes  = [models.Index(fields=["symbol","-timestamp"])]
        ordering = ["-timestamp"]

class FundingRate(models.Model):
    """Funding snapshots from Binance futures @markPrice stream."""
    symbol            = models.CharField(max_length=20, db_index=True)
    mark_price        = models.DecimalField(max_digits=24, decimal_places=8)
    index_price       = models.DecimalField(max_digits=24, decimal_places=8, default=0)
    funding_rate      = models.DecimalField(max_digits=12, decimal_places=8, default=0)
    next_funding_time = models.DateTimeField(null=True, blank=True)
    timestamp         = models.DateTimeField(db_index=True)
    class Meta:
        indexes  = [models.Index(fields=["symbol","-timestamp"])]
        ordering = ["-timestamp"]

class OrderBookSnapshot(models.Model):
    """L2 order book snapshots from Binance @depth20@100ms."""
    symbol      = models.CharField(max_length=20, db_index=True)
    timestamp   = models.DateTimeField(db_index=True)
    mid_price   = models.DecimalField(max_digits=24, decimal_places=8)
    spread      = models.DecimalField(max_digits=24, decimal_places=8, default=0)
    bid_volume  = models.DecimalField(max_digits=24, decimal_places=4, default=0)
    ask_volume  = models.DecimalField(max_digits=24, decimal_places=4, default=0)
    imbalance   = models.FloatField(default=0)   # (bid-ask)/(bid+ask)
    depth_score = models.FloatField(default=0)   # depth-weighted imbalance
    bids        = models.JSONField(default=list) # [[price,qty],...] top 20
    asks        = models.JSONField(default=list)
    class Meta:
        indexes  = [models.Index(fields=["symbol","-timestamp"])]
        ordering = ["-timestamp"]
