"""Correct the operator-facing documentation of `OpportunitySetup.sizing`.

help_text only — no schema change, no SQL. The old text advertised
`stop_atr_mult` and `target_pct`, neither of which `_suggested_levels` reads,
so the admin HQ form was instructing operators to type the two dead keys the
same wave had just finished removing from six seeded setups.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('signals', '0014_fastevent'),
    ]

    operations = [
        migrations.AlterField(
            model_name='opportunitysetup',
            name='sizing',
            field=models.JSONField(
                blank=True, default=dict,
                help_text='Sizing config: {"stop_pct": 2.0, "target_rr": 2.0}. '
                          'Those two keys and no others — anything else is discarded.',
            ),
        ),
    ]
