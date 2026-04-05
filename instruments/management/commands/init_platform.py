"""Management command to initialize the entire platform."""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Initialize Sauron Vision: seed instruments, create portfolio, check API keys"

    def handle(self, *args, **options):
        import os

        self.stdout.write(self.style.WARNING("\n" + "=" * 60))
        self.stdout.write(self.style.WARNING("  SAURON VISION — Platform Initialization"))
        self.stdout.write(self.style.WARNING("=" * 60 + "\n"))

        # Step 1: Seed instruments
        self.stdout.write("Step 1: Seeding instruments...")
        from instruments.services import seed_all_instruments
        count = seed_all_instruments()
        self.stdout.write(self.style.SUCCESS(f"  -> {count} new instruments created\n"))

        # Step 2: Create default portfolio
        self.stdout.write("Step 2: Creating default portfolio...")
        from portfolio.services import get_or_create_default_portfolio
        portfolio = get_or_create_default_portfolio()
        self.stdout.write(self.style.SUCCESS(
            f"  -> Portfolio: {portfolio.currency} {portfolio.initial_capital}\n"
        ))

        # Step 3: Seed FRED macro indicators
        self.stdout.write("Step 3: Seeding FRED macro indicators...")
        from core.constants import FRED_SERIES
        from market_data.models import MacroIndicator
        fred_count = 0
        for series_id, name in FRED_SERIES.items():
            _, was_created = MacroIndicator.objects.get_or_create(
                series_id=series_id,
                defaults={"name": name, "category": "macro", "frequency": "daily"}
            )
            if was_created:
                fred_count += 1
        self.stdout.write(self.style.SUCCESS(f"  -> {fred_count} FRED series registered\n"))

        # Step 4: Seed market configurations
        self.stdout.write("Step 4: Seeding market configurations...")
        from core.market_config import seed_market_configs
        mc = seed_market_configs()
        self.stdout.write(self.style.SUCCESS(f"  -> {mc} market configs created\n"))

        # Step 5: Register platform components
        self.stdout.write("Step 5: Registering platform components...")
        from core.platform_control import seed_components
        comp_count = seed_components()
        self.stdout.write(self.style.SUCCESS(f"  -> {comp_count} new components registered\n"))

        # Step 5: Check API keys
        self.stdout.write("Step 6: Checking API keys...\n")
        keys = {
            "ANTHROPIC_API_KEY": "Claude AI (required for AI agents)",
            "ALPHA_VANTAGE_API_KEY": "Alpha Vantage (primary market data)",
            "TWELVE_DATA_API_KEY": "Twelve Data (multi-asset data)",
            "FINNHUB_API_KEY": "Finnhub (news + sentiment)",
            "FMP_API_KEY": "Financial Modeling Prep (fundamentals)",
            "FRED_API_KEY": "FRED (macroeconomic data — free)",
            "ETORO_PUBLIC_KEY": "eToro Public Key",
            "ETORO_USER_KEY": "eToro User Key",
            "TELEGRAM_BOT_TOKEN": "Telegram (alerts)",
        }

        configured = 0
        missing = 0
        for key, desc in keys.items():
            val = os.getenv(key, "")
            if val:
                self.stdout.write(self.style.SUCCESS(f"  [OK] {desc}"))
                configured += 1
            else:
                self.stdout.write(self.style.ERROR(f"  [--] {desc} — NOT SET"))
                missing += 1

        # Summary
        self.stdout.write(self.style.WARNING("\n" + "=" * 60))
        self.stdout.write(f"  API Keys: {configured} configured, {missing} missing")
        self.stdout.write("=" * 60)

        if missing > 0:
            self.stdout.write(self.style.WARNING(
                "\n  Add missing keys to your .env file, then start Celery workers:"
            ))
        else:
            self.stdout.write(self.style.SUCCESS("\n  All keys configured! Start the platform:"))

        self.stdout.write("""
  # Terminal 1 — Web server
  python manage.py runserver

  # Terminal 2 — Fast worker (prices, news, signals)
  celery -A config worker -l info -Q fast,default -c 4

  # Terminal 3 — Slow worker (AI agents, analysis)
  celery -A config worker -l info -Q slow,ai -c 2

  # Terminal 4 — Beat scheduler (automated tasks)
  celery -A config beat -l info

  Once all 4 processes are running, Sauron Vision begins
  collecting data and generating signals automatically.
""")
        self.stdout.write(self.style.SUCCESS("  The eye is open. \n"))
