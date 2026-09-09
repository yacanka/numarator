import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('documents', '0002_external_integration_fields'),
        ('integrations', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='IdempotencyRecord',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('key', models.CharField(max_length=128)),
                ('request_hash', models.CharField(max_length=64)),
                ('credential', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='idempotency_records', to='integrations.apicredential')),
                ('document', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='idempotency_records', to='documents.generateddocument')),
            ],
        ),
        migrations.AddConstraint(
            model_name='idempotencyrecord',
            constraint=models.UniqueConstraint(fields=('credential', 'key'), name='unique_idempotency_key_per_credential'),
        ),
    ]
