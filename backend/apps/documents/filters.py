# apps/documents/filters.py
import django_filters
from .models import GeneratedDocument


class GeneratedDocumentFilter(django_filters.FilterSet):
    """Filter generated documents without using DRF reserved query names."""

    format_id = django_filters.UUIDFilter(field_name='format_id')
    status = django_filters.CharFilter(lookup_expr='exact')
    search = django_filters.CharFilter(field_name='document_number', lookup_expr='icontains')
    date_from = django_filters.DateFilter(field_name='generated_at', lookup_expr='date__gte')
    date_to = django_filters.DateFilter(field_name='generated_at', lookup_expr='date__lte')
    generated_by = django_filters.NumberFilter(field_name='generated_by__id')

    class Meta:
        model = GeneratedDocument
        fields = ['format_id', 'status', 'generated_by']
