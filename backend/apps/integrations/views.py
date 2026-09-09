from rest_framework import mixins, status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.authentication import CookieJWTAuthentication

from .models import API_SCOPES, ApiCredential
from .serializers import ApiCredentialCreateSerializer, ApiCredentialSerializer


class ApiCredentialViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Manage API keys for the currently authenticated browser user."""

    authentication_classes = [CookieJWTAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]
    queryset = ApiCredential.objects.none()

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return self.queryset
        return ApiCredential.objects.filter(owner=self.request.user).prefetch_related(
            'allowed_formats'
        )

    def get_serializer_class(self):
        if self.action == 'create':
            return ApiCredentialCreateSerializer
        return ApiCredentialSerializer

    def list(self, request, *args, **kwargs):
        serializer = ApiCredentialSerializer(self.get_queryset(), many=True)
        return Response({'success': True, 'data': serializer.data})

    def retrieve(self, request, *args, **kwargs):
        serializer = ApiCredentialSerializer(self.get_object())
        return Response({'success': True, 'data': serializer.data})

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        credential = serializer.save(owner=request.user)
        data = ApiCredentialSerializer(credential).data
        data['api_key'] = serializer.raw_key
        return Response(
            {
                'success': True,
                'data': data,
                'message': 'API key created. Store it now; it will not be shown again.',
            },
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['post'])
    def revoke(self, request, pk=None):
        credential = self.get_object()
        credential.revoke()
        return Response({
            'success': True,
            'data': ApiCredentialSerializer(credential).data,
            'message': 'API key revoked.',
        })

    @action(detail=False, methods=['get'])
    def scopes(self, request):
        return Response({
            'success': True,
            'data': [
                {'code': code, 'description': description}
                for code, description in API_SCOPES.items()
            ],
        })
