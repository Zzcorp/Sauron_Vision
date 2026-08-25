"""Rule actuator models — Phase-5 closed-loop self-adjustment.

`RuleControl` is the *current state* of a signal rule:
  - active   (default; signals persist normally)
  - paused   (new signals for this rule are dropped until paused_until)
  - reduced  (new signals persist with weight_multiplier applied)

`RuleAction` is the *audit log* of every enforcement proposal — proposed,
applied, rolled back, or rejected. Every applied action carries a snapshot
of the previous RuleControl state so rollback restores it exactly.

Safety principles encoded here:
  - Every action requires explicit admin confirmation (no auto-apply by default).
  - Every action is reversible via the snapshot fields.
  - Pauses auto-expire after `paused_until`; the actuator reads this on next pass.
  - The mode component `actuator_mode_live` gates whether admin CAN apply at all
    (off = shadow / preview-only; on = admin can apply).
"""
from django.conf import settings
from django.db import models
from django.utils import timezone


class RuleControl(models.Model):
    """Current enforcement state for a single signal rule_name.

    Two independent multiplicative weights:
      - `weight_multiplier`: set by the Phase-5 actuator (admin-confirmed
        pause / reduce / rollback). Admin-controlled.
      - `allocator_weight`: set by the Phase-7 meta-allocator (math-driven
        risk-budget allocation). Auto-updated from the realized_r distribution.

    The effective sizing multiplier returned by `rule_size_multiplier()` is
    the product of both — so admin-set adjustments always survive an allocator
    rebalance, and the allocator only fine-tunes within the admin envelope.
    """

    STATUS_ACTIVE = "active"
    STATUS_PAUSED = "paused"
    STATUS_REDUCED = "reduced"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_PAUSED, "Paused"),
        (STATUS_REDUCED, "Reduced size"),
    ]

    # Phase-8 promotion-pipeline stages.
    STAGE_RESEARCH = "research"
    STAGE_PAPER = "paper"
    STAGE_LIVE_SMALL = "live_small"
    STAGE_LIVE_FULL = "live_full"
    STAGE_CHOICES = [
        (STAGE_RESEARCH, "Research (no trade)"),
        (STAGE_PAPER, "Paper only"),
        (STAGE_LIVE_SMALL, "Live (small size)"),
        (STAGE_LIVE_FULL, "Live (full size)"),
    ]

    rule_name = models.CharField(max_length=100, unique=True, db_index=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    weight_multiplier = models.FloatField(
        default=1.0,
        help_text="Phase-5 admin-controlled multiplier. 1.0 = full, 0.5 = half.",
    )
    allocator_weight = models.FloatField(
        default=1.0,
        help_text="Phase-7 meta-allocator weight. 1.0 = neutral. Auto-updated.",
    )
    paused_until = models.DateTimeField(null=True, blank=True,
                                        help_text="When set, status reverts to active automatically after this time.")
    # Phase-8: where the rule sits in the promotion pipeline.
    promotion_stage = models.CharField(
        max_length=16, choices=STAGE_CHOICES, default=STAGE_LIVE_FULL,
        help_text="Phase-8 promotion stage. New rules start at RESEARCH; existing migrate at LIVE_FULL.",
    )
    stage_entered_at = models.DateTimeField(null=True, blank=True,
                                             help_text="When the rule entered its current promotion_stage.")
    stage_baseline_expectancy = models.FloatField(
        null=True, blank=True,
        help_text="Expectancy at last stage transition; used to detect degradation for auto-demote.",
    )
    parameters = models.JSONField(
        default=dict, blank=True,
        help_text="Phase-9 parameter dict for parameter-aware rules. Empty for hand-coded rules.",
    )
    notes = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["rule_name"]

    def __str__(self):
        return f"RuleControl[{self.rule_name}: {self.status} ×{self.weight_multiplier}]"

    def is_effectively_active(self, now=None) -> bool:
        """True iff the rule allows new signals right now (paused_until honoured)."""
        now = now or timezone.now()
        if self.status == self.STATUS_PAUSED:
            if self.paused_until and now >= self.paused_until:
                return True  # auto-reactivated by time
            return False
        return True

    @classmethod
    def running_q(cls, now=None):
        """`is_effectively_active()` expressed as a queryset filter.

        The raw `status` column is NOT the population the engine runs, and every
        query built on `status="active"` silently subtracts rules that are live:

          - `reduced` is a running state. `rule_actuator.rule_size_multiplier`
            honours `weight_multiplier` ONLY when status == "reduced" — the
            field exists to SIZE a rule that is still trading.
          - a `paused` rule whose `paused_until` has elapsed is running again.
            `is_effectively_active()` computes that expiry on the fly, but
            nothing anywhere writes the column back to "active", so the
            help_text above is true of the engine and false of the database.
            With PAUSE_DURATION_DAYS = 30, every served pause becomes a
            permanently uncounted running rule.

        It lives on the model rather than at each call site because a Python
        method cannot be filtered on, so the predicate has to be restated in ORM
        terms exactly once — next to the method it must agree with, where a
        change to one is in the same screen as the other. Asserted against the
        method in tests/test_engine_control_surfaces.py.
        """
        now = now or timezone.now()
        return (models.Q(status__in=(cls.STATUS_ACTIVE, cls.STATUS_REDUCED))
                | models.Q(status=cls.STATUS_PAUSED, paused_until__lte=now))


class RuleAction(models.Model):
    """Audit log of every actuator proposal + its lifecycle."""

    ACTION_PAUSE = "pause_rule"
    ACTION_REDUCE = "reduce_size"
    ACTION_MONITOR = "monitor"
    ACTION_INVESTIGATE_DATA = "investigate_data"
    ACTION_RETUNE = "retune_params"
    ACTION_CHOICES = [
        (ACTION_PAUSE, "Pause rule"),
        (ACTION_REDUCE, "Reduce size"),
        (ACTION_MONITOR, "Monitor (no-op)"),
        (ACTION_INVESTIGATE_DATA, "Investigate data quality"),
        (ACTION_RETUNE, "Retune parameters"),
    ]

    STATE_PROPOSED = "proposed"
    STATE_APPLIED = "applied"
    STATE_REJECTED = "rejected"
    STATE_ROLLED_BACK = "rolled_back"
    STATE_EXPIRED = "expired"
    STATE_CHOICES = [
        (STATE_PROPOSED, "Proposed (awaiting admin)"),
        (STATE_APPLIED, "Applied"),
        (STATE_REJECTED, "Rejected by admin"),
        (STATE_ROLLED_BACK, "Rolled back"),
        (STATE_EXPIRED, "Expired (no decision)"),
    ]

    rule_name = models.CharField(max_length=100, db_index=True)
    action = models.CharField(max_length=24, choices=ACTION_CHOICES)
    state = models.CharField(max_length=16, choices=STATE_CHOICES,
                             default=STATE_PROPOSED, db_index=True)

    # Source — the DecayInvestigation that triggered this proposal (nullable
    # so admin can also propose actions manually).
    source_investigation = models.ForeignKey(
        "ai_agents.DecayInvestigation", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="rule_actions",
    )

    # Source — the BrainReport whose synthesis the operator acted on. Set
    # by `propose_from_brain`; the (report, rule, action) triple is the
    # idempotency key there, so one press on the brain page can never queue
    # two proposals for the same concern. Nullable: decay proposals and
    # manual admin proposals have no report behind them.
    source_brain_report = models.ForeignKey(
        "brain.BrainReport", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="rule_actions",
    )

    rationale = models.TextField(blank=True)

    # Snapshot taken at apply-time so rollback can restore exactly. NULL
    # before apply, frozen at apply.
    previous_status = models.CharField(max_length=12, blank=True)
    previous_weight = models.FloatField(null=True, blank=True)
    previous_paused_until = models.DateTimeField(null=True, blank=True)

    # Lifecycle timestamps
    proposed_at = models.DateTimeField(auto_now_add=True)
    applied_at = models.DateTimeField(null=True, blank=True)
    rolled_back_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)

    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="rule_actions_confirmed",
    )

    class Meta:
        ordering = ["-proposed_at"]
        indexes = [
            models.Index(fields=["state", "-proposed_at"]),
            models.Index(fields=["rule_name", "-proposed_at"]),
        ]

    def __str__(self):
        return f"RuleAction[{self.rule_name} {self.action} → {self.state}]"


