"""Create Sauron Vision platform users."""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User


class Command(BaseCommand):
    help = "Create platform users for Sauron Vision"

    def handle(self, *args, **options):
        users = [
            {"username": "Emile_M", "password": "Lechienvert78!", "is_superuser": False, "is_staff": False},
            {"username": "Cesar_M", "password": "Lechienjaune21!", "is_superuser": False, "is_staff": False},
            {"username": "RS_UG", "password": "Thewhitedog44!", "is_superuser": False, "is_staff": False},
            {"username": "ElChaman", "password": "Totem92!", "is_superuser": False, "is_staff": False},
            {"username": "zz", "password": "Corp78!", "is_superuser": True, "is_staff": True},
        ]

        for u in users:
            if User.objects.filter(username=u["username"]).exists():
                user = User.objects.get(username=u["username"])
                user.set_password(u["password"])
                user.is_superuser = u["is_superuser"]
                user.is_staff = u["is_staff"]
                user.save()
                self.stdout.write(f"  Updated: {u['username']} {'(superuser)' if u['is_superuser'] else ''}")
            else:
                user = User.objects.create_user(
                    username=u["username"],
                    password=u["password"],
                    is_superuser=u["is_superuser"],
                    is_staff=u["is_staff"],
                )
                self.stdout.write(self.style.SUCCESS(
                    f"  Created: {u['username']} {'(superuser)' if u['is_superuser'] else ''}"
                ))

            # Create trader profile if missing
            try:
                from portfolio.trader_profile import TraderProfile
                TraderProfile.objects.get_or_create(user=user)
            except Exception:
                pass

            # Create notification prefs if missing
            try:
                from alerts.models import UserNotificationPrefs
                UserNotificationPrefs.objects.get_or_create(user=user)
            except Exception:
                pass

        self.stdout.write(self.style.SUCCESS(f"\n  All {len(users)} users ready."))
