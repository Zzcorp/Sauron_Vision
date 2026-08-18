
from .platform_control import PlatformComponent  # noqa

from .market_config import MarketConfig  # noqa

from .audit import AuditLog  # noqa

from .compliance import TradingRestriction  # noqa

from .presence import UserPresence  # noqa

from django.db import models


class FeatureFlag(models.Model):
    """A simple feature-flag record stored in the database.

    Use the helpers in ``core.feature_flags`` rather than querying this model
    directly — those helpers add a 60-second cache layer.
    """

    name = models.CharField(max_length=100, unique=True)
    enabled = models.BooleanField(default=False)
    description = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        state = "on" if self.enabled else "off"
        return f"{self.name} [{state}]"
