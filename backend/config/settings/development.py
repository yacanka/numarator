from .base import *  # noqa: F403
from .secret_key import development_secret_key

SECRET_KEY = development_secret_key(SECRET_KEY, BASE_DIR)  # noqa: F405

DEBUG = True
AUTH_COOKIE_SECURE = config('AUTH_COOKIE_SECURE', default=False, cast=bool)  # noqa: F405
CSRF_COOKIE_SECURE = AUTH_COOKIE_SECURE
# Cookies are host-scoped, so isolate simultaneous local Django applications.
CSRF_COOKIE_NAME = 'dn_csrftoken'
SESSION_COOKIE_NAME = 'dn_sessionid'
ALLOWED_HOSTS = ['localhost', '127.0.0.1', 'testserver']
DEV_FRONTEND_PORT = config('DEV_FRONTEND_PORT', default=5173, cast=int)  # noqa: F405
CORS_ALLOWED_ORIGINS = [
    f'http://localhost:{DEV_FRONTEND_PORT}',
    f'http://127.0.0.1:{DEV_FRONTEND_PORT}',
]
CSRF_TRUSTED_ORIGINS = CORS_ALLOWED_ORIGINS
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
