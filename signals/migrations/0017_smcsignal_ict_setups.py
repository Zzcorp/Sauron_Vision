"""Let SmcSignal.setup hold the five ICT setups the scanner can now emit.

Mitigation blocks, optimal trade entry, the Judas swing, the Silver Bullet and
SMT divergence were built, tested and callable, and every one of them returned a
`setup` string this column's choices could not name — so `scan_symbol` could
detect them and `persist_cards` could not store them. Choices are not a database
constraint, so this migration changes nothing about the rows already there and
nothing about what the column will physically accept; it changes what
`full_clean`, the admin and the model forms will accept, and it is what keeps
`SETUP_CHOICES` an honest description of the feed.

No data step. The five values have never been written, precisely because
nothing could write them.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("signals", "0016_smcsignal_dedupe_and_hit_rate_sample"),
    ]

    operations = [
        migrations.AlterField(
            model_name="smcsignal",
            name="setup",
            field=models.CharField(
                choices=[
                    ("RP_BREAKER", "RP Breaker"),
                    ("THREE_TAP", "Three Tap"),
                    ("RANGE_MSB_SD", "Range + MSB + SD"),
                    ("REVERSAL_PATTERN", "Reversal Pattern"),
                    ("PO3", "Power of Three"),
                    ("FVG_TAP", "FVG Tap"),
                    ("OB_RETEST", "Order Block Retest"),
                    ("SFP", "Swing Failure Pattern"),
                    ("MITIGATION_BLOCK", "Mitigation Block Retest"),
                    ("OTE", "Optimal Trade Entry"),
                    ("JUDAS_SWING", "Judas Swing"),
                    ("SILVER_BULLET", "Silver Bullet"),
                    ("SMT_DIVERGENCE", "SMT Divergence"),
                ],
                max_length=32,
            ),
        ),
    ]
