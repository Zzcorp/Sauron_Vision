"""Create Sauron Vision platform users.

Nothing about a person is in this file: this repository is public. The
roster is read from the environment and so is every password.

  SAURON_PLATFORM_USERS   the roster: ``name[:role],name[:role],...``.
                          A role is ``staff`` or ``superuser`` (which
                          implies staff); no role means a plain user.
                          Unset or empty, the command does nothing and
                          says which variable to set.
  SAURON_PW_<USERNAME>    the password of each listed user (username
                          uppercased, any non-alphanumeric character
                          replaced by ``_``). A listed user whose password
                          variable is unset is skipped — so running this
                          command without configured secrets is a safe
                          no-op and never leaks credentials.

Examples (PowerShell):
    $env:SAURON_PLATFORM_USERS = "alice,bob:staff,carol:superuser"
    $env:SAURON_PW_ALICE = "..."
    $env:SAURON_PW_BOB   = "..."
    $env:SAURON_PW_CAROL = "..."
    python manage.py create_users

Each user created or updated gets a TraderProfile and notification
preferences row, as before.
"""
import os
import re

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

#: The roster's environment variable, and the roles it may name.
ROSTER_ENV = "SAURON_PLATFORM_USERS"
#: role -> (is_superuser, is_staff)
ROLES = {"": (False, False), "staff": (False, True), "superuser": (True, True)}


def _env_key(username: str) -> str:
    return "SAURON_PW_" + re.sub(r"[^A-Za-z0-9]", "_", username).upper()


def roster(raw=None) -> list:
    """[(username, is_superuser, is_staff)] out of ``name[:role],...``.
    Read from the environment when `raw` is None. Blanks are ignored, a
    name listed twice is taken once (its first role), and a role nobody
    knows raises ValueError naming the role, never a password."""
    if raw is None:
        raw = os.environ.get(ROSTER_ENV) or ""
    out, seen = [], set()
    for piece in str(raw).split(","):
        piece = piece.strip()
        if not piece:
            continue
        name, _sep, role = piece.partition(":")
        name, role = name.strip(), role.strip().lower()
        if not name or name in seen:
            continue
        if role not in ROLES:
            raise ValueError("unknown role %r for user %r (staff or superuser)"
                             % (role, name))
        seen.add(name)
        is_superuser, is_staff = ROLES[role]
        out.append((name, is_superuser, is_staff))
    return out


class Command(BaseCommand):
    help = ("Create/update platform users. The roster is read from "
            f"{ROSTER_ENV} and each password from SAURON_PW_<USERNAME>.")

    def handle(self, *args, **options):
        try:
            users = roster()
        except ValueError as exc:
            raise CommandError(str(exc))
        if not users:
            self.stdout.write(self.style.WARNING(
                f"  Nothing to do: set {ROSTER_ENV}=name[:role],... (role: "
                f"staff or superuser) and SAURON_PW_<USERNAME> for each."))
            return

        created, updated, skipped = 0, 0, 0
        for username, is_superuser, is_staff in users:
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

            tag = (" (superuser)" if is_superuser
                   else " (staff)" if is_staff else "")
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
