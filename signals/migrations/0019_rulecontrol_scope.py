# The rule's reach and cadence (2026-10-04): where it may fire, and how
# long after one of its signals closes it may fire again on that symbol.
# {} means the code defaults (signals/rule_scope.DEFAULT_RULE_SCOPE).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('signals', '0018_ruleaction_source_brain_report'),
    ]

    operations = [
        migrations.AddField(
            model_name='rulecontrol',
            name='scope',
            field=models.JSONField(
                blank=True, default=dict,
                help_text='Where the rule may fire and how often: '
                          '{"exclude": {"asset_classes": [], "sectors": [], '
                          '"symbols": [], "groups": []}, "cooldown_hours": 24}. '
                          'Empty means the code defaults (signals.rule_scope).'),
        ),
    ]
