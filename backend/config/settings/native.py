"""Single-process native HTTPS profile; Docker's production.py is independent."""

import ipaddress
import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .native_environment import data_dir
from .secret_key import validate_secret_key

DEBUG = False
SECRET_KEY = validate_secret_key(SECRET_KEY)  # noqa: F405
HOST = os.environ.get('NUMARATOR_HOST', '')
try:
    address = ipaddress.IPv4Address(HOST)
    PORT = int(os.environ.get('NUMARATOR_PORT', '443'))
    if address.is_unspecified or address.is_multicast or address.is_reserved or not 1 <= PORT <= 65535:
        raise ValueError
except ValueError as error:
    raise ImproperlyConfigured('Native production requires a unicast IPv4 host and valid port') from error

ALLOWED_HOSTS = [HOST]
CSRF_TRUSTED_ORIGINS = [f'https://{HOST}' + (f':{PORT}' if PORT != 443 else '')]
CORS_ALLOWED_ORIGINS = []
CORS_ALLOW_ALL_ORIGINS = False
AUTH_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
# Production frontend defaults to csrftoken; preserve that contract.
CSRF_COOKIE_NAME = 'csrftoken'
SESSION_COOKIE_NAME = 'dn_sessionid'
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = None
USE_X_FORWARDED_HOST = False
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'

DATABASES = {'default': {
    'ENGINE': 'django.db.backends.sqlite3',
    'NAME': data_dir / 'numarator.sqlite3',
    'OPTIONS': {'timeout': 30},
    'CONN_MAX_AGE': 0,
}}
CACHES = {'default': {
    'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    'LOCATION': 'numarator-native',
}}
# There are no application Celery tasks today; never silently enqueue to a
# nonexistent broker if a task is added later.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
STATIC_ROOT = data_dir / 'staticfiles'
MEDIA_ROOT = data_dir / 'media'
FRONTEND_DIST = BASE_DIR.parent / 'frontend' / 'dist'  # noqa: F405
WHITENOISE_ROOT = FRONTEND_DIST
WHITENOISE_AUTOREFRESH = False
WHITENOISE_USE_FINDERS = False
WHITENOISE_MAX_AGE = 0
MIDDLEWARE = [*MIDDLEWARE]  # noqa: F405
MIDDLEWARE[1:1] = [
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'config.native_serialization.SerializedRequestsMiddleware',
]
ROOT_URLCONF = 'config.native_urls'
