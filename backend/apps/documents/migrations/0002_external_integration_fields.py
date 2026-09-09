import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('documents', '0001_initial'),
        ('integrations', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='generateddocument',
            name='external_reference',
            field=models.CharField(blank=True, db_index=True, max_length=200),
        ),
        migrations.AddField(
            model_name='generateddocument',
            name='source_credential',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='generated_documents', to='integrations.apicredential'),
        ),
    ]
