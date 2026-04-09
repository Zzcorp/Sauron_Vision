"""Bot heartbeat: writes a row every loop, alerts on staleness."""
from datetime import timedelta
from django.utils import timezone


def write_heartbeat(config, status="OK", note=""):
    """Write or update the heartbeat row for this config."""
    try:
        from ..models_v2 import BotHeartbeat
        hb, _ = BotHeartbeat.objects.get_or_create(config=config)
        hb.last_seen = timezone.now()
        hb.status = status
        hb.note = note[:200]
        hb.tick_count = (hb.tick_count or 0) + 1
        hb.save()
        return hb
    except Exception:
        return None


def heartbeat_age_seconds(config):
    """Seconds since the last heartbeat. Returns None if no row."""
    try:
        from ..models_v2 import BotHeartbeat
        hb = BotHeartbeat.objects.filter(config=config).first()
        if not hb or not hb.last_seen:
            return None
        return (timezone.now() - hb.last_seen).total_seconds()
    except Exception:
        return None


def check_stale_heartbeats(stale_after_seconds=600):
    """Find configs with stale heartbeats. Returns list of (config, age)."""
    try:
        from ..models_v2 import BotHeartbeat
        cutoff = timezone.now() - timedelta(seconds=stale_after_seconds)
        stale = BotHeartbeat.objects.filter(
            last_seen__lt=cutoff, config__enabled=True,
        ).select_related("config")
        return [(hb.config, (timezone.now() - hb.last_seen).total_seconds()) for hb in stale]
    except Exception:
        return []
