from django.apps import AppConfig


class CoreConfig(AppConfig):
    """Application configuration for shared core utilities."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.core'
