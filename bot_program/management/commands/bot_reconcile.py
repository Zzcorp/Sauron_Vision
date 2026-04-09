"""CLI: reconcile a user's bot positions against Binance live state."""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Reconcile open BotTrades against Binance positions for a user."

    def add_arguments(self, parser):
        parser.add_argument("--user", required=True, help="username")

    def handle(self, *args, **opts):
        from django.contrib.auth.models import User
        from bot_program.engine.reconcile import reconcile_user

        try:
            user = User.objects.get(username=opts["user"])
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"User {opts['user']} not found"))
            return

        result = reconcile_user(user.id)
        self.stdout.write(self.style.SUCCESS("Reconciliation result:"))
        for k, v in result.items():
            self.stdout.write(f"  {k}: {v}")
