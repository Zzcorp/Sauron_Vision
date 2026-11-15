# MAX BOT FLOOR RISK (2026-11-12): the most a bot's entry raised to the
# venue's smallest size may risk at its stop, in percent of the bot's pool,
# on the limits book. Read only while the live-money switch
# bots_venue_floor_live is ON (asset_engine.base.bot_floor_risk_pct); that
# switch arrives OFF, so adding the column at its default of 2 changes
# nothing on deploy.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("portfolio", "0019_traderprofile_rail_prefs"),
    ]

    operations = [
        migrations.AddField(
            model_name="portfolio",
            name="max_bot_floor_risk_pct",
            field=models.FloatField(default=2.0),
        ),
    ]
