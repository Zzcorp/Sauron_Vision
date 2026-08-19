"""Phase-10 multi-modal opportunity scanner models.

`OpportunitySetup` — a hand-curated (or evolved) pattern of conditions across
multiple data sources. Admin defines the conditions; the scanner matches them
against current market state daily.

`OpportunityFlag` — one match. Records which conditions matched, the composite
score, the suggested trade levels, and (after resolution) whether the implied
move actually played out.
"""
from django.conf import settings
from django.db import models

from instruments.models import Instrument


class OpportunitySetup(models.Model):
    """A registered multi-modal setup that the scanner matches each tick.

    The `conditions` JSON is a list of dicts, each shaped:
        {
          "kind": "<evaluator_kind>",
          "params": {... evaluator-specific ...},
          "weight": 1.0   # optional, default 1.0
        }
    """

    DIRECTION_CHOICES = [
        ("bullish", "Bullish"),
        ("bearish", "Bearish"),
        ("neutral", "Neutral"),
    ]

    name = models.CharField(max_length=120, unique=True, db_index=True)
    description = models.TextField(blank=True)

    direction = models.CharField(max_length=10, choices=DIRECTION_CHOICES,
                                  default="bullish")
    asset_classes = models.JSONField(
        default=list,
        help_text="List of asset_class strings the scanner will run on. Empty = all.",
    )

    conditions = models.JSONField(
        default=list,
        help_text="List of {kind, params, weight} dicts.",
    )

    min_match_score = models.FloatField(
        default=0.7,
        help_text="Composite score 0..1 that must be exceeded to create a flag.",
    )
    suggested_horizon_days = models.IntegerField(
        default=5,
        help_text="How many days to wait before resolving the flag's implied move.",
    )

    sizing = models.JSONField(
        default=dict, blank=True,
        # stop_atr_mult and target_pct were advertised here and read by nothing:
        # `_suggested_levels` has no ATR branch and no absolute-target branch,
        # so a setup typed from the old text got a 2R target it never asked for.
        # SIZING_KEYS in opportunity_scanner is the declaration this mirrors.
        help_text='Sizing config: {"stop_pct": 2.0, "target_rr": 2.0}. Those two keys and no others — anything else is discarded.',
    )

    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="opportunity_setups",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"OpportunitySetup[{self.name} {self.direction}]"


class OpportunityFlag(models.Model):
    """A scanner match — one (setup, instrument) pair flagged at a moment."""

    OUTCOME_CHOICES = [
        ("hit", "Implied move played out"),
        ("miss", "Implied move did not play out"),
        ("neutral", "Move within neutral band"),
        ("expired", "Resolution window passed"),
    ]

    setup = models.ForeignKey(
        OpportunitySetup, on_delete=models.CASCADE, related_name="flags",
    )
    instrument = models.ForeignKey(
        Instrument, on_delete=models.CASCADE, related_name="opportunity_flags",
    )
    # Linked Signal so this match flows through every Phase-1-9 lane automatically.
    signal = models.ForeignKey(
        "signals.Signal", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="opportunity_flags",
    )

    direction = models.CharField(max_length=10, default="bullish")
    score = models.FloatField(help_text="Composite condition match score 0..1.")
    conditions_evaluated = models.JSONField(
        default=list,
        help_text="Per-condition evaluator output: list of {kind, matched, score, details}.",
    )

    price_at_flag = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    suggested_entry = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    suggested_stop = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    suggested_target = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    horizon_days = models.IntegerField(default=5)

    outcome = models.CharField(max_length=10, choices=OUTCOME_CHOICES, blank=True)
    resolved_price = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_notes = models.TextField(blank=True)

    scanned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-scanned_at"]
        indexes = [
            models.Index(fields=["-scanned_at"]),
            models.Index(fields=["setup", "-scanned_at"]),
            models.Index(fields=["outcome", "-scanned_at"]),
        ]

    def __str__(self):
        return f"OpportunityFlag[{self.setup.name} {self.instrument.symbol} score={self.score:.2f}]"


class DiscoveredSetup(models.Model):
    """Phase-11: a setup proposal mined from historical multi-modal data.

    Mining works by:
      1. Identify historical "interesting moves" (>=Nσ forward returns).
      2. Extract binary precursor features per move (price + news + macro etc.).
      3. Run frequent-itemset mining (Apriori) to find feature combinations
         that co-occur with interesting moves at high lift over random days.
      4. Persist each surviving combination as a DiscoveredSetup row.

    Admin reviews and either:
      - ACTIVATES → creates an OpportunitySetup with the corresponding conditions.
      - REJECTS → marks rejected, no further action.
    """

    STATE_PROPOSED = "proposed"
    STATE_ACTIVATED = "activated"
    STATE_REJECTED = "rejected"
    STATE_EXPIRED = "expired"
    STATE_CHOICES = [
        (STATE_PROPOSED, "Proposed"),
        (STATE_ACTIVATED, "Activated"),
        (STATE_REJECTED, "Rejected"),
        (STATE_EXPIRED, "Expired"),
    ]

    asset_class = models.CharField(max_length=20, blank=True)
    direction = models.CharField(max_length=10, default="bullish")

    # Mined feature keys (e.g. "price_above_ma_50", "news_sentiment_positive_2d").
    features = models.JSONField(default=list)

    # Mining stats.
    n_supporting_moves = models.IntegerField(default=0)
    n_total_moves = models.IntegerField(default=0)
    support = models.FloatField(default=0.0)
    lift = models.FloatField(default=1.0)
    hit_rate = models.FloatField(default=0.0)

    lookback_days = models.IntegerField(default=730)
    forward_horizon_days = models.IntegerField(default=5)
    mined_at = models.DateTimeField(auto_now_add=True)

    state = models.CharField(max_length=12, choices=STATE_CHOICES,
                             default=STATE_PROPOSED, db_index=True)
    activated_setup = models.ForeignKey(
        "signals.OpportunitySetup", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="discovered_origins",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="discovered_setups_decided",
    )
    rationale = models.TextField(blank=True)

    class Meta:
        ordering = ["-mined_at"]
        indexes = [
            models.Index(fields=["state", "-mined_at"]),
            models.Index(fields=["asset_class", "direction"]),
        ]

    def __str__(self):
        return (f"DiscoveredSetup[{self.asset_class} {self.direction} "
                f"feats={len(self.features)} support={self.support:.2f} "
                f"lift={self.lift:.2f}]")
