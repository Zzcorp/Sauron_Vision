"""A SharePlan — the share allocator's proposal, with every input on it.

Every few hours the allocator (bot_program/share_allocator.py) computes a
TARGET share of the broker account for each live follower config and
writes it here in state PROPOSED. Nothing moves on that write: the plan
is a shadow until an admin applies it (PIN on /shares/, --yes on the
shell), and only then does `extras["account_share_pct"]` change and the
sync's arithmetic re-size the pools. A plan carries its own evidence —
the reading it saw, the drawdown, every factor per config and one
sentence of why — because a plan that cannot be re-read a week later is
a plan nobody can grade. `grade_score` is that grade: positive when the
plan leaned toward the configs that then paid, in R.

The share allocator never writes `cfg.capital` and never talks to the
broker: it writes a share, and the sync that owns the reading does the
rest (2026-09-12).
"""
from django.conf import settings
from django.db import models


class SharePlan(models.Model):
    STATE_PROPOSED = "proposed"
    STATE_APPLIED = "applied"
    STATE_REJECTED = "rejected"
    STATE_ROLLED_BACK = "rolled_back"
    STATE_EXPIRED = "expired"
    STATE_CHOICES = [
        (STATE_PROPOSED, "Proposed (shadow)"),
        (STATE_APPLIED, "Applied"),
        (STATE_REJECTED, "Rejected by admin"),
        (STATE_ROLLED_BACK, "Rolled back"),
        (STATE_EXPIRED, "Expired"),
    ]

    # The market state the plan was computed under (2026-09-12). NORMAL is
    # the symmetric rule (10 pt/day, half-way smoothing); SHOCK is de-risk
    # only (down uncapped, up frozen, no redistribution); EXPANSION lets a
    # proven rally at the high-water mark expand at 20 pt/day. Persisted so
    # the 24h shock hold can find the last shock plan without re-deriving
    # it from a reading that is gone, and so the page can badge the row.
    MODE_NORMAL = "normal"
    MODE_SHOCK = "shock"
    MODE_EXPANSION = "expansion"
    MODE_CHOICES = [
        (MODE_NORMAL, "Normal"),
        (MODE_SHOCK, "Shock (de-risk only)"),
        (MODE_EXPANSION, "Expansion"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL,
                             on_delete=models.CASCADE,
                             related_name="share_plans")
    state = models.CharField(max_length=16, choices=STATE_CHOICES,
                             default=STATE_PROPOSED, db_index=True)
    mode = models.CharField(max_length=12, choices=MODE_CHOICES,
                            default=MODE_NORMAL, db_index=True)
    # Why the plan is in that mode, one string per trigger ('equity −4.2%
    # in 24h', 'regime risk_off 0.71', 'shock hold until …').
    mode_reasons = models.JSONField(default=list, blank=True)

    # The reading the plan was computed against — value, currency, when,
    # and how old it was at proposal time. Apply re-checks freshness
    # against the LIVE reading, not this snapshot.
    reading_value = models.DecimalField(max_digits=18, decimal_places=2,
                                        null=True, blank=True)
    reading_currency = models.CharField(max_length=8, blank=True, default="")
    reading_at = models.DateTimeField(null=True, blank=True)
    reading_age_s = models.IntegerField(null=True, blank=True)

    # The drawdown governor's inputs and its answer.
    hwm = models.DecimalField(max_digits=18, decimal_places=2,
                              null=True, blank=True)
    drawdown_pct = models.FloatField(null=True, blank=True)
    governor = models.FloatField(default=1.0)

    # Per config pk (as a string — JSON keys are strings and a plan must
    # round-trip through the column unchanged): every factor, the raw /
    # capped / smoothed numbers, whether the move was held, and one
    # sentence of why.
    inputs = models.JSONField(default=dict, blank=True)
    targets = models.JSONField(default=dict, blank=True)
    current_shares = models.JSONField(default=dict, blank=True)
    # Apply-time snapshot of extras["account_share_pct"] per config, None
    # where the follower was automatic — what rollback restores EXACTLY.
    previous_shares = models.JSONField(default=dict, blank=True)

    configs_considered = models.IntegerField(default=0)
    configs_skipped = models.IntegerField(default=0)
    notes = models.TextField(blank=True, default="")

    proposed_at = models.DateTimeField(auto_now_add=True, db_index=True)
    applied_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    rolled_back_at = models.DateTimeField(null=True, blank=True)
    graded_at = models.DateTimeField(null=True, blank=True)

    grade_score = models.FloatField(null=True, blank=True)
    grade_detail = models.JSONField(default=dict, blank=True)

    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="share_plans_confirmed")

    class Meta:
        ordering = ["-proposed_at"]
        indexes = [
            models.Index(fields=["state", "-proposed_at"]),
        ]

    def __str__(self):
        return f"<SharePlan #{self.pk} {self.user_id} {self.state}>"
