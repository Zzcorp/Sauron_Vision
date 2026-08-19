"""Repair notification links that were shipped pointing at 404s.

The write side has been guarded for a while (Notification.safe_url) and a
management command existed to clean up — but a repair nobody runs is not a
repair. Every user's inbox still held copies of "Market anomaly alert"
pointing at /market-data/, which has never been a route, and the operator
met the 404 again after the code fix had already shipped.

Migrations run on deploy, so this repairs the rows without anyone having
to know the command exists. It is data-only and idempotent: a second run
matches nothing.
"""
from django.db import migrations

# Same map as alerts/management/commands/repair_notification_urls.py — the
# command stays for ad-hoc runs; this is the one that fires automatically.
# It repairs by PRODUCER intent, which is why "/dashboard/" lands on the
# briefing page rather than the dashboard: every stored row carrying it was
# written by the briefing/game-plan notifications.
REWRITES = {
    "/market-data/": "/quotes/",     # the LiveQuote page
    "/dashboard/": "/briefing/",     # what those rows were announcing
}


def repair(apps, schema_editor):
    Notification = apps.get_model("alerts", "Notification")
    for bad, good in REWRITES.items():
        Notification.objects.filter(url=bad).update(url=good)


def unrepair(apps, schema_editor):
    """Deliberately a no-op: reversing would restore known-dead links."""


class Migration(migrations.Migration):

    dependencies = [
        ("alerts", "0008_notification_alerts_noti_user_id_f18f0e_idx"),
    ]

    operations = [
        migrations.RunPython(repair, unrepair),
    ]
