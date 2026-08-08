"""AI agent task logging."""
from django.db import models
from django.utils import timezone


class AgentTask(models.Model):
    AGENT_CHOICES = [
        ("news_analyst", "News Analyst"),
        ("strategy_advisor", "Strategy Advisor"),
        ("weekly_reviewer", "Weekly Reviewer"),
        ("anomaly_detector", "Anomaly Detector"),
        ("earnings_analyst", "Earnings Analyst"),
        ("macro_interpreter", "Macro Interpreter"),
        ("monday_planner", "Monday Planner"),
    ]

    agent = models.CharField(max_length=30, choices=AGENT_CHOICES)
    provider = models.CharField(max_length=20)
    model = models.CharField(max_length=50)

    prompt_summary = models.TextField()
    input_tokens = models.IntegerField(default=0)
    output_tokens = models.IntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)

    response_summary = models.TextField(blank=True)
    structured_output = models.JSONField(default=dict)

    success = models.BooleanField(default=True)
    error = models.TextField(blank=True)
    duration_seconds = models.FloatField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.agent}] {self.provider}/{self.model} — {'OK' if self.success else 'FAIL'}"


class AIMemory(models.Model):
    """Persistent memory entries for AI agents."""
    agent = models.CharField(max_length=30, db_index=True)
    category = models.CharField(max_length=50)
    content = models.TextField()
    confidence = models.FloatField(default=0.5)
    source_task_id = models.IntegerField(null=True, blank=True)
    valid_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-confidence", "-created_at"]

    def __str__(self):
        return f"[{self.agent}] {self.category}: {self.content[:80]}"

    @classmethod
    def remember(cls, agent, category, content, confidence=0.5, source_task_id=None, valid_days=None):
        from django.utils import timezone as tz
        from datetime import timedelta
        valid_until = tz.now() + timedelta(days=valid_days) if valid_days else None
        return cls.objects.create(agent=agent, category=category, content=content, confidence=confidence, source_task_id=source_task_id, valid_until=valid_until)

    @classmethod
    def recall(cls, agent, category=None, limit=10):
        from django.utils import timezone as tz
        qs = cls.objects.filter(agent=agent)
        if category:
            qs = qs.filter(category=category)
        qs = qs.filter(models.Q(valid_until__isnull=True) | models.Q(valid_until__gte=tz.now()))
        return list(qs[:limit].values("category", "content", "confidence"))

    @classmethod
    def get_context_for_agent(cls, agent, max_chars=8000):
        memories = cls.recall(agent, limit=20)
        if not memories:
            return ""
        lines = ["## Agent Memory\n"]
        total = 0
        for m in memories:
            line = f"- [{m['category']}] {m['content']}"
            if total + len(line) > max_chars:
                break
            lines.append(line)
            total += len(line)
        return "\n".join(lines)


class TradeJournalEntry(models.Model):
    """Phase-3: AI-generated journal entry for a closed Signal, BotTrade, or Position.

    Linked via three optional FKs — exactly one of signal / bot_trade / position
    is expected to be set per entry (enforced by `clean()`, not the DB).
    """
    GRADE_CHOICES = [(g, g) for g in ["A", "B", "C", "D", "F", "N/A"]]

    signal = models.ForeignKey(
        "signals.Signal", on_delete=models.CASCADE, null=True, blank=True,
        related_name="journal_entries",
    )
    bot_trade = models.ForeignKey(
        "bot_program.BotTrade", on_delete=models.CASCADE, null=True, blank=True,
        related_name="journal_entries",
    )
    position = models.ForeignKey(
        "portfolio.Position", on_delete=models.CASCADE, null=True, blank=True,
        related_name="journal_entries",
    )

    grade = models.CharField(max_length=4, choices=GRADE_CHOICES, default="N/A")
    summary = models.TextField(blank=True)
    key_takeaway = models.CharField(max_length=400, blank=True)
    lessons = models.JSONField(default=list)
    tags = models.JSONField(default=list)
    emotional_state = models.CharField(max_length=20, blank=True)

    structured_output = models.JSONField(default=dict)
    agent_task = models.ForeignKey(
        AgentTask, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="journal_entries",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"]),
            models.Index(fields=["grade", "-created_at"]),
        ]

    def __str__(self):
        target = self.signal or self.bot_trade or self.position
        return f"[{self.grade}] journal: {target}"


