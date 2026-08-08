"""Phase 1.0 — extend Signal with self-grading fields (MFE/MAE/realized R/duration)."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("signals", "0005_remove_smcsignal_signals_smc_status_created_idx"),
    ]

    operations = [
        migrations.AddField(
            model_name="signal",
            name="realized_r",
            field=models.FloatField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name="signal",
            name="mfe",
            field=models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True),
        ),
        migrations.AddField(
            model_name="signal",
            name="mae",
            field=models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True),
        ),
        migrations.AddField(
            model_name="signal",
            name="time_to_outcome_seconds",
            field=models.IntegerField(null=True, blank=True),
        ),
        migrations.AddIndex(
            model_name="signal",
            index=models.Index(
                fields=["outcome", "expired_at"],
                name="signals_sig_outcome_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="signal",
            index=models.Index(
                fields=["signal_type", "expired_at"],
                name="signals_sig_type_idx",
            ),
        ),
    ]
