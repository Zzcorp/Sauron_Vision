"""Is the dead man's switch set, and does its watcher hear the box?

    python manage.py dead_man_switch            # on or off, and which host
    python manage.py dead_man_switch --ping     # one ok ping, now

The check on healthchecks.io goes green on the ping. The URL itself is
never printed: it is the secret (core/dead_man_switch.py).
"""
from django.core.management.base import BaseCommand, CommandError

from core import dead_man_switch as dms


class Command(BaseCommand):
    help = "Show the dead man's switch and optionally send one test ping."

    def add_arguments(self, parser):
        parser.add_argument("--ping", action="store_true",
                            help="Send one ok ping to the watcher now.")

    def handle(self, *args, **opts):
        if not dms.ping_url():
            raise CommandError(
                f"The dead man's switch is OFF: {dms.SETTING} is not set in "
                f".env. See deploy/RUNBOOK.md, \"When the box itself goes "
                f"silent\".")
        if not dms.ping_url().startswith("https://"):
            raise CommandError(f"{dms.SETTING} is set but is not an https "
                               f"URL, so no ping is ever sent. Fix it in .env.")
        self.stdout.write(f"The dead man's switch is ON: every bot tick pings "
                          f"{dms.where() or 'a URL with no host'}.")
        if not opts["ping"]:
            return
        if dms.ping(ok=True, detail="test ping from manage.py"):
            self.stdout.write(self.style.SUCCESS(
                "Ping landed: the check should read up now."))
        else:
            raise CommandError("The ping did not land; the worker log says "
                               "why (grep \"dead man's switch\").")
