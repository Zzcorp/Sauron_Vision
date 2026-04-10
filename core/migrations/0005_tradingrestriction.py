# Generated manually — adds the TradingRestriction model to the core app.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_auditlog'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='TradingRestriction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('restriction_type', models.CharField(
                    choices=[
                        ('blackout', 'Blackout Period'),
                        ('position_limit', 'Position Limit'),
                        ('instrument_ban', 'Instrument Ban'),
                        ('daily_limit', 'Daily Trading Limit'),
                    ],
                    max_length=20,
                )),
                ('instrument_symbol', models.CharField(blank=True, max_length=20)),
                ('description', models.TextField()),
                ('start_date', models.DateTimeField(blank=True, null=True)),
                ('end_date', models.DateTimeField(blank=True, null=True)),
                ('max_quantity', models.DecimalField(blank=True, decimal_places=8, max_digits=20, null=True)),
                ('max_value', models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True)),
                ('max_trades_per_day', models.IntegerField(blank=True, null=True)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='trading_restrictions',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
