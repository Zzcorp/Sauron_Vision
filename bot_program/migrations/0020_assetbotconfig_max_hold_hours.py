"""Give the time stop a real, visible ceiling — and a name for its exits.

`AssetBot._time_stop_hit` has always been able to close a position that
never resolved, and it read its ceiling out of `extras["max_hold_hours"]`.
Nothing wrote that key: not the seeder, not the settings form, not a
default. So the exit existed and never fired, and every position was
unbounded in time while every seeded setup declared a horizon of 3-21 days.

Three operations, in this order:

  1. `max_hold_hours` becomes a first-class nullable field. NULL means
     "inherit `DEFAULT_MAX_HOLD_HOURS[asset_class]`", so the ceiling of an
     untouched config tracks the platform's belief about its class instead
     of freezing today's number into every row.
  2. `outcome` gains `time_stop`. A time-stop exit used to grade as
     `manual_close` — the engine's own risk decision filed as a human's.
  3. The legacy extras key is DRAINED into the field. Leaving it in place
     would make the new field decorative on exactly the installs that had
     already set a ceiling: the runtime still honours the key first (see
     `AssetBotConfig.time_stop_setting`), so an edit to the visible field
     would have silently done nothing there. After this there is one
     writer per config.

The drain is reversible — going backwards puts the value back into extras
before the column disappears, because the alternative is a rollback that
silently turns every configured time stop off.
"""
from django.core.validators import MinValueValidator
from django.db import migrations, models

EXTRAS_KEY = "max_hold_hours"


def drain_extras_key_into_field(apps, schema_editor):
    AssetBotConfig = apps.get_model("bot_program", "AssetBotConfig")
    for cfg in AssetBotConfig.objects.all().iterator():
        extras = cfg.extras or {}
        if EXTRAS_KEY not in extras:
            continue
        try:
            hours = max(0.0, float(extras[EXTRAS_KEY]))
        except (TypeError, ValueError):
            # A hand-typed value the field cannot hold ("24h", "two"). Left
            # exactly where it is: the runtime warns and falls back to the
            # class ceiling, which is a better outcome than this migration
            # inventing a number on the operator's behalf.
            continue
        extras = dict(extras)
        extras.pop(EXTRAS_KEY)
        cfg.max_hold_hours = hours
        cfg.extras = extras
        cfg.save(update_fields=["max_hold_hours", "extras"])


def refill_extras_key_from_field(apps, schema_editor):
    """Reverse: the column is about to be dropped, so the value has to go
    back to the only other place that holds it. Without this, `migrate
    bot_program 0019` would quietly return every config to no time stop."""
    AssetBotConfig = apps.get_model("bot_program", "AssetBotConfig")
    for cfg in AssetBotConfig.objects.exclude(
            max_hold_hours__isnull=True).iterator():
        extras = dict(cfg.extras or {})
        extras[EXTRAS_KEY] = float(cfg.max_hold_hours)
        cfg.extras = extras
        cfg.save(update_fields=["extras"])


class Migration(migrations.Migration):

    dependencies = [
        ("bot_program", "0019_alter_botconfig_options"),
    ]

    operations = [
        migrations.AddField(
            model_name="assetbotconfig",
            name="max_hold_hours",
            field=models.FloatField(
                blank=True, null=True,
                validators=[MinValueValidator(0.0)],
                help_text=(
                    "Hours a position may stay open before the engine "
                    "flattens it with reason TIME. 0 = no time stop "
                    "(positions are then unbounded in time — only the stop, "
                    "the target or an operator will close them). Leave blank "
                    "to inherit the asset-class default."),
            ),
        ),
        migrations.AlterField(
            model_name="assetbottrade",
            name="outcome",
            field=models.CharField(
                blank=True, db_index=True, max_length=20,
                choices=[("hit_target", "Hit Target"),
                         ("stopped_out", "Stopped Out"),
                         ("manual_close", "Manually Closed"),
                         ("expired", "Expired"),
                         ("time_stop", "Time Stop")],
            ),
        ),
        migrations.RunPython(drain_extras_key_into_field,
                             refill_extras_key_from_field),
    ]
