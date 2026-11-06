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


class RailDeparture(models.Model):
    """Why a signal left the signal rail (2026-11-06).

    DISPLAY ONLY: read by dashboard.signal_rail and its two views, and by
    nothing in the engine, the bots, the alerts or the take-trade path
    (tests/test_rail_lifecycle.py greps for it). The rail's lifecycle is
    computed BESIDE the engine's: a departure here never touches the Signal
    row, which stays active, voting and takeable exactly as the engine
    keeps it.

    user=None  the rail's own lifecycle — one row per signal, written the
               first time the rail sees the reason, with the reason in
               words frozen at that moment (a stop that was crossed stays
               crossed on the rail, whatever the price does next).
    user set   that operator's own PASS or take, so a pass made on one
               browser holds on every other.

    The age departure is never stored: it is a clock, re-read on every
    render, so a scanner re-match legitimately keeps a reused signal on.
    """

    REASONS = [
        ("superseded", "Replaced by a newer signal from its own rule"),
        ("stop_crossed", "Price at or through its stop"),
        ("target_reached", "Price at or through its target"),
        ("chased", "Reward:risk from the mark under the ticket's line"),
        ("rule_paused", "Its rule is paused"),
        ("rule_demoted", "Its rule was demoted after it"),
        ("rule_losing", "Its rule is a measured loser"),
        ("rule_losing_live", "Its rule loses real money on its class"),
        ("passed", "Passed by the operator"),
        ("taken", "Taken by the operator"),
    ]

    signal = models.ForeignKey("signals.Signal", on_delete=models.CASCADE,
                               related_name="rail_departures")
    user = models.ForeignKey(User, null=True, blank=True,
                             on_delete=models.CASCADE, related_name="+")
    reason = models.CharField(max_length=24, choices=REASONS)
    words = models.CharField(max_length=300)
    mark = models.DecimalField(max_digits=20, decimal_places=8, null=True,
                               blank=True)
    departed_at = models.DateTimeField(db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["signal"], condition=models.Q(user__isnull=True),
                name="rail_departure_one_lifecycle"),
            models.UniqueConstraint(
                fields=["signal", "user"],
                condition=models.Q(user__isnull=False),
                name="rail_departure_one_per_user"),
        ]

    def __str__(self):
        who = "rail" if self.user_id is None else f"user {self.user_id}"
        return f"RailDeparture[{self.signal_id} {self.reason} by {who}]"
