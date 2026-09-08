from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.core.auth_urls import CookieTokenObtainPairView, CookieTokenRefreshView


class CurrentUserApiTests(TestCase):
    """Tests for authenticated profile retrieval and self-service updates."""

    def setUp(self):
        """Create an authenticated client for profile endpoint tests."""
        self.user = get_user_model().objects.create_user(
            username='operator',
            email='old@example.com',
            password='secret',
            first_name='Old',
            last_name='Name',
        )
        self.client = APIClient(enforce_csrf_checks=True)
        self.client.force_authenticate(user=self.user)

    def test_patch_updates_profile_without_username(self):
        """Editable profile fields update while username remains immutable."""
        response = self.client.patch('/api/v1/auth/me/', {
            'username': 'changed',
            'email': ' NEW@Example.COM ',
            'first_name': 'New',
            'last_name': 'Person',
        }, format='json')

        self.user.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.user.username, 'operator')
        self.assertEqual(self.user.email, 'new@example.com')
        self.assertEqual(response.data['data']['username'], 'operator')

    def test_patch_rejects_blank_email(self):
        """Blank email values are rejected before they reach the database."""
        response = self.client.patch('/api/v1/auth/me/', {'email': ' '}, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertIn('email', response.data['error']['details'])


class CookieAuthenticationApiTests(TestCase):
    """Tests for HttpOnly-cookie and CSRF-backed authentication."""

    def setUp(self):
        """Create a user and a client that enforces CSRF checks."""
        get_user_model().objects.create_user(username='operator', password='secret')
        self.client = APIClient(enforce_csrf_checks=True)

    def test_login_sets_httponly_auth_cookies_with_csrf(self):
        """Successful login stores tokens in HttpOnly cookies only."""
        csrf_response = self.client.get('/api/v1/auth/csrf/')
        csrf_token = csrf_response.cookies[settings.CSRF_COOKIE_NAME].value
        response = self.client.post(
            '/api/v1/auth/token/',
            {'username': 'operator', 'password': 'secret'},
            format='json',
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('access', response.data)
        self.assertTrue(response.cookies[settings.AUTH_ACCESS_COOKIE_NAME]['httponly'])
        self.assertTrue(response.cookies[settings.AUTH_REFRESH_COOKIE_NAME]['httponly'])

    def test_login_without_csrf_is_rejected(self):
        """Credential submission requires a valid CSRF token."""
        response = self.client.post(
            '/api/v1/auth/token/',
            {'username': 'operator', 'password': 'secret'},
            format='json',
        )

        self.assertEqual(response.status_code, 400)

    def test_refresh_uses_refresh_cookie_and_does_not_return_token(self):
        """Refresh endpoint rotates access cookie without exposing JWTs."""
        csrf_response = self.client.get('/api/v1/auth/csrf/')
        csrf_token = csrf_response.cookies[settings.CSRF_COOKIE_NAME].value
        self.client.post(
            '/api/v1/auth/token/',
            {'username': 'operator', 'password': 'secret'},
            format='json',
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        response = self.client.post('/api/v1/auth/token/refresh/', HTTP_X_CSRFTOKEN=csrf_token)

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('access', response.data)
        self.assertIn(settings.AUTH_ACCESS_COOKIE_NAME, response.cookies)


class AuthenticationThrottleScopeTests(TestCase):
    """Tests for independent authentication endpoint throttling scopes."""

    def test_token_views_use_isolated_throttle_scopes(self):
        """Login and refresh attempts do not consume the same throttle bucket."""
        self.assertEqual(CookieTokenObtainPairView.throttle_classes[0].scope, 'token_obtain')
        self.assertEqual(CookieTokenRefreshView.throttle_classes[0].scope, 'token_refresh')
