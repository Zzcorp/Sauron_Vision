from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [("signals", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="SmcSignal",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name="ID")),
                ("symbol", models.CharField(db_index=True, max_length=32)),
                ("timeframe", models.CharField(max_length=8)),
                ("setup", models.CharField(max_length=32)),
                ("direction", models.CharField(max_length=8)),
                ("headline", models.CharField(max_length=120)),
                ("thesis", models.CharField(max_length=280)),
                ("why_now", models.TextField(blank=True)),
                ("invalidation", models.CharField(max_length=200)),
                ("entry", models.FloatField()),
                ("stop", models.FloatField()),
                ("target", models.FloatField()),
                ("r_multiple", models.FloatField(default=0)),
                ("chip_structure", models.IntegerField(default=0)),
                ("chip_momentum", models.IntegerField(default=0)),
                ("chip_flow", models.IntegerField(default=0)),
                ("chip_macro", models.IntegerField(default=0)),
                ("chip_sentiment", models.IntegerField(default=0)),
                ("conviction", models.IntegerField(default=0)),
                ("reasons", models.JSONField(default=list)),
                ("components", models.JSONField(default=list)),
                ("raw", models.JSONField(blank=True, default=dict)),
                ("status", models.CharField(default="ACTIVE", max_length=16)),
                ("triggered_at", models.DateTimeField(blank=True, null=True)),
                ("closed_at", models.DateTimeField(blank=True, null=True)),
                ("realized_r", models.FloatField(blank=True, null=True)),
                ("rule_hit_rate_30d", models.FloatField(blank=True, null=True)),
                ("created_at", models.DateTimeField(
                    db_index=True, default=django.utils.timezone.now)),
                ("trigger_ts", models.DateTimeField(blank=True, null=True)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(
            model_name="smcsignal",
            index=models.Index(
                fields=["symbol", "timeframe", "status"],
                name="signals_smc_symbol_tf_status_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="smcsignal",
            index=models.Index(
                fields=["setup", "status"],
                name="signals_smc_setup_status_idx",
            ),
        ),
    ]
