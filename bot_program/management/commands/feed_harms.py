"""manage.py feed_harms --days N — the harm counters' counts, by kind (the
eToro feed spec, F1, §6.2; 2026-11-07).

The baseline the later phases are judged on: run it before a switch goes
ON and seven days after. It prints, for every kind of
bot_program.feed_harms (zeros included), how many times today's code did
that harm in the window, and for the kill switch's waits their median and
their longest, in seconds. Never a price, an account figure or an id: the
rows' details stay in the table, for a reading by hand on the server.

Usage:
    python manage.py feed_harms              # the last 7 days
    python manage.py feed_harms --days 30    # the last 30 days

Read-only: it writes nothing and asks no broker.
"""
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = ("Counts of the eToro feed's harm counters by kind over the last "
            "N days (never a price, an account figure or an id).")

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=7,
                            help="the window, in whole days (default 7)")

    def handle(self, *args, **options):
        from bot_program import feed_harms
        days = options["days"]
        if days is None or days < 1:
            raise CommandError("--days must be a whole number of days, "
                               "1 or more")
        r = feed_harms.report(days)
        self.stdout.write(f"Feed harms over the last {days} day(s), since "
                          f"{r['since']:%Y-%m-%d %H:%M} UTC")
        for kind in feed_harms.KINDS:
            n = r["counts"].get(kind, 0)
            line = f"  {kind:<24} {n:>6}  {feed_harms.KIND_WORDS[kind]}"
            if kind == feed_harms.KILL_SWITCH_WAIT and r["waits"]:
                line += (f" (p50 {r['waits']['p50']:.1f} s, "
                         f"max {r['waits']['max']:.1f} s)")
            self.stdout.write(line)
