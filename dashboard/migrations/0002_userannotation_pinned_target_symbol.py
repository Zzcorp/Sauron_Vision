# Adds target_symbol and pinned fields to UserAnnotation, updates choices and color default.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="userannotation",
            name="target_symbol",
            field=models.CharField(blank=True, max_length=20, default=""),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="userannotation",
            name="pinned",
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name="userannotation",
            name="color",
            field=models.CharField(default="#ffeb3b", max_length=7),
        ),
        migrations.AlterField(
            model_name="userannotation",
            name="annotation_type",
            field=models.CharField(
                choices=[
                    ("signal", "Signal Note"),
                    ("instrument", "Instrument Note"),
                    ("strategy", "Strategy Note"),
                    ("position", "Position"),
                    ("chart", "Chart"),
                    ("general", "General Note"),
                ],
                default="general",
                max_length=20,
            ),
        ),
        migrations.AlterModelOptions(
            name="userannotation",
            options={"ordering": ["-pinned", "-created_at"]},
        ),
    ]
