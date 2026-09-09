import logging
import re

from django.db import transaction
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from apps.documents.models import GeneratedDocument
from apps.formats.models import DocumentFormat

from .authentication import ApiKeyAuthentication
from .exceptions import Conflict, GenerationFailed
from .filters import PrivateGeneratedDocumentFilter
from .permissions import HasApiScope
from .serializers import (
    PrivateFormatListResponseSerializer,
    PrivateFormatPreviewSerializer,
    PrivateFormatPreviewResponseSerializer,
    PrivateFormatResponseSerializer,
    PrivateFormatSerializer,
    PrivateGeneratedDocumentListResponseSerializer,
    PrivateGeneratedDocumentResponseSerializer,
    PrivateGeneratedDocumentSerializer,
    PrivateNumberCreateSerializer,
    PrivateNumberStatusSerializer,
    PrivateNumberValidationResponseSerializer,
    PrivateNumberValidationSerializer,
    validate_required_format_context,
)
from .services import generate_idempotently
from .throttles import ApiCredentialGenerateRateThrottle, ApiCredentialRateThrottle

logger = logging.getLogger(__name__)
IDEMPOTENCY_KEY_PATTERN = re.compile(r'^[A-Za-z0-9._:-]{1,128}$')


class PrivateApiViewSet(viewsets.GenericViewSet):
    """Shared authentication, authorization and format restriction behavior."""

    authentication_classes = [ApiKeyAuthentication]
    permission_classes = [HasApiScope]
    throttle_classes = [ApiCredentialRateThrottle]
    scope_by_action = {}

    def get_required_scope(self):
        return self.scope_by_action.get(self.action)

    def allowed_format_ids(self):
        if not hasattr(self, '_allowed_format_ids'):
            self._allowed_format_ids = list(
                self.request.auth.allowed_formats.values_list('pk', flat=True)
            )
        return self._allowed_format_ids

    def restrict_formats(self, queryset, field_name='pk'):
        allowed_ids = self.allowed_format_ids()
        if not allowed_ids:
            return queryset
        return queryset.filter(**{f'{field_name}__in': allowed_ids})


@extend_schema_view(
    list=extend_schema(
        description='API anahtarının erişebildiği aktif formatları listeler.',
        responses=PrivateFormatListResponseSerializer(many=False),
    ),
    retrieve=extend_schema(
        description='Bir aktif formatı koduyla döndürür.',
        responses=PrivateFormatResponseSerializer,
    ),
)
class PrivateFormatViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    PrivateApiViewSet,
):
    serializer_class = PrivateFormatSerializer
    queryset = DocumentFormat.objects.none()
    filter_backends = []
    lookup_field = 'code'
    scope_by_action = {'list': 'formats:read', 'retrieve': 'formats:read', 'preview': 'formats:read'}

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return self.queryset
        queryset = DocumentFormat.objects.filter(status='active').order_by('code')
        return self.restrict_formats(queryset)

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)
        if page is not None:
            return self.get_paginated_response(self.get_serializer(page, many=True).data)
        return Response({'success': True, 'data': self.get_serializer(queryset, many=True).data})

    def retrieve(self, request, *args, **kwargs):
        return Response({'success': True, 'data': self.get_serializer(self.get_object()).data})

    @extend_schema(
        request=PrivateFormatPreviewSerializer,
        responses=PrivateFormatPreviewResponseSerializer,
    )
    @action(detail=True, methods=['post'])
    def preview(self, request, code=None):
        document_format = self.get_object()
        serializer = PrivateFormatPreviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validate_required_format_context(
            document_format,
            serializer.validated_data['context_data'],
        )
        try:
            preview = document_format.generate_preview(serializer.validated_data['context_data'])
        except (TypeError, ValueError) as error:
            raise GenerationFailed(str(error)) from error
        return Response({'success': True, 'data': {'preview': preview}})


