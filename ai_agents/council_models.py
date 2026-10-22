"""THE COUNCIL's record (2026-10-08, ai_agents/agents/council.py).

Ten voices argue a live trade: the Executioner and the Champion (the
trade debate, ai_agents/agents/trade_debate.py) and eight shadow voices,
the Emperor in the chair. What they said is kept in three tables, not in
a trade row's metadata, because:

  - a candidate refused after the debate, and a ticket nobody took, have
    no trade row at all, and their voices are graded all the same;
  - a voice's weight is a per-voice query over its graded calls;
  - "A recommendation nobody can look up later is an opinion"
    (brain/position_review_models.py).

CouncilSession  one sitting: the trade as argued, the regime recorded at
                the sitting, the frozen brief, the weights the Emperor read,
                the Hand of the Emperor and the people's mood at the
                sitting (2026-10-16), and, once graded, the truth it was
                judged against. `venue` "demo" marks a debate argued on a
                rehearsal client: closed ungraded, never real money.
CouncilVoice    one voice in one sitting: its status (asked, spoke, late,
                silent, copied), its verdict and its parsed answer verbatim.
CouncilClaim    the only thing graded: one claim per row, so a voice may
                carry a probability and a specialty claim side by side.

Nothing in sizing, the gates, the debate's binding or any order path
reads these tables (tests/test_council_shadow.py pins it).
"""
from django.conf import settings
from django.db import models


class CouncilSession(models.Model):
    ORIGIN_BOT, ORIGIN_TICKET, ORIGIN_MARKET = "bot", "ticket", "market"
    ORIGIN_CHOICES = [(ORIGIN_BOT, "A bot's order"),
                      (ORIGIN_TICKET, "A hand ticket"),
                      # reserved for council-2, the morning council
                      (ORIGIN_MARKET, "The market")]

    RECORD, QUEUED, SITTING, DONE, PARTIAL, SILENT = (
        "record", "queued", "sitting", "done", "partial", "silent")
    STATUS_CHOICES = [(RECORD, "Recorded"), (QUEUED, "Queued"),
                      (SITTING, "Sitting"), (DONE, "Done"),
                      (PARTIAL, "Partial"), (SILENT, "Silent")]

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    origin = models.CharField(max_length=8, choices=ORIGIN_CHOICES)
    venue = models.CharField(max_length=8, default="live")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES,
                              default=RECORD)
    why = models.CharField(max_length=300, blank=True, default="")

    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                             on_delete=models.SET_NULL,
                             related_name="council_sessions")
    config = models.ForeignKey("bot_program.AssetBotConfig", null=True,
                               blank=True, on_delete=models.SET_NULL,
                               related_name="council_sessions")
    trade = models.ForeignKey("bot_program.AssetBotTrade", null=True,
                              blank=True, on_delete=models.SET_NULL,
                              related_name="council_sessions")
    #: How the trade was linked: hook (after the send), meta (the row's
    #: metadata["debate"]["council_id"]), body (the ticket's execute body)
    #: or time (the ticket's time-window fallback).
    linked_by = models.CharField(max_length=8, blank=True, default="")
    #: A ticket only: whether the executed stop and target equal the ones
    #: the council argued (within 0.1%).
    levels_match = models.BooleanField(null=True, blank=True)

    symbol = models.CharField(max_length=40)
    asset_class = models.CharField(max_length=12, blank=True, default="")
    side = models.CharField(max_length=4, blank=True, default="")
    rule_name = models.CharField(max_length=100, blank=True, default="")
    entry = models.FloatField(null=True, blank=True)
    stop = models.FloatField(null=True, blank=True)
    target = models.FloatField(null=True, blank=True)
    qty = models.FloatField(null=True, blank=True)
    value_per_unit = models.FloatField(null=True, blank=True)
    cost_fraction = models.FloatField(default=0.0)
    horizon_hours = models.FloatField(default=168.0)

    regime = models.CharField(max_length=20, blank=True, default="unknown")
    regime_confidence = models.FloatField(null=True, blank=True)
    regime_report_id = models.IntegerField(null=True, blank=True)

    facts = models.JSONField(default=dict, blank=True)
    brief = models.TextField(blank=True, default="")
    extras = models.TextField(blank=True, default="")
    #: The weights the Emperor read: {voice: {factor, lane, n, brier,
    #: rung, reason}}.
    weights = models.JSONField(default=dict, blank=True)
    #: THE HAND OF THE EMPEROR at this sitting (2026-10-16): {cell, voice,
    #: name, factor, n, brier, reference, reason, why_empty, side,
    #: trusted, trusted_why}; {} before the seat existed, or on a record
    #: that never sat.
    hand = models.JSONField(default=dict, blank=True)
    #: THE PEOPLE'S MOOD at this sitting (ai_agents/council_mood.py):
    #: steady | uneasy | restless | afraid | unmeasured; "" = not read (a
    #: debate's record, or a sitting before the gauge).
    mood = models.CharField(max_length=10, blank=True, default="")
    #: Its inputs as read: R, fractions, counts and words; never money.
    mood_read = models.JSONField(default=dict, blank=True)

    # The benchmark rows (does weighting help?): the voices' plain
    # average p_work, the record-weighted average, and the Emperor's own.
    p_mean = models.FloatField(null=True, blank=True)
    p_weighted = models.FloatField(null=True, blank=True)
    p_chair = models.FloatField(null=True, blank=True)

    # The truth the sitting was graded against.
    truth = models.CharField(max_length=10, blank=True, default="")
    truth_r = models.FloatField(null=True, blank=True)
    replay_r = models.FloatField(null=True, blank=True)
    replay_outcome = models.CharField(max_length=12, blank=True, default="")
    y = models.SmallIntegerField(null=True, blank=True)
    graded_at = models.DateTimeField(null=True, blank=True)
    grade_notes = models.CharField(max_length=300, blank=True, default="")

    finished_at = models.DateTimeField(null=True, blank=True)
    schema_version = models.SmallIntegerField(default=1)

    class Meta:
        app_label = "ai_agents"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["origin", "-created_at"],
                         name="council_s_origin_idx"),
            models.Index(fields=["config", "symbol", "side", "-created_at"],
                         name="council_s_repeat_idx"),
            models.Index(fields=["user", "-created_at"],
                         name="council_s_user_idx"),
            models.Index(fields=["graded_at", "created_at"],
                         name="council_s_grade_idx"),
        ]

    def __str__(self):
        return (f"council #{self.pk} {self.origin} {self.symbol} "
                f"{self.side} [{self.status}]")


