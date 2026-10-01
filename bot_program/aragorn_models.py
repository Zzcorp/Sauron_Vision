"""ARAGORN's memory (2026-10-02).

The operator, the live book losing: "remove the strategies not working,
promote new proven ones, make it pretty autonomous but still maintainable
by Gandalf or me", then "more resilience in dark waters" and "a crash is
coming ... make the most out of crisis". Four tables:

  PairVerdict          where one (rule, asset class) pair may trade: live,
                       probation (live at a quarter of its size) or bench
                       (paper only). A row the operator pinned is never
                       changed by Aragorn.
  AragornAction        every decision Aragorn or an operator took, with
                       its numbers: the journal Gandalf reads.
  MarketStressReading  the market's stress score and the posture it set:
                       calm, stressed, crisis or recovery.
  AragornSetting       small operator settings (the posture override).
"""
from django.db import models
from django.utils import timezone


class PairVerdict(models.Model):
    STATE_LIVE = "live"
    STATE_PROBATION = "probation"
    STATE_BENCH = "bench"
    STATE_CHOICES = [(STATE_LIVE, "Live"), (STATE_PROBATION, "Probation"),
                     (STATE_BENCH, "Bench")]
    #: asset_class of the row that covers every class of the rule that has
    #: no row of its own (written when Aragorn promotes a paper rule
    #: for ONE proven class: the others stay on the bench).
    ANY_CLASS = "*"

    rule_name = models.CharField(max_length=100, db_index=True)
    asset_class = models.CharField(max_length=12)
    state = models.CharField(max_length=12, choices=STATE_CHOICES)
    since = models.DateTimeField(default=timezone.now)
    reason = models.TextField(blank=True)
    stats = models.JSONField(default=dict, blank=True)
    pinned = models.BooleanField(default=False)
    changed_by = models.CharField(max_length=40, default="aragorn")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("rule_name", "asset_class")]
        ordering = ["rule_name", "asset_class"]

    def __str__(self):
        return f"{self.rule_name}/{self.asset_class}: {self.state}"


class AragornAction(models.Model):
    at = models.DateTimeField(default=timezone.now, db_index=True)
    kind = models.CharField(max_length=24, db_index=True)
    rule_name = models.CharField(max_length=100, blank=True)
    asset_class = models.CharField(max_length=12, blank=True)
    symbol = models.CharField(max_length=40, blank=True)
    trade_id = models.IntegerField(null=True, blank=True)
    detail = models.TextField(blank=True)
    stats = models.JSONField(default=dict, blank=True)
    by = models.CharField(max_length=40, default="aragorn")

    class Meta:
        ordering = ["-at"]

    def __str__(self):
        return f"{self.at:%Y-%m-%d %H:%M} {self.kind} {self.detail[:60]}"


class MarketStressReading(models.Model):
    LEVEL_CALM = "calm"
    LEVEL_STRESSED = "stressed"
    LEVEL_CRISIS = "crisis"
    LEVEL_RECOVERY = "recovery"
    LEVEL_CHOICES = [(LEVEL_CALM, "Calm"), (LEVEL_STRESSED, "Stressed"),
                     (LEVEL_CRISIS, "Crisis"), (LEVEL_RECOVERY, "Recovery")]

    at = models.DateTimeField(default=timezone.now, db_index=True)
    score = models.FloatField(null=True, blank=True)
    raw_level = models.CharField(max_length=12, blank=True)
    level = models.CharField(max_length=12, choices=LEVEL_CHOICES)
    components = models.JSONField(default=dict, blank=True)
    reasons = models.JSONField(default=list, blank=True)
    override = models.CharField(max_length=12, blank=True)

    class Meta:
        ordering = ["-at"]

    def __str__(self):
        return f"{self.at:%Y-%m-%d %H:%M} {self.level} ({self.score})"


class AragornSetting(models.Model):
    key = models.CharField(max_length=60, unique=True)
    value = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.CharField(max_length=40, blank=True)

    def __str__(self):
        return f"{self.key}={self.value}"
