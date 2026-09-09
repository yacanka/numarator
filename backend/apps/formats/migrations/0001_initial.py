import django.core.validators
import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [
        migrations.CreateModel(
            name='FormatCategory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('code', models.SlugField(max_length=50, unique=True)),
                ('color', models.CharField(default='#1890ff', max_length=7)),
                ('icon', models.CharField(default='document', max_length=50)),
                ('order', models.PositiveIntegerField(default=0)),
            ],
            options={
                'verbose_name': 'Format Category',
                'verbose_name_plural': 'Format Categories',
                'ordering': ['order', 'name'],
            },
        ),
        migrations.CreateModel(
            name='DocumentFormat',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('is_deleted', models.BooleanField(default=False)),
                ('deleted_at', models.DateTimeField(blank=True, null=True)),
                ('code', models.SlugField(max_length=50, unique=True, validators=[django.core.validators.RegexValidator('^[A-Z0-9_]+$', 'Only uppercase letters, numbers, underscore')])),
                ('name', models.CharField(max_length=100)),
                ('description', models.TextField(blank=True)),
                ('status', models.CharField(choices=[('draft', 'Taslak'), ('active', 'Aktif'), ('deprecated', 'Kullanım Dışı'), ('archived', 'Arşivlendi')], default='draft', max_length=20)),
                ('segments_config', models.JSONField(default=list, help_text='List of segment configurations')),
                ('sequence_reset_period', models.CharField(choices=[('never', 'Hiçbir Zaman'), ('daily', 'Günlük'), ('weekly', 'Haftalık'), ('monthly', 'Aylık'), ('quarterly', 'Çeyreklik'), ('yearly', 'Yıllık')], default='never', max_length=20)),
                ('sequence_start', models.PositiveIntegerField(default=1)),
                ('sequence_step', models.PositiveIntegerField(default=1)),
                ('validation_regex', models.CharField(blank=True, max_length=500)),
                ('example_output', models.CharField(blank=True, max_length=200)),
                ('tags', models.JSONField(default=list)),
                ('category', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='formats', to='formats.formatcategory')),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_formats', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Document Format',
                'verbose_name_plural': 'Document Formats',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='FormatVersion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('version_number', models.PositiveIntegerField()),
                ('segments_config', models.JSONField()),
                ('change_note', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('changed_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ('format', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='versions', to='formats.documentformat')),
            ],
            options={'ordering': ['-version_number'], 'unique_together': {('format', 'version_number')}},
        ),
        migrations.CreateModel(
            name='FormatSequence',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('period_key', models.CharField(max_length=20)),
                ('current_value', models.BigIntegerField(default=1)),
                ('step', models.PositiveIntegerField(default=1)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('format', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='sequences', to='formats.documentformat')),
            ],
            options={'verbose_name': 'Format Sequence', 'unique_together': {('format', 'period_key')}},
        ),
    ]
