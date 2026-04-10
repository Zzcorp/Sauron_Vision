# Generated manually — adds WebhookEndpoint model to the alerts app.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('alerts', '0004_pricealert'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='WebhookEndpoint',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('url', models.URLField()),
                ('secret', models.CharField(blank=True, help_text='Shared secret for HMAC signing', max_length=100)),
                ('is_active', models.BooleanField(default=True)),
                ('on_signal', models.BooleanField(default=True)),
                ('on_trade', models.BooleanField(default=True)),
                ('on_alert', models.BooleanField(default=True)),
                ('on_portfolio', models.BooleanField(default=False)),
                ('on_news', models.BooleanField(default=False)),
                ('total_sent', models.IntegerField(default=0)),
                ('last_sent_at', models.DateTimeField(blank=True, null=True)),
                ('last_error', models.TextField(blank=True)),
                ('consecutive_failures', models.IntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='webhooks',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
