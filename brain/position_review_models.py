"""Phase 61 — PositionReview: the durable record of one open-position verdict.

Why a table rather than a log line or a cached dict:

  1. A recommendation nobody can look up later is an opinion. The evidence
     that produced it (the measured facts, the triggers that fired, the mark
     it was computed on) has to sit NEXT TO the recommendation, or the
     recommendation cannot be graded and the reviewer's trust cannot move.
  2. The cost bound depends on it. `facts_hash` is what lets the model pass
     skip a position it already reasoned about on the same facts — without a
     persisted fingerprint the deep pass would re-ask the same question every
     cycle forever.
  3. The position hover card (owned by another slice) needs a read side. It
     reads rows, not a task's return value.

Rows are written only when the deterministic pass had something to say —
a trigger fired, or the mark was unusable so no verdict could be computed.
A quiet position writes nothing: a table with one row per position per cycle
would be mostly the word "fine".

Nothing on this model closes anything. It is a proposal record; the operator
acts through dashboard/views_close.py.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models


class PositionReview(models.Model):
    """One deterministic verdict on one open position, plus the optional
    model answer that a fired trigger paid for."""

    # The platform has two position books and both are watched. `book` +
    # `position_id` is the identity: neither table's pk is unique against
    # the other, and a FK to either would make the row unable to describe
    # the other book.
    BOOK_BOT = "bot"            # bot_program.AssetBotTrade
    BOOK_PORTFOLIO = "pf"       # portfolio.Position
    BOOK_CHOICES = [
        (BOOK_BOT, "Asset bot trade"),
        (BOOK_PORTFOLIO, "Portfolio position"),
    ]

    # The four answers the model is allowed to give, plus the two the
    # deterministic layer produces on its own.
    VERDICT_HOLD = "hold"
    VERDICT_TIGHTEN = "tighten"
    VERDICT_TAKE_PART = "take_part"
    VERDICT_EXIT = "exit"
    VERDICT_NONE = "none"           # triggers fired, no model pass was made
    VERDICT_NO_QUOTE = "no_quote"   # no usable mark — deliberately no verdict
    VERDICT_CHOICES = [
        (VERDICT_HOLD, "Hold"),
        (VERDICT_TIGHTEN, "Tighten the stop"),
        (VERDICT_TAKE_PART, "Take part off"),
        (VERDICT_EXIT, "Exit"),
        (VERDICT_NONE, "No verdict (model pass not made)"),
        (VERDICT_NO_QUOTE, "No verdict (no usable mark)"),
    ]
    # The verdicts that actually advise doing something to the position.
    ACTIONABLE_VERDICTS = (VERDICT_TIGHTEN, VERDICT_TAKE_PART, VERDICT_EXIT)

    OUTCOME_RIGHT = "right"
    OUTCOME_WRONG = "wrong"
    OUTCOME_UNRESOLVABLE = "unresolvable"
    OUTCOME_CHOICES = [
        (OUTCOME_RIGHT, "Recommendation helped"),
        (OUTCOME_WRONG, "Recommendation hurt"),
        (OUTCOME_UNRESOLVABLE, "Could not be measured"),
    ]

    # ── Identity ─────────────────────────────────────────────────────
    book = models.CharField(max_length=4, choices=BOOK_CHOICES, db_index=True)
    position_id = models.IntegerField(db_index=True)
    symbol = models.CharField(max_length=40, db_index=True)
    side = models.CharField(max_length=4, blank=True)
    # Only the bot book knows an owner — portfolio.Portfolio has no user FK,
    # so a portfolio verdict is surfaced on the card and notifies nobody.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        null=True, blank=True, related_name="position_reviews",
    )
    instrument = models.ForeignKey(
        "instruments.Instrument", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="position_reviews",
    )

    # ── Layer 1: the free, deterministic evidence ────────────────────
    triggers = models.JSONField(
        default=list,
        help_text="List of {code, severity, text, values} — the reasons that fired.")
    facts = models.JSONField(
        default=dict,
        help_text="The full measured fact block the triggers were read from.")
    facts_hash = models.CharField(
        max_length=64, db_index=True, blank=True,
        help_text="Fingerprint of the BUCKETED facts — the dedupe key for the "
                  "model pass. Raw floats would change every tick and defeat it.")
    severity = models.FloatField(
        default=0.0, help_text="Max severity across fired triggers, 0..1.")

    stale_quote = models.BooleanField(
        default=False,
        help_text="True when no usable mark existed. No verdict is computed "
                  "on a stale mark — the row exists to say so out loud.")
    mark = models.DecimalField(max_digits=20, decimal_places=8,
                               null=True, blank=True)

    # R fields are NULL, never 0, when they cannot be measured (a legacy row
    # with no initial stop has no risk denominator). Upstream renders an
    # em-dash; "0.0R" would read as a scratch trade.
    unrealized_r = models.FloatField(null=True, blank=True)
    r_to_stop = models.FloatField(
        null=True, blank=True,
        help_text="R still at risk between the mark and the CURRENT stop.")
    r_to_target = models.FloatField(null=True, blank=True)
    mae_r = models.FloatField(null=True, blank=True,
                              help_text="Worst excursion since entry, in R.")
    mfe_r = models.FloatField(null=True, blank=True,
                              help_text="Best excursion since entry, in R.")
    age_hours = models.FloatField(default=0.0)

    # ── Layer 2: the answer a fired trigger paid for ─────────────────
    verdict = models.CharField(max_length=12, choices=VERDICT_CHOICES,
                               default=VERDICT_NONE, db_index=True)
    reasoning_md = models.TextField(blank=True)
    confidence = models.FloatField(null=True, blank=True)
    # Only ever accepted when it TIGHTENS. A model that widens the stop on a
    # live position is proposing more risk, and that must not be renderable.
    suggested_stop = models.DecimalField(max_digits=20, decimal_places=8,
                                          null=True, blank=True)
    take_part_pct = models.IntegerField(null=True, blank=True)

    model_used = models.CharField(max_length=80, blank=True)
    tokens_in = models.IntegerField(default=0)
    tokens_out = models.IntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    skipped_reason = models.CharField(
        max_length=200, blank=True,
        help_text="Why no model pass was made (budget, per-pass cap, same facts).")
    error = models.TextField(blank=True)

    # The falsifiable half of the claim, when one could be expressed in a
    # form brain.hypotheses already knows how to grade.
    hypothesis = models.ForeignKey(
        "brain.Hypothesis", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="position_reviews",
    )

    # ── Grading — how the recommendation itself scored ───────────────
    graded_at = models.DateTimeField(null=True, blank=True, db_index=True)
    graded_outcome = models.CharField(max_length=14, choices=OUTCOME_CHOICES,
                                       blank=True, db_index=True)
    grading_notes = models.CharField(max_length=300, blank=True)
    r_at_review = models.FloatField(null=True, blank=True)
    r_at_close = models.FloatField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["book", "position_id", "-created_at"]),
            models.Index(fields=["-created_at"]),
            models.Index(fields=["verdict", "-created_at"]),
        ]

    def __str__(self) -> str:
        return (f"<PositionReview {self.book}:{self.position_id} "
                f"{self.symbol} [{self.verdict}] "
                f"{self.created_at:%Y-%m-%d %H:%M}>")

    @property
    def position_key(self) -> str:
        """The stable handle the hover card keys its lookup on."""
        return f"{self.book}:{self.position_id}"

    @property
    def trigger_codes(self) -> list:
        return [t.get("code", "") for t in (self.triggers or [])
                if isinstance(t, dict)]

    def card_payload(self) -> dict:
        """The compact dict the position hover card renders.

        Unmeasurable numbers stay None so the card can draw an em-dash. It
        must never receive a 0 that means "we could not tell".
        """
        return {
            "review_id": self.id,
            "position_key": self.position_key,
            "symbol": self.symbol,
            "side": self.side,
            "verdict": self.verdict,
            "actionable": self.verdict in self.ACTIONABLE_VERDICTS,
            "stale_quote": self.stale_quote,
            "severity": round(float(self.severity or 0), 3),
            "confidence": (round(float(self.confidence), 3)
                           if self.confidence is not None else None),
            "unrealized_r": self.unrealized_r,
            "r_to_stop": self.r_to_stop,
            "r_to_target": self.r_to_target,
            "mae_r": self.mae_r,
            "mfe_r": self.mfe_r,
            "age_hours": round(float(self.age_hours or 0), 1),
            "triggers": [
                {"code": t.get("code", ""), "text": t.get("text", ""),
                 "severity": t.get("severity")}
                for t in (self.triggers or []) if isinstance(t, dict)
            ],
            "reasoning_md": self.reasoning_md,
            "suggested_stop": (float(self.suggested_stop)
                               if self.suggested_stop is not None else None),
            "take_part_pct": self.take_part_pct,
            "skipped_reason": self.skipped_reason,
            "as_of_iso": self.created_at.isoformat() if self.created_at else None,
        }
