"""CLI: show bot heartbeat + circuit state for all enabled configs."""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Show bot health: heartbeats, circuit states, shadow mode flags."

    def handle(self, *args, **opts):
        from bot_program.models import BotConfig
        from bot_program.engine.heartbeat import heartbeat_age_seconds, check_stale_heartbeats
        from bot_program.engine.shadow import is_shadow_mode

        configs = BotConfig.objects.filter(enabled=True).select_related("user")
        if not configs.exists():
            self.stdout.write("No enabled bot configs.")
            return

        self.stdout.write("=" * 64)
        self.stdout.write(f"  {'USER':<20} {'MODE':<8} {'HB AGE':<10} {'SHADOW':<8} {'CIRCUIT'}")
        self.stdout.write("=" * 64)
        for cfg in configs:
            age = heartbeat_age_seconds(cfg)
            age_str = f"{age:.0f}s" if age is not None else "n/a"
            shadow = "YES" if is_shadow_mode(cfg) else "no"
            try:
                circuit = cfg.circuit_state.halt_reason or "ok"
            except Exception:
                circuit = "ok"
            self.stdout.write(
                f"  {cfg.user.username:<20} {cfg.mode:<8} {age_str:<10} {shadow:<8} {circuit}"
            )

        self.stdout.write("")
        stale = check_stale_heartbeats(stale_after_seconds=600)
        if stale:
            self.stdout.write(self.style.ERROR(f"STALE HEARTBEATS: {len(stale)}"))
            for cfg, age in stale:
                self.stdout.write(self.style.ERROR(f"  {cfg.user.username}: {age:.0f}s old"))
        else:
            self.stdout.write(self.style.SUCCESS("All heartbeats fresh."))
