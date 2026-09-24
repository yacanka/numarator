"""Serve SPA navigation without swallowing API, admin, or missing asset routes."""

from django.conf import settings
from django.http import HttpResponse
from django.urls import re_path
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from .urls import urlpatterns as api_patterns


@require_safe
@never_cache
def frontend(request):
    return HttpResponse((settings.FRONTEND_DIST / 'index.html').read_bytes(), content_type='text/html')


# Explicitly mirror the browser router. Unknown/API/media paths keep real 404s.
urlpatterns = [*api_patterns, re_path(
    r'^(?:login|formats(?:/new|/[0-9a-fA-F-]{36}/edit)?|documents|settings(?:/api-keys)?)?/?$',
    frontend,
)]
