# Generated migration for AgentPrediction model

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ai_agents', '0002_aimemory'),
    ]

    operations = [
        migrations.CreateModel(
            name='AgentPrediction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('agent', models.CharField(db_index=True, max_length=50)),
                ('prediction_type', models.CharField(max_length=30)),
                ('instrument_symbol', models.CharField(blank=True, max_length=20)),
                ('predicted_value', models.CharField(max_length=100)),
                ('actual_value', models.CharField(blank=True, max_length=100)),
                ('confidence', models.FloatField(default=0.5)),
                ('was_correct', models.BooleanField(null=True)),
                ('evaluation_notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('evaluated_at', models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='agentprediction',
            index=models.Index(fields=['agent', '-created_at'], name='ai_agents_a_agent_created_idx'),
        ),
    ]
