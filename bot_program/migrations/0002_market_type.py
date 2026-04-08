from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [("bot_program", "0001_initial")]
    operations = [
        migrations.AddField(
            model_name="botconfig",
            name="market_type",
            field=models.CharField(
                max_length=10, default="spot",
                choices=[("spot","Spot"),("futures","USDT-M Futures")]),
        ),
        migrations.AddField(
            model_name="botconfig",
            name="margin_mode",
            field=models.CharField(
                max_length=10, default="isolated",
                choices=[("isolated","Isolated"),("cross","Cross")]),
        ),
    ]
