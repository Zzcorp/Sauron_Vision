
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


# ── the switch PIN's login mark (core/switch_pin.py, 2026-10-23) ────────
# Connected here because this module is loaded with the app: every login
# stamps the session with a keyed mark of the PIN it logged in under, and
# turning a live-money switch on refuses a session whose mark no longer
# matches (a PIN set or changed after login, by any door).
from django.contrib.auth.signals import user_logged_in  # noqa: E402
from django.dispatch import receiver  # noqa: E402


@receiver(user_logged_in, dispatch_uid="core.switch_pin.login_mark")
def _mark_the_login_pin(sender, request, user, **kwargs):
    from core.switch_pin import stamp_login_mark
    stamp_login_mark(request, user)
