"""Flag a watchlist.

Not one of the 179 active instruments had is_watchlist set, and a surprising
amount of the platform is gated on that flag: the technical-indicator
recalculation, the per-symbol scrapers, the instrument-detail technicals
panel. Each of them filtered on an empty set, iterated zero times and reported
success, which is why TechnicalIndicator held no rows at all while 5,600 price
bars sat in the database next to it.

By default this flags the instruments that already have price history, since
those are the ones every downstream job can actually say something about.

    python manage.py seed_watchlist
    python manage.py seed_watchlist --symbols BTCUSD,ETHUSD,SPX500
    python manage.py seed_watchlist --clear
"""
from django.core.management.base import BaseCommand

from instruments.models import Instrument


class Command(BaseCommand):
    help = "Flag instruments as watchlist members (defaults to those with price history)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--symbols", default="",
            help="Comma-separated symbols to flag instead of the default set.")
        parser.add_argument(
            "--limit", type=int, default=25,
            help="Cap on how many instruments to flag (default 25).")
        parser.add_argument(
            "--clear", action="store_true",
            help="Unflag every instrument first.")

    def handle(self, *args, **opts):
        if opts["clear"]:
            cleared = Instrument.objects.filter(is_watchlist=True).update(is_watchlist=False)
            self.stdout.write(f"cleared {cleared} existing watchlist flags")

        if opts["symbols"]:
            wanted = [s.strip().upper() for s in opts["symbols"].split(",") if s.strip()]
            qs = Instrument.objects.filter(symbol__in=wanted, is_active=True)
            missing = set(wanted) - set(qs.values_list("symbol", flat=True))
            if missing:
                self.stderr.write(self.style.WARNING(
                    f"not in the catalogue, skipped: {', '.join(sorted(missing))}"))
        else:
            qs = Instrument.objects.filter(
                is_active=True, prices__isnull=False).distinct()

        chosen = list(qs[:opts["limit"]])
        if not chosen:
            self.stderr.write(self.style.ERROR(
                "Nothing to flag. No active instrument has price history yet — "
                "run `manage.py backfill_bars` first."))
            return

        Instrument.objects.filter(pk__in=[i.pk for i in chosen]).update(is_watchlist=True)
        self.stdout.write(self.style.SUCCESS(
            f"flagged {len(chosen)} instruments: "
            f"{', '.join(i.symbol for i in chosen)}"))
