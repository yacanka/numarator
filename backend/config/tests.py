"""Tests for project-level Django entry points."""
import os
import secrets
import tempfile
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from django.core.handlers.wsgi import WSGIHandler
from django.test import SimpleTestCase
from rest_framework_simplejwt.state import token_backend

from config.settings import development
from config.settings.secret_key import development_secret_key, validate_secret_key

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


class SecretKeySettingsTests(SimpleTestCase):
    def test_missing_and_short_keys_are_rejected_without_disclosing_them(self):
        for size in (0, 25, 31):
            key = secrets.token_hex(16)[:size]
            with self.subTest(size=size):
                with self.assertRaises(ImproperlyConfigured) as error:
                    validate_secret_key(key)
                if key:
                    self.assertNotIn(key, str(error.exception))

    def test_minimum_length_key_is_preserved(self):
        key = secrets.token_hex(16)
        self.assertEqual(validate_secret_key(key), key)

    def test_development_key_is_persistent_and_private(self):
        with tempfile.TemporaryDirectory() as temporary:
            base_dir = Path(temporary)
            key = development_secret_key('', base_dir)
            self.assertGreaterEqual(len(key.encode('utf-8')), 32)
            self.assertEqual(development_secret_key('', base_dir), key)
            if os.name == 'posix':
                self.assertEqual((base_dir / '.dev-secret-key').stat().st_mode & 0o777, 0o600)

    def test_concurrent_development_starts_share_one_key(self):
        with tempfile.TemporaryDirectory() as temporary:
            with ThreadPoolExecutor(max_workers=8) as executor:
                keys = list(executor.map(
                    lambda _: development_secret_key('', Path(temporary)), range(8),
                ))
            self.assertEqual(len(set(keys)), 1)

    def test_explicit_development_key_is_preserved_without_creating_a_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            base_dir = Path(temporary)
            key = secrets.token_urlsafe(48)
            self.assertEqual(development_secret_key(key, base_dir), key)
            self.assertEqual(list(base_dir.iterdir()), [])

    def test_invalid_explicit_key_is_not_silently_replaced(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ImproperlyConfigured):
                development_secret_key(secrets.token_hex(8), Path(temporary))
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_invalid_persisted_key_is_not_silently_rotated(self):
        with tempfile.TemporaryDirectory() as temporary:
            base_dir = Path(temporary)
            key = secrets.token_hex(8)
            (base_dir / '.dev-secret-key').write_text(key)
            with self.assertRaises(ImproperlyConfigured):
                development_secret_key('', base_dir)
            self.assertEqual((base_dir / '.dev-secret-key').read_text(), key)

    def test_configured_jwt_backend_round_trip_has_no_key_length_warning(self):
        with warnings.catch_warnings():
            warnings.simplefilter('error')
            token = token_backend.encode({'purpose': 'signing-key-regression'})
            self.assertEqual(token_backend.decode(token)['purpose'], 'signing-key-regression')
