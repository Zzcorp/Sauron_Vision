# The operator's Ambience (2026-11-12): how much of Sauron's own theme the
# pages show, Magic, Calm or Off, per user, beside the theme. Display only:
# nothing in the engine, the bots, the Orcs, the alerts, the gates or the
# ticket reads it. Every profile that exists takes "magic", which is what
# every page showed before this column, and the column keeps "magic" as its
# database default, so code that does not know it can still create a
# profile (the old containers during the migrate step, or a rollback).
#
# MIGRATE BEFORE RESTARTING web, the workers and beat. New code on the old
# schema reads the profile whole where it loads it, and that read raises
# "no such column": the pages still answer (the theme and the idle lock
# read it narrowly), but in the workers the cross-asset orchestrator's gate
# (bot_program.orchestrator.gate_new_entry) raises, its caller logs it and
# lets the bot's entry through WITHOUT the exposure caps. Never restart a
# worker on this code before this migration has run.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("portfolio", "0020_portfolio_max_bot_floor_risk_pct"),
    ]

    operations = [
        migrations.AddField(
            model_name="traderprofile",
            name="ambience",
            field=models.CharField(
                choices=[("magic", "Magic"), ("calm", "Calm"), ("off", "Off")],
                db_default="magic",
                default="magic",
                help_text="Display only: embers, light and moments.",
                max_length=8,
            ),
        ),
    ]
