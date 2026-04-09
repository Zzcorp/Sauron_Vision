from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [("bot_program", "0002_market_type")]

    operations = [
        migrations.CreateModel(
            name="BotHeartbeat",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name="ID")),
                ("last_seen", models.DateTimeField(
                    db_index=True, default=django.utils.timezone.now)),
                ("status", models.CharField(default="OK", max_length=16)),
                ("note", models.CharField(blank=True, max_length=200)),
                ("tick_count", models.IntegerField(default=0)),
                ("config", models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="heartbeat", to="bot_program.botconfig")),
            ],
        ),
        migrations.CreateModel(
            name="BotCircuitState",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name="ID")),
                ("last_error_at", models.DateTimeField(blank=True, null=True)),
                ("last_error_burst_started", models.DateTimeField(blank=True, null=True)),
                ("error_count_in_burst", models.IntegerField(default=0)),
                ("halted_until", models.DateTimeField(blank=True, null=True)),
                ("halt_reason", models.CharField(blank=True, max_length=200)),
                ("config", models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="circuit_state", to="bot_program.botconfig")),
            ],
        ),
        migrations.CreateModel(
            name="BotShadowState",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name="ID")),
                ("shadow_until", models.DateTimeField(blank=True, null=True)),
                ("config", models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="shadow_state", to="bot_program.botconfig")),
            ],
        ),
        migrations.CreateModel(
            name="BotShadowAction",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(
                    db_index=True, default=django.utils.timezone.now)),
                ("action_type", models.CharField(max_length=20)),
                ("symbol", models.CharField(max_length=20)),
                ("details", models.JSONField(default=dict)),
                ("config", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="shadow_actions", to="bot_program.botconfig")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="BotSymbolOverride",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name="ID")),
                ("symbol", models.CharField(max_length=20)),
                ("position_size_pct", models.FloatField(blank=True, null=True)),
                ("stop_loss_pct", models.FloatField(blank=True, null=True)),
                ("take_profit_pct", models.FloatField(blank=True, null=True)),
                ("trailing_stop_pct", models.FloatField(blank=True, null=True)),
                ("leverage", models.FloatField(blank=True, null=True)),
                ("enabled", models.BooleanField(default=True)),
                ("config", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="symbol_overrides", to="bot_program.botconfig")),
            ],
            options={"unique_together": {("config", "symbol")}},
        ),
    ]
