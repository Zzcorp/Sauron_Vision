"""HorizonView — one run of the 5-10 year sector synthesis (2026-09-12).

The operator's ask: "syntheses of sectors and their development over
5-10 years, to guard against those risks." This is the durable record of
one such synthesis: the sector tilts, the asset-class tilts the share
allocator reads as a weak prior, the regime claims, and the cost of the
run. The row is created BEFORE the model is called (status `running`) and
settled after it, so a provider outage or a garbled answer still leaves a
row that says what happened — the position reviewer's precedent.

A rejected answer keeps its raw text: the operator paid ~1.5 USD for it
and gets to read what came back, even when the platform refused to act
on it (the strategy generator's `_record_rejection` precedent). Nothing
here is read by any allocator unless `status == "ok"` — `latest_view`
enforces that, and the age ceiling with it.
"""
from __future__ import annotations

from datetime import timedelta

from django.db import models
from django.utils import timezone

# A view older than this is history, not a prior. Mirrored in
# bot_program.share_allocator.HORIZON_MAX_AGE_DAYS; the allocator imports
# neither constant from the other so the two modules stay decoupled, and
# tests/test_horizon.py pins that they agree.
DEFAULT_MAX_AGE_DAYS = 45


class HorizonView(models.Model):
    STATUS_RUNNING = "running"
    STATUS_OK = "ok"
    STATUS_REJECTED = "rejected"
    STATUS_ERROR = "error"
    STATUS_CHOICES = [
        (STATUS_RUNNING, "Running"),
        (STATUS_OK, "OK"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_ERROR, "Error"),
    ]

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES,
                              default=STATUS_RUNNING, db_index=True)
    horizon_years = models.IntegerField(default=5)
    summary_md = models.TextField(blank=True)
    # The validated sector list, exactly as parse_response returned it:
    # [{key, thesis_md, structural_drivers, risks, catalysts, tilt,
    #   confidence, calls: [{symbol, direction, horizon_hours, confidence,
    #   why}]}]
    sectors = models.JSONField(default=list)
    # {asset_class: {"tilt": -2..2, "confidence": 0..1, "why": str}} — the
    # shape the share allocator reads.
    asset_class_tilts = models.JSONField(default=dict)
    regime_claims = models.JSONField(default=list)
    calls_registered = models.IntegerField(default=0)
    calls_dropped = models.IntegerField(default=0)

    model_used = models.CharField(max_length=80, default="")
    tokens_in = models.IntegerField(default=0)
    tokens_out = models.IntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    error = models.TextField(blank=True)
    # The model's raw text, kept ONLY on a rejected row (≤ 20,000 chars).
    raw = models.TextField(blank=True)
    snapshot_as_of = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return (f"<HorizonView #{self.pk} {self.status} "
                f"{self.horizon_years}y {self.created_at:%Y-%m-%d}>")

    @property
    def age_days(self) -> float:
        return (timezone.now() - self.created_at).total_seconds() / 86400.0


def latest_view(max_age_days: int = DEFAULT_MAX_AGE_DAYS):
    """The newest OK view no older than `max_age_days`, or None.

    Status ok only: a rejected or errored row carries no tilts, and a
    running one is a model call in flight. Age-capped because a
    structural view from three months ago describes a tape that has
    moved; the allocator would rather be neutral than confident on it.
    """
    qs = HorizonView.objects.filter(status=HorizonView.STATUS_OK)
    if max_age_days is not None:
        cutoff = timezone.now() - timedelta(days=int(max_age_days))
        qs = qs.filter(created_at__gte=cutoff)
    return qs.order_by("-created_at").first()
