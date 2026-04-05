"""Management command to seed financial instruments."""
from django.core.management.base import BaseCommand
from instruments.services import seed_all_instruments, INSTRUMENTS_DATA


class Command(BaseCommand):
    help = "Seed the database with financial instruments (200+ assets)"

    def add_arguments(self, parser):
        parser.add_argument("--class", type=str, default="all",
            help="Asset class to seed: all, forex, commodity, stock, index, etf, crypto")

    def handle(self, *args, **options):
        asset_class = options.get("class", "all")

        if asset_class == "all":
            self.stdout.write("Seeding ALL instruments...")
            count = seed_all_instruments()
            self.stdout.write(self.style.SUCCESS(f"  Created {count} instruments across all asset classes"))
        else:
            from instruments.models import Instrument
            data = INSTRUMENTS_DATA.get(asset_class, {})
            created = 0
            for symbol, info in data.items():
                name = info[0] if isinstance(info, tuple) else info
                exchange = info[1] if isinstance(info, tuple) else ("FOREX" if asset_class == "forex" else "")
                _, was_created = Instrument.objects.get_or_create(
                    symbol=symbol,
                    defaults={"name": name, "asset_class": asset_class, "exchange": exchange, "currency": "USD", "is_active": True}
                )
                if was_created:
                    created += 1
            self.stdout.write(self.style.SUCCESS(f"  Created {created} {asset_class} instruments"))

        # Summary
        from instruments.models import Instrument
        for ac in ["forex", "commodity", "index", "stock", "etf", "crypto"]:
            c = Instrument.objects.filter(asset_class=ac).count()
            self.stdout.write(f"  {ac:12s}: {c}")
        self.stdout.write(self.style.SUCCESS(f"\n  Total: {Instrument.objects.count()} instruments"))
