"""Storage for the Big Money Board (spec §2.9).

One BigMoneyRead per (market day, row, live or replayed): the evening read
and the next morning's share `as_of`, and the morning updates the same rows
(the crypto close and the overnight FRED data fill in). One BigMoneyCell per
scored claim, graded against the proxy's later closes (bigmoney/score.py).
Live and replayed rows are never pooled.
"""
from django.db import models
from django.utils import timezone


class BigMoneyRead(models.Model):
    as_of = models.DateField(db_index=True)
    row = models.CharField(max_length=20)            # ROWS keys, "global", "instruments"
    replayed = models.BooleanField(default=False)
    run = models.CharField(max_length=10)            # morning | evening | manual | replay
    computed_at = models.DateTimeField(default=timezone.now)
    lean = models.FloatField(null=True)
    lean_label = models.CharField(max_length=48, blank=True)
    lean_from = models.JSONField(default=list)
    coverage = models.FloatField(null=True)
    current = models.JSONField(default=list)         # the month's current, words
    risk = models.JSONField(default=list)
    cells = models.JSONField(default=dict)           # footprint -> cell; "instruments": symbol -> {footprint -> cell, "_lean": {...}}
    unread = models.JSONField(default=list)

    class Meta:
        unique_together = ("as_of", "row", "replayed")
        ordering = ["-as_of", "row"]

    def __str__(self):
        return f"{self.as_of} {self.row}{' (replayed)' if self.replayed else ''}"


class BigMoneyCell(models.Model):                     # one per scored claim
    read = models.ForeignKey(BigMoneyRead, on_delete=models.CASCADE,
                             related_name="scored")
    footprint = models.CharField(max_length=32)
    market = models.CharField(max_length=20)          # row key or instrument symbol
    proxy = models.CharField(max_length=20)
    score = models.FloatField(null=True)
    claim = models.CharField(max_length=10)           # direction | tail
    horizon_days = models.PositiveSmallIntegerField()
    proxy_close = models.FloatField(null=True)        # c_t: the as-of close, never an older one
    proxy_close_date = models.DateField(null=True)    # the day c_t closed
    fwd_return = models.FloatField(null=True)
    fwd_adverse = models.FloatField(null=True)
    scored_at = models.DateTimeField(null=True)
    score_note = models.CharField(max_length=120, blank=True)

    class Meta:
        unique_together = ("read", "footprint", "market")
        indexes = [models.Index(fields=["footprint", "market", "scored_at"])]

    def __str__(self):
        return f"{self.footprint} {self.market} {self.score}"
