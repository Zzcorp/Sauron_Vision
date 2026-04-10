# Generated manually — adds the AuditLog model to the core app.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_featureflag'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AuditLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('action', models.CharField(choices=[
                    ('bot_toggle', 'Bot Enabled/Disabled'),
                    ('trade_open', 'Trade Opened'),
                    ('trade_close', 'Trade Closed'),
                    ('strategy_approve', 'Strategy Approved'),
                    ('strategy_reject', 'Strategy Rejected'),
                    ('kill_switch', 'Kill Switch Activated'),
                    ('config_change', 'Configuration Changed'),
                    ('login', 'User Login'),
                    ('alert_triggered', 'Alert Triggered'),
                    ('position_open', 'Position Opened'),
                    ('position_close', 'Position Closed'),
                ], max_length=30)),
                ('target_type', models.CharField(blank=True, max_length=50)),
                ('target_id', models.IntegerField(blank=True, null=True)),
                ('description', models.TextField()),
                ('ip_address', models.GenericIPAddressField(blank=True, null=True)),
                ('metadata', models.JSONField(default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='audit_logs',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='auditlog',
            index=models.Index(fields=['user', '-created_at'], name='core_audit_user_idx'),
        ),
        migrations.AddIndex(
            model_name='auditlog',
            index=models.Index(fields=['action', '-created_at'], name='core_audit_action_idx'),
        ),
    ]
