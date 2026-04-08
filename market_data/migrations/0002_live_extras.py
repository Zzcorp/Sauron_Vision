from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [("market_data", "0001_initial")]
    operations = [
        migrations.CreateModel(
            name="LiquidationEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("symbol", models.CharField(db_index=True, max_length=20)),
                ("side", models.CharField(choices=[("LONG","Long liquidated"),("SHORT","Short liquidated")], max_length=6)),
                ("qty", models.DecimalField(decimal_places=8, max_digits=24)),
                ("price", models.DecimalField(decimal_places=8, max_digits=24)),
                ("notional_usd", models.DecimalField(decimal_places=2, default=0, max_digits=24)),
                ("timestamp", models.DateTimeField(db_index=True)),
                ("source", models.CharField(default="binance_futures", max_length=24)),
            ],
            options={"ordering": ["-timestamp"]},
        ),
        migrations.AddIndex(
            model_name="liquidationevent",
            index=models.Index(fields=["symbol","-timestamp"], name="md_liq_sym_ts_idx"),
        ),
        migrations.CreateModel(
            name="FundingRate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("symbol", models.CharField(db_index=True, max_length=20)),
                ("mark_price", models.DecimalField(decimal_places=8, max_digits=24)),
                ("index_price", models.DecimalField(decimal_places=8, default=0, max_digits=24)),
                ("funding_rate", models.DecimalField(decimal_places=8, default=0, max_digits=12)),
                ("next_funding_time", models.DateTimeField(blank=True, null=True)),
                ("timestamp", models.DateTimeField(db_index=True)),
            ],
            options={"ordering": ["-timestamp"]},
        ),
        migrations.AddIndex(
            model_name="fundingrate",
            index=models.Index(fields=["symbol","-timestamp"], name="md_fund_sym_ts_idx"),
        ),
        migrations.CreateModel(
            name="OrderBookSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("symbol", models.CharField(db_index=True, max_length=20)),
                ("timestamp", models.DateTimeField(db_index=True)),
                ("mid_price", models.DecimalField(decimal_places=8, max_digits=24)),
                ("spread", models.DecimalField(decimal_places=8, default=0, max_digits=24)),
                ("bid_volume", models.DecimalField(decimal_places=4, default=0, max_digits=24)),
                ("ask_volume", models.DecimalField(decimal_places=4, default=0, max_digits=24)),
                ("imbalance", models.FloatField(default=0)),
                ("depth_score", models.FloatField(default=0)),
                ("bids", models.JSONField(default=list)),
                ("asks", models.JSONField(default=list)),
            ],
            options={"ordering": ["-timestamp"]},
        ),
        migrations.AddIndex(
            model_name="orderbooksnapshot",
            index=models.Index(fields=["symbol","-timestamp"], name="md_ob_sym_ts_idx"),
        ),
    ]
