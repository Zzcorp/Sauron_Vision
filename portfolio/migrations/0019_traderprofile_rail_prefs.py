# The signal rail's filters and display choices (2026-11-06), per user, so
# every browser draws the same rail. Display only: nothing in the engine,
# the bots, the alerts or the take-trade path reads it. {} is the defaults
# (dashboard.rail_prefs), so nothing changes on deploy.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("portfolio", "0018_portfolio_max_bot_leverage"),
    ]

    operations = [
        migrations.AddField(
            model_name="traderprofile",
            name="rail_prefs",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
