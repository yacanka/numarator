from .base import *  # noqa: F403
from .secret_key import validate_secret_key

DEBUG = False
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'

SECRET_KEY = validate_secret_key(SECRET_KEY)  # noqa: F405

DATABASES['default'].update({  # noqa: F405
    'ENGINE': 'django.db.backends.postgresql',
    'HOST': config('DB_HOST', default='db'),  # noqa: F405
    'PORT': config('DB_PORT', default='5432'),  # noqa: F405
    'CONN_MAX_AGE': config('DB_CONN_MAX_AGE', default=60, cast=int),  # noqa: F405
})
CACHES['default'] = {  # noqa: F405
    'BACKEND': 'django_redis.cache.RedisCache',
    'LOCATION': config('REDIS_URL', default='redis://redis:6379/0'),  # noqa: F405
    'OPTIONS': {'CLIENT_CLASS': 'django_redis.client.DefaultClient'},
}
CELERY_BROKER_URL = config('REDIS_URL', default='redis://redis:6379/0')  # noqa: F405
