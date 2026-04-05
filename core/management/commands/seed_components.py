"""Register all platform components."""
from django.core.management.base import BaseCommand
from core.platform_control import seed_components


class Command(BaseCommand):
    help = "Register all platform components (scrapers, agents, pipelines)"

    def handle(self, *args, **options):
        count = seed_components()
        self.stdout.write(self.style.SUCCESS(f"Registered {count} new components"))
