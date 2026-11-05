# MAX BOT LEVERAGE (2026-11-05): the highest multiplier a bot's eToro order may
# carry, on the limits book. The operator, 2026-11-04: "restaurer achat et
# vente manuel en leverage max et plus mesuré pour les bots" (restore manual
# buy and sell at max leverage, and more measured for the bots). Added NULL,
# which is no cap (asset_engine.base.bot_leverage_cap): every existing book
# reads blank, so nothing changes on deploy until the operator sets it.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("portfolio", "0017_portfolio_max_notional_multiple"),
    ]

    operations = [
        migrations.AddField(
            model_name="portfolio",
            name="max_bot_leverage",
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
