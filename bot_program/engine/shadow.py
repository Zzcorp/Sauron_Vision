"""Shadow mode: compute everything as if live, but log instead of submit.

Use case: after deploying a code change, flip shadow mode on for 24-48h to
see what the bot WOULD have done without risking real money.
"""
import logging
from datetime import timedelta
from django.utils import timezone

logger = logging.getLogger(__name__)


def is_shadow_mode(config):
    """Shadow mode is on if BotConfig has a shadow_until in the future."""
    try:
        from ..models_v2 import BotShadowState
        state = BotShadowState.objects.filter(config=config).first()
        if not state or not state.shadow_until:
            return False
        return state.shadow_until > timezone.now()
    except Exception:
        return False


def enable_shadow(config, hours=24):
    """Enable shadow mode for N hours."""
    try:
        from ..models_v2 import BotShadowState
        state, _ = BotShadowState.objects.get_or_create(config=config)
        state.shadow_until = timezone.now() + timedelta(hours=hours)
        state.save()
        return state.shadow_until
    except Exception:
        return None


def log_shadow_action(config, action_type, symbol, details):
    """Log an action that would have been taken in live mode."""
    logger.info("[SHADOW] %s %s %s: %s",
                config.user.username, action_type, symbol, details)
    try:
        from ..models_v2 import BotShadowAction
        BotShadowAction.objects.create(
            config=config,
            action_type=action_type,
            symbol=symbol,
            details=details,
        )
    except Exception:
        pass