class DecayInvestigation(models.Model):
    """Phase-3: AI-generated investigation when a rule's expectancy decays."""
    rule_name = models.CharField(max_length=100, db_index=True)
    recent_expectancy = models.FloatField(null=True, blank=True)
    baseline_expectancy = models.FloatField(null=True, blank=True)
    recent_n = models.IntegerField(default=0)
    baseline_n = models.IntegerField(default=0)

    hypothesis = models.TextField(blank=True)
    contributing_factors = models.JSONField(default=list)
    recommended_action = models.CharField(max_length=400, blank=True)

    structured_output = models.JSONField(default=dict)
    agent_task = models.ForeignKey(
        AgentTask, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="decay_investigations",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["rule_name", "-created_at"]),
        ]

    def __str__(self):
        return f"decay[{self.rule_name}]: {self.recommended_action[:50]}"


class AgentPrediction(models.Model):
    """Track individual agent predictions for calibration.

    Phase-6 calibration loop: every prediction has an `expected_resolution_at`
    deadline and (optionally) a linked Signal / RuleAction. A nightly resolver
    looks up ground truth and stamps `actual_value`, `was_correct`, and `score`
    (continuous; e.g. realized_r for trade predictions).

    The `score` field is the unified granular metric — `was_correct` is the
    bool reduction for backwards compatibility.
    """
    agent = models.CharField(max_length=50, db_index=True)
    prediction_type = models.CharField(max_length=30)  # direction | trade_outcome | decay_continues | ...
    instrument_symbol = models.CharField(max_length=20, blank=True)
    predicted_value = models.CharField(max_length=100)
    actual_value = models.CharField(max_length=100, blank=True)
    confidence = models.FloatField(default=0.5,
                                    help_text="Probability assigned to predicted_value (0.0–1.0).")
    was_correct = models.BooleanField(null=True)  # null = not yet evaluated
    score = models.FloatField(null=True, blank=True,
                              help_text="Granular correctness; for trade outcomes = realized_r.")
    evaluation_notes = models.TextField(blank=True)

    # Phase-6: ground-truth resolution
    expected_resolution_at = models.DateTimeField(null=True, blank=True, db_index=True,
                                                   help_text="Earliest time ground truth is expected.")
    linked_signal = models.ForeignKey(
        "signals.Signal", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="agent_predictions",
    )
    linked_rule_action = models.ForeignKey(
        "signals.RuleAction", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="agent_predictions",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    evaluated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = 'ai_agents'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['agent', '-created_at']),
            models.Index(fields=['was_correct', 'expected_resolution_at']),
        ]

    def __str__(self):
        status = 'correct' if self.was_correct else ('wrong' if self.was_correct is False else 'pending')
        return f"{self.agent} {self.prediction_type}: {self.predicted_value} [{status}]"


class AIModelSetting(models.Model):
    """Runtime model/effort selection, editable without a redeploy.

    One row per tier ("fast"/"balanced"/"deep") or per agent name. Agent
    rows win over tier rows; a tier row wins over the env var; the env var
    wins over the code default. See ai_agents.catalog for the resolver.
    """

    SCOPE_CHOICES = [("tier", "Tier"), ("agent", "Agent")]

    scope = models.CharField(max_length=8, choices=SCOPE_CHOICES)
    # "fast"/"balanced"/"deep" for tier rows; the agent_name for agent rows.
    key = models.CharField(max_length=60)
    model_id = models.CharField(max_length=60, blank=True)
    # Blank = use the tier default for models that support effort.
    effort = models.CharField(max_length=8, blank=True, default="")
    updated_by = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="ai_model_settings",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "ai_agents"
        unique_together = [("scope", "key")]
        ordering = ["scope", "key"]

    def __str__(self):
        return f"{self.scope}:{self.key} → {self.model_id or '(default)'}"
