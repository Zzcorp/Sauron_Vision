"""Enable or disable an asset bot from the shell — the toggle on the
admin page, with the page's own rule.

The page asks the trading PIN to ARM a live bot and nothing to stop
one: stopping must stay frictionless. Here `--yes` plays the PIN's
role for arming a live config; `bot off` never asks. Read-only until
told otherwise; never touches the broker.

    python manage.py bot list
    python manage.py bot off 1
    python manage.py bot on 6            # paper: writes; live: plan only
    python manage.py bot on 6 --yes      # live: writes
"""
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "List, enable or disable asset-bot configs (the page's toggle, as a command)."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["list", "on", "off"])
        parser.add_argument("ids", nargs="*", type=int)
        parser.add_argument("--yes", action="store_true",
                            help="Arm a LIVE config (the page asks the PIN for this).")

    def handle(self, *args, **opts):
        from bot_program.asset_models import AssetBotConfig
        if opts["action"] == "list":
            rows = AssetBotConfig.objects.select_related("user").order_by("user_id", "pk")
            for c in rows:
                state = "ON " if c.enabled else "OFF"
                self.stdout.write(
                    f"  {state}  [{c.pk:<3}] {c.name:<24} {c.asset_class:<9} {c.mode:<5} "
                    f"pool {c.capital} {c.base_currency}  symbols {len(c.symbols or [])}  "
                    f"({c.user.username})")
            if not rows:
                self.stdout.write("no configs")
            return
        if not opts["ids"]:
            raise CommandError(f"bot {opts['action']}: give at least one config id "
                               f"(see `bot list`).")
        enable = opts["action"] == "on"
        for pk in opts["ids"]:
            cfg = AssetBotConfig.objects.filter(pk=pk).first()
            if cfg is None:
                self.stdout.write(self.style.ERROR(f"[{pk}]: not found"))
                continue
            if cfg.enabled == enable:
                self.stdout.write(f"[{pk}] {cfg.name}: already "
                                  f"{'ON' if enable else 'OFF'} (unchanged)")
                continue
            if enable and cfg.mode == "live" and not opts["yes"]:
                self.stdout.write(self.style.WARNING(
                    f"[{pk}] {cfg.name} is LIVE ({cfg.asset_class}, pool {cfg.capital} "
                    f"{cfg.base_currency}, {len(cfg.symbols or [])} symbols): arming it "
                    f"puts real money in play — the page asks the PIN here. Add --yes."))
                continue
            cfg.enabled = enable
            cfg.save(update_fields=["enabled", "updated_at"])
            self.stdout.write(self.style.SUCCESS(
                f"[{pk}] {cfg.name} ({cfg.asset_class}/{cfg.mode}): "
                f"{'ENABLED' if enable else 'DISABLED'}"))
