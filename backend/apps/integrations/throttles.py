from rest_framework.throttling import SimpleRateThrottle


class ApiCredentialRateThrottle(SimpleRateThrottle):
    """Apply general private API limits independently to each credential."""

    scope = 'private_api'

    def get_cache_key(self, request, view):
        if not request.auth:
            return None
        return self.cache_format % {'scope': self.scope, 'ident': request.auth.pk}


class ApiCredentialGenerateRateThrottle(ApiCredentialRateThrottle):
    """Apply a separate limit to number issuance calls."""

    scope = 'private_generate'
