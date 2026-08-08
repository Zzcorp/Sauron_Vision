"""Create Sauron Vision platform users.

Passwords are NEVER hardcoded in source. Each user's password is read from an
environment variable named ``SAURON_PW_<USERNAME>`` (username uppercased, with any
non-alphanumeric character replaced by ``_``). Users whose password env var is
unset are skipped — so running this command without configured secrets is a safe
no-op and never leaks credentials.

Examples (PowerShell):
    $env:SAURON_PW_EMILE_M = "..."
    $env:SAURON_PW_ZZ      = "..."   # superuser
    python manage.py create_users

The superuser flag is the only role baked into source; it is not a secret.
"""
import os
import re

from django.core.management.base import BaseCommand
from django.contrib.auth.models import User


# (username, is_superuser, is_staff). Passwords come from env — see module docstring.
PLATFORM_USERS = [
    ("Emile_M", False, False),
    ("Cesar_M", False, False),
    ("RS_UG", False, False),
    ("ElChaman", False, False),
    ("Anonymous_Z", False, False),
    ("zz", True, True),
]


def _env_key(username: str) -> str:
    return "SAURON_PW_" + re.sub(r"[^A-Za-z0-9]", "_", username).upper()


class Command(BaseCommand):
    help = "Create/update platform users. Passwords are read from SAURON_PW_<USERNAME> env vars."

    def handle(self, *args, **options):
        created, updated, skipped = 0, 0, 0

        for username, is_superuser, is_staff in PLATFORM_USERS:
            env_key = _env_key(username)
            password = os.environ.get(env_key)
            if not password:
                self.stdout.write(self.style.WARNING(
                    f"  Skipped: {username} — set {env_key} to create/update this user."
                ))
                skipped += 1
                continue

            user, was_created = User.objects.get_or_create(username=username)
            user.set_password(password)
            user.is_superuser = is_superuser
            user.is_staff = is_staff
            user.save()

            tag = " (superuser)" if is_superuser else ""
            if was_created:
                created += 1
                self.stdout.write(self.style.SUCCESS(f"  Created: {username}{tag}"))
            else:
                updated += 1
                self.stdout.write(f"  Updated: {username}{tag}")

            try:
                from portfolio.trader_profile import TraderProfile
                TraderProfile.objects.get_or_create(user=user)
            except Exception:
                pass

            try:
                from alerts.models import UserNotificationPrefs
                UserNotificationPrefs.objects.get_or_create(user=user)
            except Exception:
                pass

        self.stdout.write(self.style.SUCCESS(
            f"\n  Done — {created} created, {updated} updated, {skipped} skipped."
        ))
        if skipped:
            self.stdout.write(
                "  Set the SAURON_PW_<USERNAME> environment variables for any skipped users."
            )
