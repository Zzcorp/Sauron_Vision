# Written by hand on 2026-09-23 in the shape of 0034_saxo_venue_cells;
# `makemigrations bot_program --check` must agree with it after the model
# edit lands (run it, do not trust the hand copy).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bot_program', '0035_alter_saxoaccount_is_primary_for_stocks'),
    ]

    operations = [
        migrations.AddField(
            model_name='etoroaccount',
            name='last_available_cash',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=18, null=True),
        ),
        migrations.AddField(
            model_name='etoroaccount',
            name='last_used_margin',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=18, null=True),
        ),
        migrations.AddField(
            model_name='etoroaccount',
            name='last_margin_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
