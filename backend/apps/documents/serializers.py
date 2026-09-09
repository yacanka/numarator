# apps/documents/serializers.py
from rest_framework import serializers
from .models import GeneratedDocument


class GeneratedDocumentSerializer(serializers.ModelSerializer):
    format_code = serializers.CharField(source='format.code', read_only=True)
    format_name = serializers.CharField(source='format.name', read_only=True)
    generated_by_username = serializers.CharField(
        source='generated_by.username',
        read_only=True
    )

    class Meta:
        model = GeneratedDocument
        fields = [
            'id', 'document_number', 'format', 'format_code', 'format_name',
            'status', 'sequence_value',
            'context_data', 'metadata',
            'external_reference',
            'generated_by', 'generated_by_username',
            'generated_at', 'used_at', 'cancelled_at', 'cancellation_reason',
        ]
        read_only_fields = ['id', 'document_number', 'sequence_value', 'generated_at']


class CancelDocumentSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True)


class DocumentStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=GeneratedDocument.STATUS_CHOICES)
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True)


class DocumentStatsSerializer(serializers.Serializer):
    total_generated = serializers.IntegerField()
    active_count = serializers.IntegerField()
    cancelled_count = serializers.IntegerField()
    used_count = serializers.IntegerField()
    today_count = serializers.IntegerField()
    this_month_count = serializers.IntegerField()
    by_format = serializers.ListField()
    recent_activity = serializers.ListField()
