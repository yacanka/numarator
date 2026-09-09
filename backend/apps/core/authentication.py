from django.conf import settings
from django.middleware.csrf import CsrfViewMiddleware
from rest_framework import exceptions
from rest_framework_simplejwt.authentication import JWTAuthentication


class CookieJWTAuthentication(JWTAuthentication):
    """Authenticate users with an HttpOnly access-token cookie and CSRF checks."""

    def authenticate(self, request):
        """Return a validated user/token pair from the access cookie."""
        raw_token = request.COOKIES.get(settings.AUTH_ACCESS_COOKIE_NAME)
        if raw_token is None:
            return None
        self.enforce_csrf(request)
        validated_token = self.get_validated_token(raw_token)
        return self.get_user(validated_token), validated_token

    def enforce_csrf(self, request):
        """Reject unsafe cookie-authenticated requests without a valid CSRF token."""
        reason = CsrfViewMiddleware(lambda _: None).process_view(request, None, (), {})
        if reason:
            raise exceptions.PermissionDenied('CSRF token missing or incorrect.')
