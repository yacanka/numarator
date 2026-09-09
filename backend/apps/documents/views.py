# apps/documents/views.py
import logging
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Count, Q
from django.utils import timezone
from datetime import timedelta

from .models import GeneratedDocument
from .serializers import (
    GeneratedDocumentSerializer,
    CancelDocumentSerializer,
    DocumentStatusUpdateSerializer,
    DocumentStatsSerializer,
)
from .filters import GeneratedDocumentFilter
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, OpenApiParameter

logger = logging.getLogger(__name__)


class GeneratedDocumentViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = GeneratedDocumentSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = GeneratedDocumentFilter

    def get_queryset(self):
        return GeneratedDocument.objects.select_related(
            'format', 'generated_by'
        ).order_by('-generated_at')

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return Response({'success': True, 'data': serializer.data})

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response({'success': True, 'data': serializer.data})

    @action(detail=True, methods=['post'], url_path='cancel')
    def cancel(self, request, pk=None):
        doc = self.get_object()

        if doc.status != 'active':
            return Response(
                {'success': False, 'error': {'message': f'Document is already {doc.status}'}},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = CancelDocumentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        doc.cancel(
            reason=serializer.validated_data.get('reason', ''),
            user=request.user
        )

        return Response({'success': True, 'message': 'Document cancelled'})

    @action(detail=True, methods=['post'], url_path='mark-used')
    def mark_used(self, request, pk=None):
        doc = self.get_object()

        if doc.status != 'active':
            return Response(
                {'success': False, 'error': {'message': f'Document is {doc.status}'}},
                status=status.HTTP_400_BAD_REQUEST
            )

        doc.mark_used()
        return Response({'success': True, 'message': 'Document marked as used'})

    @action(detail=True, methods=['patch'], url_path='status')
    def update_status(self, request, pk=None):
        """Update a generated document number lifecycle status."""
        doc = self.get_object()
        serializer = DocumentStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        doc.change_status(
            serializer.validated_data['status'],
            reason=serializer.validated_data.get('reason', '')
        )
        data = self.get_serializer(doc).data
        return Response({'success': True, 'data': data})

    @extend_schema(parameters=[OpenApiParameter('number', str, OpenApiParameter.PATH)])
    @action(detail=False, methods=['get'], url_path='validate/(?P<number>[^/.]+)')
    def validate_number(self, request, number=None):
        """Validate if a document number exists and is active"""
        try:
            doc = GeneratedDocument.objects.get(document_number=number)
            return Response({
                'success': True,
                'data': {
                    'valid': True,
                    'exists': True,
                    'status': doc.status,
                    'document': GeneratedDocumentSerializer(doc).data,
                }
            })
        except GeneratedDocument.DoesNotExist:
            return Response({
                'success': True,
                'data': {'valid': False, 'exists': False}
            })

    @action(detail=False, methods=['get'], url_path='stats')
    def stats(self, request):
        today = timezone.now().date()
        month_start = today.replace(day=1)
        week_start = today - timedelta(days=7)

        qs = GeneratedDocument.objects.all()

        # Status counts
        status_counts = qs.values('status').annotate(count=Count('id'))
        status_map = {s['status']: s['count'] for s in status_counts}

        # By format
        by_format = list(
            qs.values('format__code', 'format__name')
            .annotate(count=Count('id'))
            .order_by('-count')[:10]
        )

        # Daily trend (last 30 days)
        from django.db.models.functions import TruncDate
        daily_trend = list(
            qs.filter(generated_at__date__gte=today - timedelta(days=30))
            .annotate(date=TruncDate('generated_at'))
            .values('date')
            .annotate(count=Count('id'))
            .order_by('date')
        )

        data = {
            'total_generated': qs.count(),
            'active_count': status_map.get('active', 0),
            'cancelled_count': status_map.get('cancelled', 0),
            'used_count': status_map.get('used', 0),
            'today_count': qs.filter(generated_at__date=today).count(),
            'this_week_count': qs.filter(generated_at__date__gte=week_start).count(),
            'this_month_count': qs.filter(generated_at__date__gte=month_start).count(),
            'by_format': by_format,
            'daily_trend': daily_trend,
        }

        return Response({'success': True, 'data': data})
