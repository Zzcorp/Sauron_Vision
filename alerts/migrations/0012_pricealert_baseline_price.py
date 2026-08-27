# Generated manually — the side of the target a 'cross' alert is measured
# from. NULL on every existing row: those alerts arm on the next beat.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('alerts', '0011_alter_notification_notification_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='pricealert',
            name='baseline_price',
            field=models.DecimalField(blank=True, decimal_places=8,
                                      max_digits=20, null=True),
        ),
    ]
