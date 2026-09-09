from django.conf import settings
from django.contrib.auth import get_user_model
from django.middleware.csrf import CsrfViewMiddleware, get_token
from django.urls import path
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer, TokenRefreshSerializer
from drf_spectacular.utils import extend_schema, extend_schema_field

from apps.core.throttles import TokenObtainRateThrottle, TokenRefreshRateThrottle


class CurrentUserSerializer(serializers.ModelSerializer):
    """Serialize authenticated user profile fields exposed to the frontend."""

    username = serializers.SerializerMethodField()

    class Meta:
        model = get_user_model()
        fields = ['id', 'username', 'email', 'first_name', 'last_name']
        read_only_fields = ['id', 'username']
        extra_kwargs = {
            'email': {'required': True, 'allow_blank': False},
            'first_name': {'required': False, 'allow_blank': True},
            'last_name': {'required': False, 'allow_blank': True},
        }

    @extend_schema_field(serializers.CharField())
    def get_username(self, user):
        """Return the configured username identifier for the user model."""
        return user.get_username()

    def validate_email(self, value):
        """Normalize the email address before saving it."""
        normalized_email = value.strip().lower()
        if not normalized_email:
            raise serializers.ValidationError('Email address is required.')
        return normalized_email


class AuthSuccessSerializer(serializers.Serializer):
    """Document cookie-auth endpoint responses without exposing JWT values."""

    success = serializers.BooleanField()


def cookie_settings(max_age):
    """Return shared secure cookie attributes for auth token cookies."""
    return {
        'httponly': True,
        'secure': settings.AUTH_COOKIE_SECURE,
        'samesite': settings.AUTH_COOKIE_SAMESITE,
        'path': settings.AUTH_COOKIE_PATH,
        'max_age': max_age,
    }


def set_auth_cookies(response, access_token, refresh_token=None):
    """Attach HttpOnly JWT cookies to the API response."""
    response.set_cookie(
        settings.AUTH_ACCESS_COOKIE_NAME,
        access_token,
        **cookie_settings(settings.AUTH_ACCESS_COOKIE_MAX_AGE),
    )
    if refresh_token:
        response.set_cookie(
            settings.AUTH_REFRESH_COOKIE_NAME,
            refresh_token,
            **cookie_settings(settings.AUTH_REFRESH_COOKIE_MAX_AGE),
        )


def clear_auth_cookies(response):
    """Remove HttpOnly JWT cookies from the browser."""
    for cookie_name in settings.AUTH_COOKIE_NAMES:
        response.delete_cookie(cookie_name, path=settings.AUTH_COOKIE_PATH)


def enforce_csrf(request):
    """Validate the double-submit CSRF header for auth endpoints."""
    reason = CsrfViewMiddleware(lambda _: None).process_view(request, None, (), {})
    if reason:
        raise serializers.ValidationError('CSRF token missing or incorrect.')


class CsrfTokenView(APIView):
    """Issue a CSRF cookie before credential-bearing auth requests."""

    authentication_classes = []
    permission_classes = [AllowAny]

    @method_decorator(ensure_csrf_cookie)
    @extend_schema(responses=AuthSuccessSerializer)
    def get(self, request):
        """Return a success envelope while Django sets the CSRF cookie."""
        get_token(request)
        return Response({'success': True})


class CookieTokenObtainPairView(APIView):
    """Authenticate credentials and store JWTs in HttpOnly cookies."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [TokenObtainRateThrottle]

    @extend_schema(request=TokenObtainPairSerializer, responses=AuthSuccessSerializer)
    def post(self, request):
        """Validate credentials and set access and refresh cookies."""
        enforce_csrf(request)
        serializer = TokenObtainPairSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        response = Response({'success': True}, status=status.HTTP_200_OK)
        set_auth_cookies(response, serializer.validated_data['access'], serializer.validated_data['refresh'])
        return response


class CookieTokenRefreshView(APIView):
    """Rotate the access cookie by validating the HttpOnly refresh cookie."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [TokenRefreshRateThrottle]

    @extend_schema(request=None, responses=AuthSuccessSerializer)
    def post(self, request):
        """Refresh the access token without exposing tokens to JavaScript."""
        enforce_csrf(request)
        refresh_token = request.COOKIES.get(settings.AUTH_REFRESH_COOKIE_NAME)
        if not refresh_token:
            raise InvalidToken('Refresh token cookie is missing.')
        serializer = TokenRefreshSerializer(data={'refresh': refresh_token})
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as error:
            raise InvalidToken(error.args[0]) from error
        response = Response({'success': True}, status=status.HTTP_200_OK)
        set_auth_cookies(response, serializer.validated_data['access'])
        return response


class LogoutView(APIView):
    """Clear authentication cookies for the current browser session."""

    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(request=None, responses=AuthSuccessSerializer)
    def post(self, request):
        """Logout the user by deleting access and refresh cookies."""
        enforce_csrf(request)
        response = Response({'success': True})
        clear_auth_cookies(response)
        return response


class CurrentUserView(APIView):
    """Return and update the authenticated user's public profile."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses=CurrentUserSerializer)
    def get(self, request):
        """Return identity fields needed by the frontend."""
        return Response({'success': True, 'data': CurrentUserSerializer(request.user).data})

    @extend_schema(request=CurrentUserSerializer, responses=CurrentUserSerializer)
    def patch(self, request):
        """Update editable profile fields without allowing username changes."""
        serializer = CurrentUserSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({'success': True, 'data': serializer.data})


urlpatterns = [
    path('csrf/', CsrfTokenView.as_view(), name='csrf_token'),
    path('token/', CookieTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', CookieTokenRefreshView.as_view(), name='token_refresh'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('me/', CurrentUserView.as_view(), name='current_user'),
]
