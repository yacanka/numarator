import django_filters
from django.db import models

from .models import DocumentFormat


class DocumentFormatFilter(django_filters.FilterSet):
    """Filter formats by lifecycle, category, search text, and dates."""

    status = django_filters.CharFilter(lookup_expr='exact')
    category = django_filters.NumberFilter()
    search = django_filters.CharFilter(method='filter_search')
    created_after = django_filters.DateFilter(field_name='created_at', lookup_expr='date__gte')
    created_before = django_filters.DateFilter(field_name='created_at', lookup_expr='date__lte')

    def filter_search(self, queryset, name, value):
        """Return formats matching a free-text search term."""
        return queryset.filter(
            models.Q(name__icontains=value)
            | models.Q(code__icontains=value)
            | models.Q(description__icontains=value)
        )

    class Meta:
        model = DocumentFormat
        fields = ['status', 'category']
