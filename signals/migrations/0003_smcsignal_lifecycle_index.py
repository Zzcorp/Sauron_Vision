from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("signals", "0002_smcsignal")]

    operations = [
        migrations.AddIndex(
            model_name="smcsignal",
            index=models.Index(
                fields=["status", "created_at"],
                name="signals_smc_status_created_idx",
            ),
        ),
    ]
