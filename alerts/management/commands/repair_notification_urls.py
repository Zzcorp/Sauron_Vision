"""Repair stored notification links that point at pages that never
existed.

Producers wrote free-text urls unchecked for months: the anomaly alert
linked "/market-data/" (never a route — the LiveQuote page is /quotes/)
and the briefing/game-plan notifications linked "/dashboard/" (the
dashboard is mounted at "/", and the briefing page is /briefing/).
`Notification.create_for_all` fans one row out per active user, so every
user holds copies of every bad link. The write side is guarded now
(Notification.safe_url); this repairs what already shipped.

Run with:  python manage.py repair_notification_urls
"""
from django.core.management.base import BaseCommand

REWRITES = {
    "/market-data/": "/quotes/",
    "/dashboard/": "/briefing/",
}


class Command(BaseCommand):
    help = "Rewrite stored notification urls that 404 (see REWRITES)."

    def handle(self, *args, **options):
        from alerts.models import Notification

        total = 0
        for bad, good in REWRITES.items():
            n = Notification.objects.filter(url=bad).update(url=good)
            if n:
                self.stdout.write(f"  {bad}  ->  {good}  ({n} rows)")
            total += n

        # Anything else unresolvable is blanked so the bell opens the
        # detail popup instead of a dead page.
        blanked = 0
        for notif in Notification.objects.exclude(url="").only("id", "url"):
            safe = Notification.safe_url(notif.url)
            if safe != notif.url:
                Notification.objects.filter(pk=notif.pk).update(url=safe)
                blanked += 1

        self.stdout.write(self.style.SUCCESS(
            f"Rewrote {total} row(s), blanked {blanked} unresolvable "
            f"link(s)."))