class CouncilVoice(models.Model):
    ASKED, SPOKE, LATE, SILENT, COPIED = ("asked", "spoke", "late",
                                          "silent", "copied")
    STATUS_CHOICES = [(ASKED, "Asked"), (SPOKE, "Spoke"), (LATE, "Late"),
                      (SILENT, "Silent"), (COPIED, "Copied")]

    session = models.ForeignKey(CouncilSession, on_delete=models.CASCADE,
                                related_name="voices")
    voice = models.CharField(max_length=16)
    agent = models.CharField(max_length=30, blank=True, default="")
    wave = models.SmallIntegerField(default=1)
    status = models.CharField(max_length=8, choices=STATUS_CHOICES,
                              default=ASKED)
    why = models.CharField(max_length=200, blank=True, default="")
    verdict = models.CharField(max_length=20, blank=True, default="")
    p_work = models.FloatField(null=True, blank=True)
    conviction = models.FloatField(null=True, blank=True)
    #: The parsed answer, verbatim.
    answer = models.JSONField(default=dict, blank=True)
    model = models.CharField(max_length=60, blank=True, default="")
    #: The weight the Emperor read for this voice, and why.
    weight_seen = models.FloatField(null=True, blank=True)
    weight_reason = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    answered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "ai_agents"
        ordering = ["wave", "id"]
        constraints = [
            models.UniqueConstraint(fields=["session", "voice"],
                                    name="council_one_voice_per_sitting"),
        ]

    def __str__(self):
        return f"{self.voice} [{self.status}] {self.verdict}"


class CouncilClaim(models.Model):
    """One graded claim. `kind` "work" and "attack" are the WEIGHT claims
    (the common event every voice is weighted on); every other kind is a
    specialty claim, shown beside the weight and never part of it."""

    WEIGHT_KINDS = ("work", "attack")
    KIND_CHOICES = [(k, k) for k in ("work", "attack", "stance", "boldness",
                                     "trigger", "fix", "touch", "direction",
                                     "theory", "battle")]
    PENDING, RIGHT, WRONG, UNRESOLVABLE, UNGRADED, REFUSED = (
        "pending", "right", "wrong", "unresolvable", "ungraded", "refused")
    GRADE_CHOICES = [(g, g) for g in (PENDING, RIGHT, WRONG, UNRESOLVABLE,
                                      UNGRADED, REFUSED)]

    session = models.ForeignKey(CouncilSession, on_delete=models.CASCADE,
                                related_name="claims")
    voice = models.ForeignKey(CouncilVoice, on_delete=models.CASCADE,
                              related_name="claims")
    # Copied from the session and the voice, so the weight query needs no
    # join.
    voice_key = models.CharField(max_length=16)
    regime = models.CharField(max_length=20, blank=True, default="unknown")
    asset_class = models.CharField(max_length=12, blank=True, default="")
    venue = models.CharField(max_length=8, default="live")
    origin = models.CharField(max_length=8, blank=True, default="")

    kind = models.CharField(max_length=12, choices=KIND_CHOICES)
    stance = models.CharField(max_length=8, blank=True, default="")
    symbol = models.CharField(max_length=40, blank=True, default="")
    p = models.FloatField(null=True, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    prediction = models.ForeignKey("ai_agents.AgentPrediction", null=True,
                                   blank=True, on_delete=models.SET_NULL,
                                   related_name="council_claims")
    hypothesis = models.ForeignKey("brain.Hypothesis", null=True, blank=True,
                                   on_delete=models.SET_NULL,
                                   related_name="council_claims")

    grade = models.CharField(max_length=12, choices=GRADE_CHOICES,
                             default=PENDING, db_index=True)
    y = models.SmallIntegerField(null=True, blank=True)
    brier = models.FloatField(null=True, blank=True)
    r = models.FloatField(null=True, blank=True)
    value_r = models.FloatField(null=True, blank=True)
    grade_notes = models.CharField(max_length=300, blank=True, default="")
    graded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "ai_agents"
        ordering = ["id"]
        indexes = [
            models.Index(fields=["voice_key", "venue", "regime",
                                 "asset_class", "kind"],
                         name="council_c_weight_idx"),
            models.Index(fields=["grade", "created_at"],
                         name="council_c_grade_idx"),
        ]

    def __str__(self):
        return f"{self.voice_key} {self.kind} [{self.grade}]"
