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

        # ── Upgrade the list-page fallbacks that ALREADY shipped ────────
        #
        # A notification's url is written once, at creation, so fixing a
        # producer does nothing for the rows already in everybody's bell.
        # The anomaly alert deep-linked only when a scan found exactly ONE
        # severe anomaly and otherwise fell back to /quotes/ — and that
        # scan fires repeatedly on one instrument, nine or thirteen times a
        # day on the same pair, so the fallback was the normal case. Those
        # rows still point at a list page the operator has to search.
        #
        # /quotes/ is a VALID page, so `safe_url` above leaves it alone.
        # This is the separate question of whether it is the RIGHT page,
        # and the row itself carries the answer: `data.items` holds one
        # entry per anomaly with the asset's own url. When every item names
        # the same asset, that is where the click belonged all along.
        upgraded = 0
        for notif in Notification.objects.filter(url="/quotes/").only(
                "id", "url", "data"):
            data = notif.data if isinstance(notif.data, dict) else {}
            items = data.get("items")
            if not isinstance(items, list):
                continue
            urls = {i.get("url") for i in items
                    if isinstance(i, dict) and i.get("url")}
            # One asset, one destination. Several assets keep the list
            # page: it is the only page that holds all of them, and the
            # rows in the panel carry their own links.
            if len(urls) != 1:
                continue
            target = Notification.safe_url(urls.pop())
            if target and target != notif.url:
                Notification.objects.filter(pk=notif.pk).update(url=target)
                upgraded += 1
        if upgraded:
            self.stdout.write(
                f"  /quotes/  ->  the asset's own page  ({upgraded} rows)")

        self.stdout.write(self.style.SUCCESS(
            f"Rewrote {total} row(s), upgraded {upgraded} list-page "
            f"fallback(s), blanked {blanked} unresolvable link(s)."))
