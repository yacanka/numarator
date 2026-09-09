import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('formats', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='GeneratedDocument',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('document_number', models.CharField(db_index=True, max_length=200, unique=True)),
                ('sequence_value', models.BigIntegerField()),
                ('status', models.CharField(choices=[('active', 'Aktif'), ('cancelled', 'İptal Edildi'), ('used', 'Kullanıldı'), ('expired', 'Süresi Doldu')], default='active', max_length=20)),
                ('context_data', models.JSONField(default=dict)),
                ('metadata', models.JSONField(default=dict)),
                ('generated_at', models.DateTimeField()),
                ('used_at', models.DateTimeField(blank=True, null=True)),
                ('cancelled_at', models.DateTimeField(blank=True, null=True)),
                ('cancellation_reason', models.TextField(blank=True)),
                ('format', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='generated_documents', to='formats.documentformat')),
                ('generated_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='generated_documents', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Generated Document',
                'verbose_name_plural': 'Generated Documents',
                'ordering': ['-generated_at'],
                'indexes': [
                    models.Index(fields=['format', 'generated_at'], name='documents_g_format_75a5e9_idx'),
                    models.Index(fields=['status', 'generated_at'], name='documents_g_status_613c1e_idx'),
                    models.Index(fields=['document_number'], name='documents_g_documen_cfa8b0_idx'),
                ],
            },
        ),
    ]
