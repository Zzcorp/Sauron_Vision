"""SmcSignal model — explainability fields baked in from day one."""
from django.db import models
from django.utils import timezone


class SmcSignal(models.Model):
    SETUP_CHOICES = [
        ("RP_BREAKER",       "RP Breaker"),
        ("THREE_TAP",        "Three Tap"),
        ("RANGE_MSB_SD",     "Range + MSB + SD"),
        ("REVERSAL_PATTERN", "Reversal Pattern"),
        ("PO3",              "Power of Three"),
        ("FVG_TAP",          "FVG Tap"),
        ("OB_RETEST",        "Order Block Retest"),
        ("SFP",              "Swing Failure Pattern"),
    ]
    DIRECTION_CHOICES = [("LONG", "Long"), ("SHORT", "Short")]
    STATUS_CHOICES = [
        ("ACTIVE",       "Active"),
        ("TRIGGERED",    "Triggered"),
        ("FILLED",       "Filled"),
        ("STOPPED",      "Stopped"),
        ("TARGET_HIT",   "Target Hit"),
        ("EXPIRED",      "Expired"),
        ("INVALIDATED",  "Invalidated"),
    ]

    # Identity
    symbol = models.CharField(max_length=32, db_index=True)
    timeframe = models.CharField(max_length=8)
    setup = models.CharField(max_length=32, choices=SETUP_CHOICES)
    direction = models.CharField(max_length=8, choices=DIRECTION_CHOICES)

    # The 5-second card
    headline = models.CharField(max_length=120)
    thesis = models.CharField(max_length=280)
    why_now = models.TextField(blank=True)
    invalidation = models.CharField(max_length=200)

    # Levels
    entry = models.FloatField()
    stop = models.FloatField()
    target = models.FloatField()
    r_multiple = models.FloatField(default=0)

    # Confluence chips: -1 disagree / 0 neutral / 1 supporting
    chip_structure = models.IntegerField(default=0)
    chip_momentum = models.IntegerField(default=0)
    chip_flow = models.IntegerField(default=0)
    chip_macro = models.IntegerField(default=0)
    chip_sentiment = models.IntegerField(default=0)

    # Conviction (0-100)
    conviction = models.IntegerField(default=0)

    # Raw evidence
    reasons = models.JSONField(default=list)
    components = models.JSONField(default=list)
    raw = models.JSONField(default=dict, blank=True)

    # Lifecycle
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="ACTIVE")
    triggered_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    realized_r = models.FloatField(null=True, blank=True)

    # Performance attribution
    rule_hit_rate_30d = models.FloatField(null=True, blank=True)

    # Bookkeeping
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    trigger_ts = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["symbol", "timeframe", "status"]),
            models.Index(fields=["setup", "status"]),
        ]

    def __str__(self):
        return f"{self.symbol} {self.direction} {self.setup} @ {self.entry:.4f}"
