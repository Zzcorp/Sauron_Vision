"""SmcSignal model — explainability fields baked in from day one."""
from django.db import models
from django.utils import timezone


class SmcSignal(models.Model):
    # Every value here must be one some detector can actually emit, and the
    # pairing is checked by tests/test_ict_cards.py. "SFP" sat in this list for
    # months with nothing able to produce it — a card the feed advertised, the
    # performance summary grouped by and the filters offered, and that no scan
    # could ever store. `smc_rules.detect_sfp_setups` closed that hole; the five
    # ICT setups below arrived the same way round, built and tested as
    # primitives before this field could hold their names, and wired into
    # `scan_symbol` at the same time as this list grew.
    SETUP_CHOICES = [
        ("RP_BREAKER",       "RP Breaker"),
        ("THREE_TAP",        "Three Tap"),
        ("RANGE_MSB_SD",     "Range + MSB + SD"),
        ("REVERSAL_PATTERN", "Reversal Pattern"),
        ("PO3",              "Power of Three"),
        ("FVG_TAP",          "FVG Tap"),
        ("OB_RETEST",        "Order Block Retest"),
        ("SFP",              "Swing Failure Pattern"),
        ("MITIGATION_BLOCK", "Mitigation Block Retest"),
        ("OTE",              "Optimal Trade Entry"),
        ("JUDAS_SWING",      "Judas Swing"),
        ("SILVER_BULLET",    "Silver Bullet"),
        ("SMT_DIVERGENCE",   "SMT Divergence"),
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

    # Performance attribution — MEASURED from closed cards of this setup by
    # signals.performance.setup_performance_summary, never seeded from the
    # strategy author's published numbers. None means NOT MEASURED: either
    # too few closed cards to be empirical, or the record could not be read.
    # The card renders an em-dash for it and the conviction bonus is skipped.
    rule_hit_rate_30d = models.FloatField(null=True, blank=True)
    # Sample size behind the rate above. 0 is a measurement ("nothing has
    # closed yet"); None means nobody looked.
    rule_hit_rate_n = models.IntegerField(null=True, blank=True)

    # Bookkeeping
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    trigger_ts = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["symbol", "timeframe", "status"]),
            models.Index(fields=["setup", "status"]),
        ]
        constraints = [
            # One card per setup per direction per BAR. Every detector
            # evaluates the last bar, so the 900s SignalEngine pass and the
            # 1800s universe scan between them re-detected a live setup
            # roughly 18 times per 4h bar and stored all 18 — which fills the
            # feed with one idea and multiplies the n_closed that decides
            # whether a hit rate is empirical yet. persist_cards checks for
            # an open card first; this is the backstop that also covers two
            # workers racing on the same bar.
            #
            # Rows with a NULL trigger_ts are exempt (SQL treats NULLs as
            # distinct) — nothing the detectors emit lacks one, but a
            # hand-built card imported without a bar stamp is not something
            # this constraint can honestly deduplicate.
            models.UniqueConstraint(
                fields=["symbol", "timeframe", "setup", "direction", "trigger_ts"],
                name="uniq_smcsignal_per_bar",
            ),
        ]

    def __str__(self):
        return f"{self.symbol} {self.direction} {self.setup} @ {self.entry:.4f}"
