# The signal rail's departures (2026-11-06): why a signal left the rail, in
# words, written once by the rail's own lifecycle (user NULL) or by the
# operator's PASS or take (user set). Display only — nothing in the engine,
# the bots, the alerts or the take-trade path reads this table.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0002_userannotation_pinned_target_symbol"),
        ("signals", "0019_rulecontrol_scope"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="RailDeparture",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name="ID")),
                ("reason", models.CharField(choices=[
                    ("superseded", "Replaced by a newer signal from its own rule"),
                    ("stop_crossed", "Price at or through its stop"),
                    ("target_reached", "Price at or through its target"),
                    ("chased", "Reward:risk from the mark under the ticket's line"),
                    ("rule_paused", "Its rule is paused"),
                    ("rule_demoted", "Its rule was demoted after it"),
                    ("rule_losing", "Its rule is a measured loser"),
                    ("rule_losing_live", "Its rule loses real money on its class"),
                    ("passed", "Passed by the operator"),
                    ("taken", "Taken by the operator")], max_length=24)),
                ("words", models.CharField(max_length=300)),
                ("mark", models.DecimalField(blank=True, decimal_places=8,
                                             max_digits=20, null=True)),
                ("departed_at", models.DateTimeField(db_index=True)),
                ("signal", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="rail_departures", to="signals.signal")),
                ("user", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("user__isnull", True)),
                        fields=("signal",),
                        name="rail_departure_one_lifecycle"),
                    models.UniqueConstraint(
                        condition=models.Q(("user__isnull", False)),
                        fields=("signal", "user"),
                        name="rail_departure_one_per_user"),
                ],
            },
        ),
    ]
