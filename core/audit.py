"""Audit trail — log every significant action."""
from django.db import models
from django.contrib.auth.models import User


class AuditLog(models.Model):
    """Immutable audit log entry."""
    ACTION_TYPES = [
        ('bot_toggle', 'Bot Enabled/Disabled'),
        ('trade_open', 'Trade Opened'),
        ('trade_close', 'Trade Closed'),
        ('strategy_approve', 'Strategy Approved'),
        ('strategy_reject', 'Strategy Rejected'),
        ('kill_switch', 'Kill Switch Activated'),
        ('config_change', 'Configuration Changed'),
        ('login', 'User Login'),
        ('alert_triggered', 'Alert Triggered'),
        ('position_open', 'Position Opened'),
        ('position_close', 'Position Closed'),
    ]

    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='audit_logs')
    action = models.CharField(max_length=30, choices=ACTION_TYPES)
    target_type = models.CharField(max_length=50, blank=True)  # e.g., 'BotConfig', 'Strategy'
    target_id = models.IntegerField(null=True, blank=True)
    description = models.TextField()
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['action', '-created_at']),
        ]

    def __str__(self):
        return f"[{self.action}] {self.user} — {self.description[:50]}"

    @classmethod
    def log(cls, user, action, description, target_type='', target_id=None, ip_address=None, metadata=None):
        """Create an audit log entry."""
        return cls.objects.create(
            user=user, action=action, description=description,
            target_type=target_type, target_id=target_id,
            ip_address=ip_address, metadata=metadata or {},
        )
