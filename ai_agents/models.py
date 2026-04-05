"""AI agent task logging."""
from django.db import models


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
