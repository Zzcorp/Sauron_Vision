"""The cockpit's catalogue (/ops/), as a command.

Prints every shell twin and diagnostic the platform ships, grouped by
category, with its purpose, its usage lines and the page it mirrors —
read straight off core.ops_commands, the same list the page renders, so
the two cannot disagree. Read-only: it touches no database row.

    python manage.py ops
    python manage.py ops --category read
"""
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Print the command catalogue the /ops/ cockpit shows. Read-only."

    def add_arguments(self, parser):
        parser.add_argument("--category", default="",
                            choices=["", "read", "decide", "ops"],
                            help="Only this category.")

    def handle(self, *args, **opts):
        from core.ops_commands import by_category, is_runnable

        want = opts["category"]
        w = self.stdout.write
        w("SAURON — COMMAND CATALOGUE (the /ops/ cockpit, as text)")
        for key, label, rows in by_category():
            if want and key != want:
                continue
            w("")
            w(f"[{key}] {label}")
            for e in rows:
                lane = ("page can run it" if is_runnable(e)
                        else e.get("runnable_reason")
                        or "run on the server — --yes or the PIN keeps its meaning")
                w(f"\n  {e['title']}  ({e['name']})")
                w(f"    {e['purpose']}")
                for line in e["usage"]:
                    w(f"      {line}")
                mirrors = e.get("mirrors") or "—"
                w(f"    mirrors {mirrors} · {lane}")
        if want and not any(k == want for k, _l, _r in by_category()):
            raise CommandError(f"unknown category {want!r}")
