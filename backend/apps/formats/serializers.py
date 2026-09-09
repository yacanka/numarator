# apps/formats/serializers.py
from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field
from .models import DocumentFormat, FormatCategory, FormatSequence, FormatVersion
from .engine.segments import SEGMENT_REGISTRY, SegmentConfig, get_segment_class


class SegmentConfigSerializer(serializers.Serializer):
    """Validates individual segment configuration"""
    type = serializers.ChoiceField(choices=list(SEGMENT_REGISTRY.keys()))
    config = serializers.DictField(default=dict)
    order = serializers.IntegerField(default=0)
    label = serializers.CharField(max_length=100, required=False, allow_blank=True)

    def validate(self, attrs):
        seg_type = attrs['type']
        config = attrs.get('config', {})

        try:
            cls = get_segment_class(seg_type)
            cls(SegmentConfig(**config))
        except (ValueError, TypeError) as e:
            raise serializers.ValidationError(
                {'config': str(e)}
            )

        return attrs


class FormatCategorySerializer(serializers.ModelSerializer):
    code = serializers.SlugField(max_length=50)

    class Meta:
        model = FormatCategory
        fields = ['id', 'name', 'code', 'color', 'icon', 'order']

    def validate_code(self, value):
        """Reject duplicate generated category codes with clear feedback."""
        queryset = FormatCategory.objects.filter(code=value)
        if self.instance is not None:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError(
                'A category with this generated code already exists. Use a different name.'
            )
        return value


class DocumentFormatListSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    category_color = serializers.CharField(source='category.color', read_only=True)
    total_generated = serializers.IntegerField(read_only=True)
    preview = serializers.CharField(read_only=True, source='generate_preview')

    class Meta:
        model = DocumentFormat
        fields = [
            'id', 'code', 'name', 'description', 'status',
            'category', 'category_name', 'category_color',
            'sequence_reset_period', 'example_output',
            'total_generated', 'preview', 'tags',
            'created_at', 'updated_at',
        ]


class DocumentFormatDetailSerializer(serializers.ModelSerializer):
    segments_config = SegmentConfigSerializer(many=True)
    category_detail = FormatCategorySerializer(source='category', read_only=True)
    total_generated = serializers.IntegerField(read_only=True)
    preview = serializers.SerializerMethodField()
    current_sequence = serializers.SerializerMethodField()

    class Meta:
        model = DocumentFormat
        fields = [
            'id', 'code', 'name', 'description', 'status',
            'category', 'category_detail',
            'segments_config',
            'sequence_reset_period', 'sequence_start', 'sequence_step',
            'validation_regex', 'example_output',
            'total_generated', 'preview', 'current_sequence',
            'tags', 'created_at', 'updated_at', 'created_by',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'created_by']

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_preview(self, obj):
        try:
            return obj.generate_preview()
        except Exception:
            return None

    @extend_schema_field(serializers.IntegerField())
    def get_current_sequence(self, obj):
        from django.utils import timezone
        from .engine.generator import DocumentNumberGenerator
        from .models import FormatSequence

        gen = DocumentNumberGenerator(obj)
        period_key = gen._get_period_key(timezone.now(), obj.sequence_reset_period)

        seq = FormatSequence.objects.filter(
            format=obj,
            period_key=period_key
        ).first()

        return seq.current_value if seq else obj.sequence_start

    def validate_code(self, value):
        return value.upper()

    def validate_segments_config(self, value):
        if not value:
            raise serializers.ValidationError("At least one segment is required")
        if len(value) > 20:
            raise serializers.ValidationError("Maximum 20 segments allowed")
        return value

    def create(self, validated_data):
        validated_data['created_by'] = self.context['request'].user
        return super().create(validated_data)

    def update(self, instance, validated_data):
        # Save version before update
        if 'segments_config' in validated_data:
            self._save_version(instance)
        return super().update(instance, validated_data)

    def _save_version(self, instance):
        last_version = instance.versions.first()
        version_number = (last_version.version_number + 1) if last_version else 1

        FormatVersion.objects.create(
            format=instance,
            version_number=version_number,
            segments_config=instance.segments_config,
            changed_by=self.context['request'].user,
        )


class GenerateDocumentSerializer(serializers.Serializer):
    """Input for generating a document number"""
    context_data = serializers.DictField(
        required=False,
        default=dict,
        help_text='Dynamic context values (department, category, etc.)'
    )
    metadata = serializers.DictField(
        required=False,
        default=dict,
        help_text='Additional metadata to store'
    )
    count = serializers.IntegerField(
        required=False,
        default=1,
        min_value=1,
        max_value=100,
        help_text='Number of documents to generate (bulk)'
    )

    def validate_context_data(self, value):
        # Validate context data values are strings or numbers
        for k, v in value.items():
            if not isinstance(v, (str, int, float, bool)):
                raise serializers.ValidationError(
                    f"Context value for '{k}' must be string or number"
                )
        return value


class BulkGenerateSerializer(serializers.Serializer):
    count = serializers.IntegerField(min_value=1, max_value=1000)
    context_data = serializers.DictField(required=False, default=dict)
    metadata = serializers.DictField(required=False, default=dict)
