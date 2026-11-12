# The operator's Ambience (2026-11-12): how much of Sauron's own theme the
# pages show, Magic, Calm or Off, per user, beside the theme. Display only:
# nothing in the engine, the bots, the Orcs, the alerts, the gates or the
# ticket reads it. Every profile that exists takes "magic", which is what
# every page showed before this column. The profile is read on every
# request (the theme, the idle lock): MIGRATE BEFORE RESTART.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("portfolio", "0019_traderprofile_rail_prefs"),
    ]

    operations = [
        migrations.AddField(
            model_name="traderprofile",
            name="ambience",
            field=models.CharField(
                choices=[("magic", "Magic"), ("calm", "Calm"), ("off", "Off")],
                default="magic",
                help_text="Display only: embers, light and moments.",
                max_length=8,
            ),
        ),
    ]
