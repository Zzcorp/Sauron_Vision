"""Phase 50 — Research conversation models.

User-facing chat with Sauron. Read-only RAG over BrainReports + Knowledge
graph + Hypotheses + Briefings + EarningsReviews. No tool calls, no state
mutation — the agent ANSWERS, it doesn't act.

One ongoing conversation per user (single thread; restart with the
"New conversation" button which archives + starts fresh).
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import models


User = get_user_model()


class ResearchConversation(models.Model):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="research_conversations",
    )
    title = models.CharField(max_length=200, blank=True,
                              help_text="Auto-generated from the first user message.")
    is_active = models.BooleanField(default=True, db_index=True,
                                     help_text="Only one active conversation per user.")
    started_at = models.DateTimeField(auto_now_add=True, db_index=True)
    last_message_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-last_message_at"]
        indexes = [
            models.Index(fields=["user", "-last_message_at"]),
            models.Index(fields=["user", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"<Conversation #{self.id} {self.user.username} '{self.title[:40]}'>"


class ResearchMessage(models.Model):
    ROLE_USER = "user"
    ROLE_ASSISTANT = "assistant"
    ROLE_CHOICES = [(ROLE_USER, "User"), (ROLE_ASSISTANT, "Assistant")]

    conversation = models.ForeignKey(
        ResearchConversation, on_delete=models.CASCADE, related_name="messages",
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    content = models.TextField()

    # Assistant-only metadata.
    model_used = models.CharField(max_length=80, blank=True)
    tokens_in = models.IntegerField(default=0)
    tokens_out = models.IntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    error = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["conversation", "created_at"]),
        ]

    def __str__(self) -> str:
        prefix = "👤" if self.role == self.ROLE_USER else "🦅"
        return f"{prefix} {self.content[:60]}"
