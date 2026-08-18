"""Signal models — detected trading opportunities."""
from django.db import models
from instruments.models import Instrument
from core.constants import Direction, Urgency


class Signal(models.Model):
    SIGNAL_TYPES = [
        ("technical", "Technical"),
        ("fundamental", "Fundamental"),
        ("sentiment", "Sentiment"),
        ("macro", "Macro"),
        ("flow", "Institutional Flow"),
        ("ai_generated", "AI Generated"),
        ("composite", "Composite"),
    ]

    OUTCOME_CHOICES = [
        ("hit_target", "Hit Target"),
        ("stopped_out", "Stopped Out"),
        ("expired", "Expired"),
        ("manual_close", "Manually Closed"),
    ]

    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name="signals")
    signal_type = models.CharField(max_length=20, choices=SIGNAL_TYPES)
    direction = models.CharField(max_length=10, choices=Direction.CHOICES)
    urgency = models.CharField(max_length=10, choices=Urgency.CHOICES)

    title = models.CharField(max_length=300)
    description = models.TextField()
    rule_name = models.CharField(max_length=100)

    score = models.FloatField()
    sub_scores = models.JSONField(default=dict)

    price_at_signal = models.DecimalField(max_digits=20, decimal_places=8)
    suggested_entry = models.DecimalField(max_digits=20, decimal_places=8, null=True)
    suggested_stop = models.DecimalField(max_digits=20, decimal_places=8, null=True)
    suggested_target = models.DecimalField(max_digits=20, decimal_places=8, null=True)
    risk_reward_ratio = models.FloatField(null=True)

    portfolio_impact = models.TextField(blank=True)
    conflicts_with = models.ManyToManyField("self", blank=True, symmetrical=True)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expired_at = models.DateTimeField(null=True)
    outcome = models.CharField(max_length=20, choices=OUTCOME_CHOICES, blank=True)

    # Self-grading fields (Phase 1.0 — "the system grades itself")
    realized_r = models.FloatField(null=True, blank=True)
    mfe = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    mae = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    time_to_outcome_seconds = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"]),
            models.Index(fields=["instrument", "is_active"]),
            models.Index(fields=["outcome", "expired_at"], name="signals_sig_outcome_idx"),
            models.Index(fields=["signal_type", "expired_at"], name="signals_sig_type_idx"),
        ]

    def __str__(self):
        return f"[{self.direction.upper()}] {self.title} (score: {self.score:.2f})"
from .models_smc import SmcSignal  # noqa: F401
from .models_control import (  # noqa: F401
    RuleControl, RuleAction, MetaAllocation, PromotionEvent, RuleMutation,
)
from .models_opportunity import OpportunitySetup, OpportunityFlag, DiscoveredSetup  # noqa: F401
from .models_events import FastEvent  # noqa: F401


# ── WS push on signal creation ──────────────────────────────────────────
# dashboard.consumers.push_signal_notification existed with ZERO call
# sites: the frontend had a 'signal' message handler, the backend had a
# broadcaster, and no code path ever connected a created Signal to either
# — so the rail only ever changed on a page load. A post_save receiver is
# the one choke point every creation path shares (rule adapter, SMC
# bridge, opportunity scanner, event engine).
from django.db.models.signals import post_save as _post_save  # noqa: E402
from django.dispatch import receiver as _receiver  # noqa: E402


@_receiver(_post_save, sender=Signal, dispatch_uid="ws_push_new_signal")
def _push_new_signal(sender, instance, created, **kwargs):
    if not created or not instance.is_active:
        return
    try:
        from dashboard.consumers import push_signal_notification
        push_signal_notification({
            "id": instance.id,
            "symbol": instance.instrument.symbol,
            "direction": instance.direction,
            "title": instance.title or "",
            "score": float(instance.score or 0),
            "urgency": instance.urgency or "",
        })
    except Exception:  # noqa: BLE001 — a WS hiccup must never fail creation
        pass
