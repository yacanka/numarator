import django_filters

from apps.documents.models import GeneratedDocument


class PrivateGeneratedDocumentFilter(django_filters.FilterSet):
    """Filter reconciliation queries exposed to external applications."""

    format_code = django_filters.CharFilter(field_name='format__code', lookup_expr='iexact')
    document_number = django_filters.CharFilter(lookup_expr='exact')
    external_reference = django_filters.CharFilter(lookup_expr='exact')
    generated_from = django_filters.IsoDateTimeFilter(field_name='generated_at', lookup_expr='gte')
    generated_to = django_filters.IsoDateTimeFilter(field_name='generated_at', lookup_expr='lte')

    class Meta:
        model = GeneratedDocument
        fields = ['format_code', 'document_number', 'external_reference', 'status']
