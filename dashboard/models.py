"""Dashboard models — presets and annotations."""
from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


PRESET_CHOICES = [
    ("morning_review", "Morning Review"),
    ("active_trading", "Active Trading"),
    ("end_of_day", "End of Day"),
    ("custom", "Custom"),
]

MORNING_REVIEW_CONFIG = {
    "sections": [
        "section-portfolio",
        "section-markets",
        "section-news",
        "section-sessions",
        "section-signals",
    ]
}

ACTIVE_TRADING_CONFIG = {
    "sections": [
        "section-portfolio",
        "section-signals",
        "section-strategies",
        "section-bot",
        "section-performance",
        "section-automation",
    ]
}

END_OF_DAY_CONFIG = {
    "sections": [
        "section-performance",
        "section-exposure",
        "section-best-trades",
        "section-strategies",
        "section-ai-tasks",
        "section-portfolio",
    ]
}

ALL_CONFIG = {
    "sections": [
        "section-portfolio",
        "section-markets",
        "section-automation",
        "section-performance",
        "section-exposure",
        "section-signals",
        "section-strategies",
        "section-bot",
        "section-news",
        "section-ai-tasks",
        "section-sessions",
        "section-best-trades",
    ]
}


class DashboardPreset(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="dashboard_presets")
    name = models.CharField(max_length=50)
    preset_type = models.CharField(max_length=20, choices=PRESET_CHOICES, default="custom")
    layout_config = models.JSONField(default=dict)
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["preset_type", "name"]

    def __str__(self):
        return f"{self.user.username} — {self.name}"

    @classmethod
    def get_or_create_defaults(cls, user):
        """Ensure the three default presets exist for this user, and refresh
        their layout_config to the canonical values (so updates to the section
        IDs propagate to existing rows)."""
        defaults = [
            ("Morning Review", "morning_review", MORNING_REVIEW_CONFIG),
            ("Active Trading", "active_trading", ACTIVE_TRADING_CONFIG),
            ("End of Day", "end_of_day", END_OF_DAY_CONFIG),
        ]
        for name, ptype, config in defaults:
            obj, _ = cls.objects.get_or_create(
                user=user,
                preset_type=ptype,
                defaults={"name": name, "layout_config": config, "is_active": False},
            )
            if obj.layout_config != config:
                obj.layout_config = config
                obj.save(update_fields=["layout_config"])

    @classmethod
    def get_active_for_user(cls, user):
        return cls.objects.filter(user=user, is_active=True).first()


ANNOTATION_TYPE_CHOICES = [
    ("signal", "Signal Note"),
    ("instrument", "Instrument Note"),
    ("strategy", "Strategy Note"),
    ("position", "Position"),
    ("chart", "Chart"),
    ("general", "General Note"),
]


class UserAnnotation(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="annotations")
    annotation_type = models.CharField(max_length=20, choices=ANNOTATION_TYPE_CHOICES, default="general")
    target_id = models.IntegerField(null=True, blank=True)
    target_symbol = models.CharField(max_length=20, blank=True)
    content = models.TextField()
    color = models.CharField(max_length=7, default="#ffeb3b")
    pinned = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-pinned", "-created_at"]

    def __str__(self):
        return f"{self.user.username} [{self.annotation_type}] {self.content[:40]}"
