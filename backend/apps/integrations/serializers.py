import json

from django.utils import timezone
from drf_spectacular.utils import extend_schema_field, extend_schema_serializer
from rest_framework import serializers

from apps.documents.models import GeneratedDocument
from apps.formats.models import DocumentFormat
from apps.formats.serializers import GenerateDocumentSerializer

from .models import API_SCOPES, ApiCredential


def validate_required_format_context(document_format, context_data):
    """Reject generation when a context segment has no value or configured default."""
    missing_keys = []
    for segment in document_format.segments_config:
        if segment.get('type') != 'context':
            continue
        config = segment.get('config', {})
        key = config.get('key')
        if key and 'default' not in config and key not in context_data:
            missing_keys.append(key)
    if missing_keys:
        raise serializers.ValidationError({
            'context_data': {
                key: 'This context value is required by the selected format.'
                for key in missing_keys
            }
        })


class ApiCredentialSerializer(serializers.ModelSerializer):
    """Expose credential metadata while never returning its stored hash."""

    allowed_formats = serializers.PrimaryKeyRelatedField(many=True, read_only=True)
    allowed_format_codes = serializers.SerializerMethodField()
    all_formats = serializers.SerializerMethodField()
    active = serializers.BooleanField(source='is_usable', read_only=True)

    class Meta:
        model = ApiCredential
        fields = [
            'id', 'name', 'key_prefix', 'scopes', 'allowed_formats',
            'allowed_format_codes', 'all_formats', 'active', 'expires_at',
            'revoked_at', 'last_used_at', 'created_at',
        ]

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_allowed_format_codes(self, credential):
        return [item.code for item in credential.allowed_formats.all()]

    @extend_schema_field(serializers.BooleanField())
    def get_all_formats(self, credential):
        return not credential.allowed_formats.exists()


class ApiCredentialCreateSerializer(serializers.Serializer):
    """Validate API key issuance settings supplied by an authenticated user."""

    name = serializers.CharField(max_length=100)
    scopes = serializers.ListField(
        child=serializers.ChoiceField(choices=list(API_SCOPES)),
        required=True,
        allow_empty=False,
    )
    allowed_formats = serializers.PrimaryKeyRelatedField(
        queryset=DocumentFormat.objects.all(),
        many=True,
        required=True,
    )
    expires_at = serializers.DateTimeField(required=False, allow_null=True)

    def validate_scopes(self, scopes):
        if len(scopes) != len(set(scopes)):
            raise serializers.ValidationError('Scopes cannot contain duplicate values.')
        return scopes

    def validate_expires_at(self, expires_at):
        if expires_at is not None and expires_at <= timezone.now():
            raise serializers.ValidationError('Expiration must be in the future.')
        return expires_at

    def create(self, validated_data):
        allowed_formats = validated_data.pop('allowed_formats', [])
        owner = validated_data.pop('owner')
        credential, raw_key = ApiCredential.issue(owner=owner, **validated_data)
        credential.allowed_formats.set(allowed_formats)
        self.raw_key = raw_key
        return credential


class PrivateFormatSerializer(serializers.ModelSerializer):
    """Describe the active format contract needed by external callers."""

    preview = serializers.SerializerMethodField()
    required_context = serializers.SerializerMethodField()

    class Meta:
        model = DocumentFormat
        fields = [
            'code', 'name', 'description', 'preview', 'required_context',
            'sequence_reset_period', 'tags', 'updated_at',
        ]

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_preview(self, document_format):
        try:
            return document_format.generate_preview()
        except (TypeError, ValueError):
            return None

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_required_context(self, document_format):
        fields = []
        for segment in document_format.segments_config:
            if segment.get('type') != 'context':
                continue
            config = segment.get('config', {})
            fields.append({
                'key': config.get('key'),
                'required': 'default' not in config,
                'default': config.get('default'),
                'max_length': config.get('max_length', 10),
            })
        return fields


class PrivateFormatPreviewSerializer(GenerateDocumentSerializer):
    """Reuse generation context validation without accepting persistence fields."""

    metadata = None
    count = None


class PrivateNumberCreateSerializer(GenerateDocumentSerializer):
    """Validate a single idempotent private API number request."""

    format_code = serializers.SlugField(max_length=50)
    external_reference = serializers.CharField(
        max_length=200,
        required=False,
        allow_blank=True,
        default='',
    )
    count = None

    def validate_context_data(self, value):
        value = super().validate_context_data(value)
        self._validate_json_size(value, 8192, 'context_data')
        return value

    def validate_metadata(self, value):
        self._validate_json_size(value, 16384, 'metadata')
        return value

    @staticmethod
    def _validate_json_size(value, maximum_bytes, field_name):
        try:
            encoded = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        except (TypeError, ValueError) as error:
            raise serializers.ValidationError(f'{field_name} must contain valid JSON values.') from error
        if len(encoded) > maximum_bytes:
            raise serializers.ValidationError(
                f'{field_name} cannot exceed {maximum_bytes} bytes.'
            )


class PrivateGeneratedDocumentSerializer(serializers.ModelSerializer):
    """Return the stable external representation of an issued number."""

    format_code = serializers.CharField(source='format.code', read_only=True)
    valid = serializers.BooleanField(source='is_valid', read_only=True)

    class Meta:
        model = GeneratedDocument
        fields = [
            'id', 'document_number', 'format_code', 'status', 'valid',
            'external_reference', 'context_data', 'metadata', 'generated_at',
            'used_at', 'cancelled_at', 'cancellation_reason',
        ]


class PrivateNumberValidationSerializer(serializers.Serializer):
    document_number = serializers.CharField(max_length=200)


class PrivateNumberStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=['used', 'cancelled'])
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True, default='')

    def validate(self, attrs):
        if attrs['status'] == 'used' and attrs.get('reason'):
            raise serializers.ValidationError({'reason': 'Reason is only accepted for cancellation.'})
        return attrs


class PrivatePaginationSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    total_pages = serializers.IntegerField()
    current_page = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    page_size = serializers.IntegerField()


class PrivateFormatResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    data = PrivateFormatSerializer()


@extend_schema_serializer(many=False)
class PrivateFormatListResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    data = PrivateFormatSerializer(many=True)
    pagination = PrivatePaginationSerializer()


class PrivateFormatPreviewDataSerializer(serializers.Serializer):
    preview = serializers.CharField()


class PrivateFormatPreviewResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    data = PrivateFormatPreviewDataSerializer()


class PrivateGeneratedDocumentResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    data = PrivateGeneratedDocumentSerializer()


@extend_schema_serializer(many=False)
class PrivateGeneratedDocumentListResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    data = PrivateGeneratedDocumentSerializer(many=True)
    pagination = PrivatePaginationSerializer()


class PrivateNumberValidationDataSerializer(serializers.Serializer):
    exists = serializers.BooleanField()
    valid = serializers.BooleanField()
    status = serializers.ChoiceField(
        choices=GeneratedDocument.STATUS_CHOICES,
        required=False,
    )
    document = PrivateGeneratedDocumentSerializer(required=False)


class PrivateNumberValidationResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    data = PrivateNumberValidationDataSerializer()
