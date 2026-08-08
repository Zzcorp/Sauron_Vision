"""Phase 49 — EarningsReview model.

Stores the output of one EarningsReviewerAgent run for one (instrument, event)
pair. Modeled after the Anthropic Earnings Reviewer template's output shape
but using our internal data and BaseAgent infrastructure.
"""
from __future__ import annotations

from django.db import models


class EarningsReview(models.Model):
    """Deep-dive AI review of an earnings event for a held instrument."""

    DIRECTION_BULLISH = "bullish"
    DIRECTION_BEARISH = "bearish"
    DIRECTION_NEUTRAL = "neutral"
    DIRECTION_UNKNOWN = "unknown"
    DIRECTION_CHOICES = [
        (DIRECTION_BULLISH, "Bullish"),
        (DIRECTION_BEARISH, "Bearish"),
        (DIRECTION_NEUTRAL, "Neutral"),
        (DIRECTION_UNKNOWN, "Unknown"),
    ]

    instrument = models.ForeignKey(
        "instruments.Instrument", on_delete=models.CASCADE,
        related_name="earnings_reviews",
    )
    # Loose link — EconomicEvent has no FK to Instrument, we matched on title.
    event_title = models.CharField(max_length=300, blank=True)
    event_datetime = models.DateTimeField(null=True, blank=True, db_index=True)

    summary_md = models.TextField(blank=True,
                                    help_text="2-4 paragraph narrative.")
    key_themes = models.JSONField(
        default=list, help_text="Top themes (list of {kind, text, severity}).")
    risk_signals = models.JSONField(
        default=list, help_text="Specific bear-case items the reviewer flagged.")
    implied_direction = models.CharField(
        max_length=10, choices=DIRECTION_CHOICES, default=DIRECTION_UNKNOWN)
    implied_confidence = models.FloatField(default=0.5)
    suggested_action = models.CharField(
        max_length=300, blank=True,
        help_text="One-line operator nudge (e.g. 'tighten stop', 'reduce size').")

    # Snapshot of inputs used so we can reproduce / audit.
    input_news_count = models.IntegerField(default=0)
    input_price_move_pct = models.FloatField(null=True, blank=True)

    model_used = models.CharField(max_length=80, default="")
    tokens_in = models.IntegerField(default=0)
    tokens_out = models.IntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    error = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["instrument", "-event_datetime"]),
            models.Index(fields=["-created_at"]),
        ]

    def __str__(self) -> str:
        return (f"<EarningsReview {self.instrument.symbol} "
                f"{self.event_datetime:%Y-%m-%d} "
                f"[{self.implied_direction}]>")