class MetaAllocation(models.Model):
    """Phase-7: audit log of every meta-allocator run.

    Each run computes target weights for every active rule using an ensemble
    of methods. Stored in shadow state until admin promotes to applied — same
    pattern as Phase-5 RuleAction.
    """

    STATE_SHADOW = "shadow"
    STATE_APPLIED = "applied"
    STATE_ROLLED_BACK = "rolled_back"
    STATE_REJECTED = "rejected"
    STATE_CHOICES = [
        (STATE_SHADOW, "Shadow (preview)"),
        (STATE_APPLIED, "Applied"),
        (STATE_ROLLED_BACK, "Rolled back"),
        (STATE_REJECTED, "Rejected by admin"),
    ]

    state = models.CharField(max_length=16, choices=STATE_CHOICES,
                             default=STATE_SHADOW, db_index=True)
    lookback_days = models.IntegerField(default=180)
    sample_tier = models.CharField(max_length=10, blank=True,
                                   help_text="tier1 (≥30/rule) | tier2 (≥10/rule) | tier3 (<10)")

    # Ensemble breakdown — what fraction of the final weight came from each method.
    ensemble_blend = models.JSONField(default=dict)
    # Per-method outputs: {"uniform": {rule:weight}, "inverse_vol": {...}, "expectancy": {...}}
    per_method_weights = models.JSONField(default=dict)
    # Final blended target weights, after caps + smoothing.
    target_weights = models.JSONField(default=dict)
    # Snapshot of `RuleControl.allocator_weight` at apply-time per rule (for rollback).
    previous_weights = models.JSONField(default=dict)

    rules_considered = models.IntegerField(default=0)
    rules_skipped = models.IntegerField(default=0)
    notes = models.TextField(blank=True)

    proposed_at = models.DateTimeField(auto_now_add=True)
    applied_at = models.DateTimeField(null=True, blank=True)
    rolled_back_at = models.DateTimeField(null=True, blank=True)

    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="meta_allocations_confirmed",
    )

    class Meta:
        ordering = ["-proposed_at"]
        indexes = [
            models.Index(fields=["state", "-proposed_at"]),
        ]

    def __str__(self):
        return f"MetaAllocation[{self.state} sample={self.sample_tier} rules={self.rules_considered}]"


