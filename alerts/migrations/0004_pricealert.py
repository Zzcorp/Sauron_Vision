# Generated manually — adds the PriceAlert model to the alerts app.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('alerts', '0003_notification'),
        ('instruments', '__first__'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='PriceAlert',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('condition', models.CharField(choices=[('above', 'Price Above'), ('below', 'Price Below'), ('cross', 'Price Crosses')], max_length=10)),
                ('target_price', models.DecimalField(decimal_places=8, max_digits=20)),
                ('triggered', models.BooleanField(default=False)),
                ('triggered_at', models.DateTimeField(blank=True, null=True)),
                ('notify_telegram', models.BooleanField(default=True)),
                ('notify_email', models.BooleanField(default=False)),
                ('note', models.CharField(blank=True, max_length=200)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('instrument', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='instruments.instrument')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='price_alerts', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