@extend_schema_view(
    list=extend_schema(
        description='Numara geçmişini mutabakat için filtreleyerek listeler.',
        responses=PrivateGeneratedDocumentListResponseSerializer(many=False),
    ),
    retrieve=extend_schema(
        description='Bir numaranın güncel durumunu kimliğiyle döndürür.',
        responses=PrivateGeneratedDocumentResponseSerializer,
    ),
    create=extend_schema(
        description='Aktif bir formattan idempotent olarak tek numara üretir.',
        request=PrivateNumberCreateSerializer,
        parameters=[
            OpenApiParameter(
                name='Idempotency-Key',
                type=str,
                location=OpenApiParameter.HEADER,
                required=True,
                description=(
                    'Bu iş olayı için kararlı, 1-128 karakterlik tekrar anahtarı. '
                    'Harf, rakam, nokta, alt çizgi, iki nokta ve tire kabul edilir.'
                ),
            ),
        ],
        responses={
            201: PrivateGeneratedDocumentResponseSerializer,
            200: PrivateGeneratedDocumentResponseSerializer,
        },
    ),
)
class PrivateNumberViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    PrivateApiViewSet,
):
    serializer_class = PrivateGeneratedDocumentSerializer
    queryset = GeneratedDocument.objects.none()
    filter_backends = [DjangoFilterBackend]
    filterset_class = PrivateGeneratedDocumentFilter
    scope_by_action = {
        'list': 'numbers:read',
        'retrieve': 'numbers:read',
        'create': 'numbers:generate',
        'validate': 'numbers:read',
        'status': 'numbers:status',
    }

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return self.queryset
        queryset = GeneratedDocument.objects.select_related('format').order_by('-generated_at')
        return self.restrict_formats(queryset, field_name='format_id')

    def get_throttles(self):
        throttle_classes = [ApiCredentialRateThrottle]
        if self.action == 'create':
            throttle_classes.append(ApiCredentialGenerateRateThrottle)
        return [throttle() for throttle in throttle_classes]

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            return self.get_paginated_response(self.get_serializer(page, many=True).data)
        return Response({'success': True, 'data': self.get_serializer(queryset, many=True).data})

    def retrieve(self, request, *args, **kwargs):
        return Response({'success': True, 'data': self.get_serializer(self.get_object()).data})

    def create(self, request, *args, **kwargs):
        idempotency_key = request.headers.get('Idempotency-Key', '').strip()
        if not IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key):
            raise ValidationError({
                'idempotency_key': (
                    'Idempotency-Key is required and must contain 1-128 letters, '
                    'numbers, dots, underscores, colons or hyphens.'
                )
            })

        serializer = PrivateNumberCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data
        try:
            document_format = self.restrict_formats(
                DocumentFormat.objects.filter(status='active')
            ).get(code__iexact=payload['format_code'])
        except DocumentFormat.DoesNotExist as error:
            raise NotFound('Active format not found or not allowed for this API key.') from error
        validate_required_format_context(document_format, payload['context_data'])

        try:
            document, replayed = generate_idempotently(
                credential=request.auth,
                idempotency_key=idempotency_key,
                document_format=document_format,
                payload=payload,
                user=request.user,
            )
        except Conflict:
            raise
        except (TypeError, ValueError, RuntimeError) as error:
            logger.warning('Private API generation failed: %s', error, exc_info=True)
            raise GenerationFailed() from error

        response = Response(
            {'success': True, 'data': self.get_serializer(document).data},
            status=status.HTTP_200_OK if replayed else status.HTTP_201_CREATED,
        )
        if replayed:
            response['Idempotent-Replayed'] = 'true'
        return response

    @extend_schema(
        request=PrivateNumberValidationSerializer,
        responses=PrivateNumberValidationResponseSerializer,
    )
    @action(detail=False, methods=['post'], url_path='validate')
    def validate(self, request):
        serializer = PrivateNumberValidationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        document = self.get_queryset().filter(
            document_number=serializer.validated_data['document_number']
        ).first()
        if document is None:
            return Response({'success': True, 'data': {'exists': False, 'valid': False}})
        return Response({
            'success': True,
            'data': {
                'exists': True,
                'valid': document.is_valid,
                'status': document.status,
                'document': self.get_serializer(document).data,
            },
        })

    @extend_schema(
        request=PrivateNumberStatusSerializer,
        responses=PrivateGeneratedDocumentResponseSerializer,
    )
    @action(detail=True, methods=['patch'], url_path='status')
    def status(self, request, pk=None):
        serializer = PrivateNumberStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            try:
                document = self.get_queryset().select_for_update().get(pk=pk)
            except GeneratedDocument.DoesNotExist as error:
                raise NotFound() from error
            target_status = serializer.validated_data['status']
            if document.status != target_status:
                if document.status != 'active':
                    raise Conflict(
                        f'Number is already {document.status} and cannot become {target_status}.'
                    )
                document.change_status(
                    target_status,
                    reason=serializer.validated_data.get('reason', ''),
                )
        return Response({'success': True, 'data': self.get_serializer(document).data})
