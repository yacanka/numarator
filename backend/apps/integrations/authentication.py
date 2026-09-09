import secrets

from django.utils import timezone
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication

from .models import ApiCredential


class ApiKeyAuthentication(BaseAuthentication):
    """Authenticate private API requests using the X-API-Key header."""

    header_name = 'X-API-Key'

    def authenticate(self, request):
        raw_key = request.headers.get(self.header_name)
        if not raw_key:
            return None

        key_prefix = self._extract_prefix(raw_key)
        if key_prefix is None:
            raise exceptions.AuthenticationFailed('Invalid or inactive API key.')

        try:
            credential = ApiCredential.objects.select_related('owner').get(
                key_prefix=key_prefix
            )
        except ApiCredential.DoesNotExist as error:
            raise exceptions.AuthenticationFailed('Invalid or inactive API key.') from error

        expected_hash = ApiCredential.hash_key(raw_key)
        if not secrets.compare_digest(credential.key_hash, expected_hash):
            raise exceptions.AuthenticationFailed('Invalid or inactive API key.')
        if not credential.is_usable:
            raise exceptions.AuthenticationFailed('Invalid or inactive API key.')

        now = timezone.now()
        ApiCredential.objects.filter(pk=credential.pk).update(last_used_at=now)
        credential.last_used_at = now
        return credential.owner, credential

    def authenticate_header(self, request):
        return self.header_name

    @staticmethod
    def _extract_prefix(raw_key):
        parts = raw_key.split('_', 2)
        if len(parts) != 3 or parts[0] != 'dnk' or len(parts[1]) != 12:
            return None
        return f'{parts[0]}_{parts[1]}'
