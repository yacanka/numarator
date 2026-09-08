"""Tests for project-level Django entry points."""
from django.core.handlers.wsgi import WSGIHandler
from django.test import SimpleTestCase
from config.settings import development

from config.wsgi import application


class WsgiApplicationTests(SimpleTestCase):
    """Validate the configured WSGI application object."""

    def test_wsgi_application_is_exported(self):
        """The WSGI module exposes Django's callable application object."""
        self.assertIsInstance(application, WSGIHandler)


class LocalCookieSettingsTests(SimpleTestCase):
    def test_development_cookies_are_isolated_from_other_local_django_apps(self):
        self.assertEqual(development.CSRF_COOKIE_NAME, 'dn_csrftoken')
        self.assertEqual(development.SESSION_COOKIE_NAME, 'dn_sessionid')
