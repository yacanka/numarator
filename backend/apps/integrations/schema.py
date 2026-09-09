from drf_spectacular.extensions import OpenApiAuthenticationExtension
from django.conf import settings


class ApiKeyAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = 'apps.integrations.authentication.ApiKeyAuthentication'
    name = 'ExternalApplicationApiKey'

    def get_security_definition(self, auto_schema):
        return {
            'type': 'apiKey',
            'in': 'header',
            'name': 'X-API-Key',
            'description': 'Entegrasyon ayarlarından bir kez gösterilen dnk_... API anahtarı.',
        }


class CookieJwtAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = 'apps.core.authentication.CookieJWTAuthentication'
    name = 'BrowserAccessCookie'

    def get_security_definition(self, auto_schema):
        return {
            'type': 'apiKey',
            'in': 'cookie',
            'name': settings.AUTH_ACCESS_COOKIE_NAME,
            'description': 'Tarayıcı oturumu tarafından yönetilen HttpOnly JWT cookie.',
        }
