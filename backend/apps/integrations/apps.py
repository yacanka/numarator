from django.apps import AppConfig


class IntegrationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.integrations'

    def ready(self):
        """Register the API-key OpenAPI security scheme."""
        from . import schema  # noqa: F401
