# The book's notional cap (2026-10-04): the most notional one venue's open
# positions may carry together, as a multiple of the venue's book. The
# exposure limit counts forex at its margin (1/30), so a 500 book carried
# 14,800 of yen crosses inside "100% max total exposure".

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("portfolio", "0016_portfolio_max_open_risk_pct"),
    ]

    operations = [
        migrations.AddField(
            model_name="portfolio",
            name="max_notional_multiple",
            field=models.FloatField(default=4.0),
        ),
    ]
