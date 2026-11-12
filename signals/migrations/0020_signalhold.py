# A signal's announcement held until its market opens (2026-11-12,
# signals/models_hold.py): one row per held signal. Additive: a new, empty
# table. Nothing is written to it while the signal_market_hold switch is
# off, which is how it arrives.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("signals", "0019_rulecontrol_scope"),
    ]

    operations = [
        migrations.CreateModel(
            name="SignalHold",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "state",
                    models.CharField(
                        choices=[
                            ("held", "Held: its market cannot trade yet"),
                            ("released", "Released: announced once, at the open"),
                            ("dropped", "Dropped: never announced"),
                        ],
                        db_index=True,
                        default="held",
                        max_length=10,
                    ),
                ),
                ("reason", models.CharField(default="market_shut", max_length=30)),
                ("words", models.CharField(blank=True, default="", max_length=300)),
                ("reopens_at", models.DateTimeField(blank=True, null=True)),
                ("held_at", models.DateTimeField()),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                (
                    "mark",
                    models.DecimalField(
                        blank=True, decimal_places=8, max_digits=20, null=True
                    ),
                ),
                (
                    "signal",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="hold",
                        to="signals.signal",
                    ),
                ),
            ],
            options={
                "ordering": ["-held_at", "-pk"],
            },
        ),
    ]
