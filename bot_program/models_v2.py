"""Money-protection layer models: heartbeats, circuit state, shadow, overrides."""
from django.db import models
from django.utils import timezone
from .models import BotConfig


class BotHeartbeat(models.Model):
    """One row per BotConfig, updated on every runner tick."""
    config = models.OneToOneField(BotConfig, on_delete=models.CASCADE,
                                   related_name="heartbeat")
    last_seen = models.DateTimeField(default=timezone.now, db_index=True)
    status = models.CharField(max_length=16, default="OK")
    note = models.CharField(max_length=200, blank=True)
    tick_count = models.IntegerField(default=0)

    def __str__(self):
        return f"HB {self.config.user.username} {self.status} @ {self.last_seen}"


class BotCircuitState(models.Model):
    """Tracks circuit-breaker state per config."""
    config = models.OneToOneField(BotConfig, on_delete=models.CASCADE,
                                   related_name="circuit_state")
    last_error_at = models.DateTimeField(null=True, blank=True)
    last_error_burst_started = models.DateTimeField(null=True, blank=True)
    error_count_in_burst = models.IntegerField(default=0)
    halted_until = models.DateTimeField(null=True, blank=True)
    halt_reason = models.CharField(max_length=200, blank=True)

    def __str__(self):
        return f"Circuit {self.config.user.username}"


class BotShadowState(models.Model):
    """Shadow mode state for a config (compute, don't submit)."""
    config = models.OneToOneField(BotConfig, on_delete=models.CASCADE,
                                   related_name="shadow_state")
    shadow_until = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Shadow {self.config.user.username} until {self.shadow_until}"


class BotShadowAction(models.Model):
    """Log of actions the bot would have taken in shadow mode."""
    config = models.ForeignKey(BotConfig, on_delete=models.CASCADE,
                                related_name="shadow_actions")
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    action_type = models.CharField(max_length=20)   # ENTRY / EXIT / SL / TP
    symbol = models.CharField(max_length=20)
    details = models.JSONField(default=dict)

    class Meta:
        ordering = ["-created_at"]


class BotSymbolOverride(models.Model):
    """Per-symbol parameter overrides for a BotConfig.

    Lets BTC and a memecoin not share the same stop_loss_pct.
    """
    config = models.ForeignKey(BotConfig, on_delete=models.CASCADE,
                                related_name="symbol_overrides")
    symbol = models.CharField(max_length=20)
    position_size_pct = models.FloatField(null=True, blank=True)
    stop_loss_pct = models.FloatField(null=True, blank=True)
    take_profit_pct = models.FloatField(null=True, blank=True)
    trailing_stop_pct = models.FloatField(null=True, blank=True)
    leverage = models.FloatField(null=True, blank=True)
    enabled = models.BooleanField(default=True)

    class Meta:
        unique_together = [("config", "symbol")]

    def __str__(self):
        return f"{self.config.user.username} {self.symbol} override"

    def merged_params(self):
        """Return effective params, falling back to BotConfig defaults."""
        return {
            "position_size_pct": self.position_size_pct or self.config.position_size_pct,
            "stop_loss_pct": self.stop_loss_pct or self.config.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct or self.config.take_profit_pct,
            "trailing_stop_pct": self.trailing_stop_pct or self.config.trailing_stop_pct,
            "leverage": self.leverage or self.config.leverage,
        }
