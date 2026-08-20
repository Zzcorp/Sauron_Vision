"""Make the single-position ceiling agree with the sizing engine — on
existing books, not just on new ones.

`AlterField` moves the DEFAULT, which only ever reaches rows created after
it. Every deployed install already has its "Main" Portfolio row, so on an
upgrade the ceiling stays at the old 10 while the sizing engine goes on
building positions at 20% of the pool — and the gate that was just armed
refuses the platform's own default-sized entry on every existing account.
A limit nobody set, refusing trades nobody mis-sized, is the worst way for
this work to arrive.

So the value moves too — but ONLY where it is still the old default. An
operator who deliberately set 5% or 40% chose that number, and a migration
that overwrites a risk limit somebody typed is a far worse bug than the one
it is fixing. `10.0` is the fingerprint of "never touched"; anything else is
a decision and is left alone.

Reversing puts the untouched rows back to 10, so a downgrade does not leave
a number this schema never shipped.
"""
from django.db import migrations, models

OLD_DEFAULT = 10.0
NEW_DEFAULT = 20.0


def _move_untouched(apps, schema_editor, *, frm, to):
    Portfolio = apps.get_model("portfolio", "Portfolio")
    # A float equality test is exact here on purpose: the value was written by
    # a field default, not computed, so it is bit-identical to the literal.
    # Anything that is not that literal was set by a person.
    Portfolio.objects.filter(max_single_position_pct=frm).update(
        max_single_position_pct=to)


def forwards(apps, schema_editor):
    _move_untouched(apps, schema_editor, frm=OLD_DEFAULT, to=NEW_DEFAULT)


def backwards(apps, schema_editor):
    _move_untouched(apps, schema_editor, frm=NEW_DEFAULT, to=OLD_DEFAULT)


class Migration(migrations.Migration):

    dependencies = [
        ('portfolio', '0010_traderprofile_idle_lock'),
    ]

    operations = [
        migrations.AlterField(
            model_name='portfolio',
            name='max_single_position_pct',
            field=models.FloatField(default=20),
        ),
        migrations.RunPython(forwards, backwards),
    ]