class PromotionEvent(models.Model):
    """Phase-8: audit log of every promotion-pipeline transition.

    Every promotion or demotion (auto or manual) creates a row. Snapshots the
    `from_stage`, `to_stage`, baseline expectancy, and the trigger reason —
    so rollback can restore exactly and "why" is always answerable.
    """

    REASON_CHOICES = [
        ("auto_promote", "Auto promotion (criteria met)"),
        ("auto_demote", "Auto demotion (degradation)"),
        ("manual_promote", "Manual promotion"),
        ("manual_demote", "Manual demotion"),
        ("rollback", "Rollback to prior stage"),
    ]

    rule_name = models.CharField(max_length=100, db_index=True)
    from_stage = models.CharField(max_length=16, blank=True)
    to_stage = models.CharField(max_length=16)
    reason = models.CharField(max_length=24, choices=REASON_CHOICES)

    # Snapshot at transition time — used both for audit and to compute
    # subsequent degradation against this baseline.
    expectancy_at_transition = models.FloatField(null=True, blank=True)
    n_at_transition = models.IntegerField(default=0)

    notes = models.TextField(blank=True)
    triggered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="promotion_events_triggered",
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["rule_name", "-created_at"]),
        ]

    def __str__(self):
        return f"PromotionEvent[{self.rule_name} {self.from_stage}→{self.to_stage}]"


class RuleMutation(models.Model):
    """Phase-9: a candidate mutation of an existing rule's parameters.

    Mutations are proposed by the evolution loop, scored (heuristically by
    default; with a proper backtest when the rule is parameter-aware), and
    optionally APPLIED — which forks a new rule with the mutated parameters,
    starting at RESEARCH stage in the Phase-8 promotion pipeline. The original
    rule is never modified by evolution.
    """

    STATE_PROPOSED = "proposed"
    STATE_APPLIED = "applied"
    STATE_REJECTED = "rejected"
    STATE_EXPIRED = "expired"
    STATE_CHOICES = [
        (STATE_PROPOSED, "Proposed"),
        (STATE_APPLIED, "Applied (forked into new rule)"),
        (STATE_REJECTED, "Rejected"),
        (STATE_EXPIRED, "Expired"),
    ]

    parent_rule = models.CharField(max_length=100, db_index=True,
                                    help_text="The rule_name being mutated.")
    forked_rule = models.CharField(max_length=120, blank=True,
                                    help_text="Name of the new rule created when applied. "
                                              "Format: '{parent}_evolved_v{N}'.")

    parent_params = models.JSONField(default=dict)
    mutated_params = models.JSONField(default=dict)
    parameters_changed = models.JSONField(default=list,
                                           help_text="List of parameter names that differ from parent.")

    parent_expectancy = models.FloatField(null=True, blank=True)
    proposed_score = models.FloatField(null=True, blank=True,
                                        help_text="Score from the proposer. Method-specific; see score_method + score_details.")
    score_method = models.CharField(max_length=24, default="heuristic",
                                     help_text="heuristic | walk_forward | manual_backtest")
    score_details = models.JSONField(
        default=dict, blank=True,
        help_text="Method-specific score breakdown (e.g. train/test expectancies for walk_forward).",
    )

    state = models.CharField(max_length=12, choices=STATE_CHOICES,
                             default=STATE_PROPOSED, db_index=True)
    rationale = models.TextField(blank=True)

    proposed_at = models.DateTimeField(auto_now_add=True)
    applied_at = models.DateTimeField(null=True, blank=True)

    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="rule_mutations_decided",
    )

    class Meta:
        ordering = ["-proposed_at"]
        indexes = [
            models.Index(fields=["state", "-proposed_at"]),
            models.Index(fields=["parent_rule", "-proposed_at"]),
        ]

    def __str__(self):
        return f"RuleMutation[{self.parent_rule} → {self.forked_rule or 'pending'} ({self.state})]"
