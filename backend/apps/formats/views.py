# apps/formats/views.py
import logging
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Count, Q
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, OpenApiParameter

from .models import DocumentFormat, FormatCategory, FormatVersion
from .serializers import (
    DocumentFormatListSerializer,
    DocumentFormatDetailSerializer,
    FormatCategorySerializer,
    GenerateDocumentSerializer,
    BulkGenerateSerializer,
)
from .filters import DocumentFormatFilter
from apps.documents.serializers import GeneratedDocumentSerializer
from apps.core.throttles import GenerateRateThrottle

logger = logging.getLogger(__name__)


class FormatCategoryViewSet(viewsets.ModelViewSet):
    queryset = FormatCategory.objects.all()
    serializer_class = FormatCategorySerializer
    permission_classes = [permissions.IsAuthenticated]

    def list(self, request, *args, **kwargs):
        """Return categories with the standard API response envelope."""
        queryset = self.get_queryset().annotate(
            format_count=Count('formats', filter=Q(formats__is_deleted=False))
        )
        serializer = self.get_serializer(queryset, many=True)
        return Response({'success': True, 'data': serializer.data})

    def create(self, request, *args, **kwargs):
        """Create a category and wrap the 201 response payload."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return self._success_response(serializer.data, status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        """Update a category and keep the response shape consistent."""
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return self._success_response(serializer.data)

    def _success_response(self, data, response_status=status.HTTP_200_OK):
        """Build the success envelope shared by category writes."""
        return Response({'success': True, 'data': data}, status=response_status)


class DocumentFormatViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_class = DocumentFormatFilter

    def get_queryset(self):
        return DocumentFormat.objects.select_related(
            'category', 'created_by'
        ).annotate(
            _total_generated=Count('generated_documents')
        ).order_by('-created_at')

    def get_serializer_class(self):
        if self.action == 'list':
            return DocumentFormatListSerializer
        return DocumentFormatDetailSerializer

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return Response({'success': True, 'data': serializer.data})

    def create(self, request, *args, **kwargs):
        """Create a category and wrap the 201 response payload."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        return Response(
            {'success': True, 'data': serializer.data, 'message': 'Format created successfully'},
            status=status.HTTP_201_CREATED
        )

    def update(self, request, *args, **kwargs):
        """Update a category and keep the response shape consistent."""
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({'success': True, 'data': serializer.data})

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.total_generated > 0:
            return Response(
                {'success': False, 'error': {'message': 'Cannot delete format with generated documents'}},
                status=status.HTTP_400_BAD_REQUEST
            )
        instance.delete()
        return Response({'success': True, 'message': 'Format deleted'})

    @extend_schema(request=GenerateDocumentSerializer)
    @action(
        detail=True,
        methods=['post'],
        url_path='generate',
        throttle_classes=[GenerateRateThrottle]
    )
    def generate(self, request, pk=None):
        """Generate a document number using this format"""
        fmt = self.get_object()

        if not fmt.is_active:
            return Response(
                {'success': False, 'error': {'message': f'Format is {fmt.status}, not active'}},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = GenerateDocumentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            count = serializer.validated_data.get('count', 1)

            if count == 1:
                doc = fmt.get_generator().generate(
                    context_data=serializer.validated_data.get('context_data'),
                    user=request.user,
                    metadata=serializer.validated_data.get('metadata'),
                )
                return Response({
                    'success': True,
                    'data': GeneratedDocumentSerializer(doc).data
                })
            else:
                docs = fmt.get_generator().bulk_generate(
                    count=count,
                    context_data=serializer.validated_data.get('context_data'),
                    user=request.user,
                )
                return Response({
                    'success': True,
                    'data': GeneratedDocumentSerializer(docs, many=True).data,
                    'count': len(docs)
                })

        except Exception as e:
            logger.error(f"Generation failed: {e}", exc_info=True)
            return Response(
                {'success': False, 'error': {'message': str(e)}},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY
            )

    @action(detail=True, methods=['get'], url_path='preview')
    def preview(self, request, pk=None):
        """Get format preview without generating"""
        fmt = self.get_object()
        context_data = request.query_params.dict()

        try:
            preview = fmt.generate_preview(context_data=context_data)
            return Response({'success': True, 'data': {'preview': preview}})
        except Exception as e:
            return Response(
                {'success': False, 'error': {'message': str(e)}},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY
            )

    @action(detail=True, methods=['post'], url_path='activate')
    def activate(self, request, pk=None):
        fmt = self.get_object()
        fmt.status = 'active'
        fmt.save(update_fields=['status'])
        return Response({'success': True, 'message': 'Format activated'})

    @action(detail=True, methods=['post'], url_path='deactivate')
    def deactivate(self, request, pk=None):
        fmt = self.get_object()
        fmt.status = 'deprecated'
        fmt.save(update_fields=['status'])
        return Response({'success': True, 'message': 'Format deactivated'})

    @action(detail=True, methods=['post'], url_path='duplicate')
    def duplicate(self, request, pk=None):
        fmt = self.get_object()
        new_fmt = DocumentFormat.objects.create(
            code=f"{fmt.code}_COPY",
            name=f"{fmt.name} (Kopya)",
            description=fmt.description,
            segments_config=fmt.segments_config,
            sequence_reset_period=fmt.sequence_reset_period,
            sequence_start=fmt.sequence_start,
            sequence_step=fmt.sequence_step,
            validation_regex=fmt.validation_regex,
            category=fmt.category,
            tags=fmt.tags,
            created_by=request.user,
            status='draft',
        )
        serializer = DocumentFormatDetailSerializer(new_fmt, context={'request': request})
        return Response(
            {'success': True, 'data': serializer.data},
            status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=['get'], url_path='versions')
    def versions(self, request, pk=None):
        fmt = self.get_object()
        versions = fmt.versions.select_related('changed_by').all()
        return Response({
            'success': True,
            'data': [
                {
                    'id': str(v.id) if hasattr(v, 'id') else v.version_number,
                    'version_number': v.version_number,
                    'segments_config': v.segments_config,
                    'changed_by': v.changed_by.username if v.changed_by else None,
                    'change_note': v.change_note,
                    'created_at': v.created_at,
                }
                for v in versions
            ]
        })

    @action(detail=False, methods=['get'], url_path='segment-types')
    def segment_types(self, request):
        """List all available segment types"""
        from .engine.segments import get_available_segments
        return Response({'success': True, 'data': get_available_segments()})

    @action(detail=False, methods=['get'], url_path='stats')
    def stats(self, request):
        from django.utils import timezone
        from datetime import timedelta
        from apps.documents.models import GeneratedDocument

        today = timezone.now().date()
        month_start = today.replace(day=1)

        data = {
            'total_formats': DocumentFormat.objects.count(),
            'active_formats': DocumentFormat.objects.filter(status='active').count(),
            'total_documents': GeneratedDocument.objects.count(),
            'today_documents': GeneratedDocument.objects.filter(
                generated_at__date=today
            ).count(),
            'month_documents': GeneratedDocument.objects.filter(
                generated_at__date__gte=month_start
            ).count(),
        }

        return Response({'success': True, 'data': data})