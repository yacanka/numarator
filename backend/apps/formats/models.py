# apps/formats/models.py
from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import RegexValidator
from apps.core.models import SoftDeleteModel

User = get_user_model()


class DocumentFormat(SoftDeleteModel):
    """Document number format definition"""

    RESET_PERIOD_CHOICES = [
        ('never', 'Hiçbir Zaman'),
        ('daily', 'Günlük'),
        ('weekly', 'Haftalık'),
        ('monthly', 'Aylık'),
        ('quarterly', 'Çeyreklik'),
        ('yearly', 'Yıllık'),
    ]

    STATUS_CHOICES = [
        ('draft', 'Taslak'),
        ('active', 'Aktif'),
        ('deprecated', 'Kullanım Dışı'),
        ('archived', 'Arşivlendi'),
    ]

    code = models.SlugField(
        max_length=50,
        unique=True,
        validators=[RegexValidator(r'^[A-Z0-9_]+$', 'Only uppercase letters, numbers, underscore')]
    )
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    category = models.ForeignKey(
        'FormatCategory',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='formats'
    )

    # Segment configuration (JSON)
    segments_config = models.JSONField(
        default=list,
        help_text='List of segment configurations'
    )

    # Sequence settings
    sequence_reset_period = models.CharField(
        max_length=20,
        choices=RESET_PERIOD_CHOICES,
        default='never'
    )
    sequence_start = models.PositiveIntegerField(default=1)
    sequence_step = models.PositiveIntegerField(default=1)

    # Validation
    validation_regex = models.CharField(max_length=500, blank=True)
    example_output = models.CharField(max_length=200, blank=True)

    # Metadata
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_formats'
    )
    tags = models.JSONField(default=list)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Document Format'
        verbose_name_plural = 'Document Formats'

    def __str__(self):
        return f"{self.code} - {self.name}"

    def get_generator(self):
        from .engine.generator import DocumentNumberGenerator
        return DocumentNumberGenerator(self)

    def generate_preview(self, context_data=None):
        return self.get_generator().preview(context_data)

    @property
    def total_generated(self):
        """Return generated document count without extra queries when annotated."""
        cached_count = getattr(self, '_total_generated', None)
        if cached_count is not None:
            return cached_count
        return self.generated_documents.count()

    @property
    def is_active(self):
        return self.status == 'active'


class FormatCategory(models.Model):
    name = models.CharField(max_length=100)
    code = models.SlugField(max_length=50, unique=True)
    color = models.CharField(max_length=7, default='#1890ff')
    icon = models.CharField(max_length=50, default='document')
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'name']
        verbose_name = 'Format Category'
        verbose_name_plural = 'Format Categories'

    def __str__(self):
        return self.name


class FormatSequence(models.Model):
    """Tracks current sequence value per format and period"""
    format = models.ForeignKey(
        DocumentFormat,
        on_delete=models.CASCADE,
        related_name='sequences'
    )
    period_key = models.CharField(max_length=20)
    current_value = models.BigIntegerField(default=1)
    step = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('format', 'period_key')]
        verbose_name = 'Format Sequence'

    def __str__(self):
        return f"{self.format.code} [{self.period_key}]: {self.current_value}"


class FormatVersion(models.Model):
    """Immutable version history of formats"""
    format = models.ForeignKey(
        DocumentFormat,
        on_delete=models.CASCADE,
        related_name='versions'
    )
    version_number = models.PositiveIntegerField()
    segments_config = models.JSONField()
    changed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True
    )
    change_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('format', 'version_number')]
        ordering = ['-version_number']

    def __str__(self):
        return f"{self.format.code} v{self.version_number}"