from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [("backtester", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="BacktestRunV2",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name="ID")),
                ("name", models.CharField(blank=True, max_length=120)),
                ("config_hash", models.CharField(db_index=True, max_length=16)),
                ("config", models.JSONField(default=dict)),
                ("symbols", models.JSONField(default=list)),
                ("start_date", models.DateTimeField(blank=True, null=True)),
                ("end_date", models.DateTimeField(blank=True, null=True)),
                ("initial_capital", models.FloatField(default=10000)),
                ("final_capital", models.FloatField(default=0)),
                ("total_return_pct", models.FloatField(default=0)),
                ("max_drawdown_pct", models.FloatField(default=0)),
                ("sharpe", models.FloatField(blank=True, null=True)),
                ("sortino", models.FloatField(blank=True, null=True)),
                ("calmar", models.FloatField(blank=True, null=True)),
                ("profit_factor", models.FloatField(blank=True, null=True)),
                ("win_rate", models.FloatField(default=0)),
                ("n_trades", models.IntegerField(default=0)),
                ("expectancy_r", models.FloatField(default=0)),
                ("metrics", models.JSONField(default=dict)),
                ("trades", models.JSONField(default=list)),
                ("equity_curve", models.JSONField(default=list)),
                ("created_at", models.DateTimeField(
                    db_index=True, default=django.utils.timezone.now)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(
            model_name="backtestrunv2",
            index=models.Index(
                fields=["config_hash", "-created_at"],
                name="bt_v2_hash_created_idx",
            ),
        ),
    ]
