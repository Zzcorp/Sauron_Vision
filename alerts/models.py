"""Alert and newsletter models."""
from django.db import models
from django.contrib.auth.models import User


class AlertRule(models.Model):
    """User's personal signal alert rules."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="alert_rules")
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)

    # Trigger conditions
    instrument_symbol = models.CharField(max_length=20, blank=True)  # empty = all instruments
    asset_class = models.CharField(max_length=20, blank=True)  # empty = all classes
    min_score = models.FloatField(default=0.5)
    direction = models.CharField(max_length=10, blank=True)  # bullish, bearish, or empty=both
    urgency = models.CharField(max_length=10, blank=True)  # critical, high, medium, low

    # Channels
    notify_telegram = models.BooleanField(default=True)
    notify_email = models.BooleanField(default=False)
    notify_whatsapp = models.BooleanField(default=False)
    notify_sms = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.username}: {self.name}"


class Newsletter(models.Model):
    """Admin-created newsletter for distribution."""
    FREQ_CHOICES = [
        ("weekly", "Weekly"),
        ("monthly", "Monthly"),
        ("adhoc", "Ad-hoc"),
    ]
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("ai_generated", "AI Generated — Pending Review"),
        ("approved", "Approved"),
        ("sent", "Sent"),
        ("failed", "Failed"),
    ]

    title = models.CharField(max_length=200)
    frequency = models.CharField(max_length=10, choices=FREQ_CHOICES, default="weekly")
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default="draft")

    # Content
    content_markdown = models.TextField(blank=True)
    content_html = models.TextField(blank=True)
    ai_prompt = models.TextField(blank=True, help_text="Prompt used to generate content")

    # Distribution
    send_telegram = models.BooleanField(default=True)
    send_email = models.BooleanField(default=True)
    send_whatsapp = models.BooleanField(default=False)

    # Targeting
    target_all_users = models.BooleanField(default=True)
    target_markets = models.JSONField(default=list, blank=True)  # ["stock", "forex", "crypto"]

    # Meta
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    recipients_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.status}] {self.title}"


class UserNotificationPrefs(models.Model):
    """User notification channel preferences."""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="notification_prefs")

    # Channels
    telegram_chat_id = models.CharField(max_length=50, blank=True)
    whatsapp_number = models.CharField(max_length=20, blank=True)
    email_notifications = models.BooleanField(default=True)
    sms_number = models.CharField(max_length=20, blank=True)

    # What to receive
    receive_signals = models.BooleanField(default=True)
    receive_strategies = models.BooleanField(default=True)
    receive_news_alerts = models.BooleanField(default=True)
    receive_portfolio_alerts = models.BooleanField(default=True)
    receive_weekly_newsletter = models.BooleanField(default=True)
    receive_monthly_newsletter = models.BooleanField(default=True)

    # Quiet hours (UTC)
    quiet_start = models.TimeField(null=True, blank=True)
    quiet_end = models.TimeField(null=True, blank=True)

    class Meta:
        verbose_name_plural = "User notification preferences"

    def __str__(self):
        return f"{self.user.username} notification prefs"


class Notification(models.Model):
    """In-app notification for the bell dropdown."""
    TYPES = [
        ("signal", "New Signal"),
        ("strategy", "Strategy Update"),
        ("news", "Breaking News"),
        ("portfolio", "Portfolio Alert"),
        ("system", "System Message"),
        ("newsletter", "Newsletter"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    notification_type = models.CharField(max_length=20, choices=TYPES)
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    url = models.CharField(max_length=200, blank=True)  # Link to the relevant page
    read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{'READ' if self.read else 'NEW'}] {self.title}"

    @classmethod
    def create_for_all(cls, notification_type, title, body="", url=""):
        """Create a notification for all active users."""
        from django.contrib.auth.models import User as U
        notifs = []
        for user in U.objects.filter(is_active=True):
            notifs.append(cls(
                user=user, notification_type=notification_type,
                title=title, body=body, url=url,
            ))
        cls.objects.bulk_create(notifs)
        return len(notifs)

    @classmethod
    def create_for_user(cls, user, notification_type, title, body="", url=""):
        """Create a notification for a specific user."""
        return cls.objects.create(
            user=user, notification_type=notification_type,
            title=title, body=body, url=url,
        )

    @classmethod
    def unread_count(cls, user):
        return cls.objects.filter(user=user, read=False).count()

    @classmethod
    def recent(cls, user, limit=15):
        return cls.objects.filter(user=user).order_by("-created_at")[:limit]
