# apps/core/throttles.py
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle


class GenerateRateThrottle(UserRateThrottle):
    """Limit high-cost document number generation per authenticated user."""

    scope = 'generate'


class TokenObtainRateThrottle(AnonRateThrottle):
    """Throttle password-based token obtain attempts separately from refreshes."""

    scope = 'token_obtain'


class TokenRefreshRateThrottle(AnonRateThrottle):
    """Throttle token refresh attempts without consuming the login quota."""

    scope = 'token_refresh'
