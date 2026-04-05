"""AI memory system — agents learn from past performance."""
from django.db import models
from django.utils import timezone


class AIMemory(models.Model):
    """Persistent memory entries for AI agents."""
    agent = models.CharField(max_length=30, db_index=True)
    category = models.CharField(max_length=50)  # "lesson", "pattern", "preference", "regime"
    content = models.TextField()
    confidence = models.FloatField(default=0.5)  # 0-1, how confident is this memory
    source_task_id = models.IntegerField(null=True)  # Which AgentTask created this
    valid_until = models.DateTimeField(null=True)  # Optional expiry
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-confidence", "-created_at"]

    def __str__(self):
        return f"[{self.agent}] {self.category}: {self.content[:80]}"

    @classmethod
    def remember(cls, agent, category, content, confidence=0.5, source_task_id=None, valid_days=None):
        """Store a new memory."""
        valid_until = None
        if valid_days:
            valid_until = timezone.now() + timezone.timedelta(days=valid_days)
        return cls.objects.create(
            agent=agent,
            category=category,
            content=content,
            confidence=confidence,
            source_task_id=source_task_id,
            valid_until=valid_until,
        )

    @classmethod
    def recall(cls, agent, category=None, limit=10):
        """Retrieve memories for an agent, optionally filtered by category."""
        qs = cls.objects.filter(agent=agent)
        if category:
            qs = qs.filter(category=category)
        # Exclude expired memories
        qs = qs.filter(
            models.Q(valid_until__isnull=True) | models.Q(valid_until__gte=timezone.now())
        )
        return list(qs[:limit].values("category", "content", "confidence"))

    @classmethod
    def get_context_for_agent(cls, agent, max_tokens_estimate=2000):
        """Build a context string from memories for injection into agent prompts."""
        memories = cls.recall(agent, limit=20)
        if not memories:
            return ""

        lines = ["\n## Agent Memory (learned from past sessions)\n"]
        char_count = 0
        for mem in memories:
            line = f"- [{mem['category']}] (confidence: {mem['confidence']:.1f}) {mem['content']}"
            if char_count + len(line) > max_tokens_estimate * 4:
                break
            lines.append(line)
            char_count += len(line)

        return "\n".join(lines)
