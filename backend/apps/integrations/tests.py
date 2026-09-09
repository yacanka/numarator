from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from drf_spectacular.generators import SchemaGenerator

from apps.documents.models import GeneratedDocument
from apps.formats.models import DocumentFormat

from .models import API_SCOPES, ApiCredential, IdempotencyRecord


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class ApiCredentialManagementTests(TestCase):
    """Cover one-time key disclosure and owner-isolated management."""

    def setUp(self):
        self.user = get_user_model().objects.create_user('owner', password='secret')
        self.other_user = get_user_model().objects.create_user('other', password='secret')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_create_returns_plaintext_key_once_and_stores_only_hash(self):
        response = self.client.post(
            '/api/v1/integrations/api-keys/',
            {
                'name': 'ERP',
                'scopes': list(API_SCOPES),
                'allowed_formats': [],
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        raw_key = response.data['data']['api_key']
        credential = ApiCredential.objects.get(owner=self.user)
        self.assertTrue(raw_key.startswith(f'{credential.key_prefix}_'))
        self.assertNotEqual(credential.key_hash, raw_key)
        self.assertNotIn('api_key', self.client.get(
            f'/api/v1/integrations/api-keys/{credential.id}/'
        ).data['data'])

    def test_revoke_cannot_target_another_users_key(self):
        credential, _ = ApiCredential.issue(owner=self.other_user, name='Other ERP')

        response = self.client.post(
            f'/api/v1/integrations/api-keys/{credential.id}/revoke/'
        )

        self.assertEqual(response.status_code, 404)
        credential.refresh_from_db()
        self.assertIsNone(credential.revoked_at)

    def test_create_rejects_past_expiration(self):
        response = self.client.post(
            '/api/v1/integrations/api-keys/',
            {
                'name': 'Expired ERP',
                'scopes': list(API_SCOPES),
                'allowed_formats': [],
                'expires_at': (timezone.now() - timedelta(minutes=1)).isoformat(),
            },
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('expires_at', response.data['error']['details'])

    def test_create_requires_explicit_scopes_and_format_access(self):
        response = self.client.post(
            '/api/v1/integrations/api-keys/',
            {'name': 'Implicitly privileged ERP'},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('scopes', response.data['error']['details'])
        self.assertIn('allowed_formats', response.data['error']['details'])


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class PrivateApiTests(TestCase):
    """Exercise authentication, authorization and critical number workflows."""

    def setUp(self):
        self.user = get_user_model().objects.create_user('integration-owner')
        self.document_format = DocumentFormat.objects.create(
            code='ORDER',
            name='Order',
            status='active',
            segments_config=[
                {'type': 'static', 'order': 1, 'config': {'value': 'ORD-'}},
                {'type': 'context', 'order': 2, 'config': {'key': 'branch'}},
                {'type': 'separator', 'order': 3, 'config': {'value': '-'}},
                {'type': 'sequence', 'order': 4, 'config': {'padding': 4}},
            ],
            created_by=self.user,
        )
        self.other_format = DocumentFormat.objects.create(
            code='INVOICE',
            name='Invoice',
            status='active',
            segments_config=[
                {'type': 'static', 'order': 1, 'config': {'value': 'INV-'}},
                {'type': 'sequence', 'order': 2, 'config': {'padding': 4}},
            ],
            created_by=self.user,
        )
        self.credential, self.raw_key = ApiCredential.issue(
            owner=self.user,
            name='ERP',
            scopes=list(API_SCOPES),
        )
        self.client = APIClient()

    @property
    def auth_headers(self):
        return {'HTTP_X_API_KEY': self.raw_key}

    def generate(self, idempotency_key='order-42', **payload_overrides):
        payload = {
            'format_code': 'ORDER',
            'context_data': {'branch': 'IST'},
            'metadata': {'customer_id': 42},
            'external_reference': 'erp-order-42',
        }
        payload.update(payload_overrides)
        return self.client.post(
            '/api/private/v1/numbers/',
            payload,
            format='json',
            HTTP_X_API_KEY=self.raw_key,
            HTTP_IDEMPOTENCY_KEY=idempotency_key,
        )

    def test_private_api_rejects_missing_invalid_and_revoked_keys(self):
        missing_response = self.client.get('/api/private/v1/formats/')
        invalid_response = self.client.get(
            '/api/private/v1/formats/',
            HTTP_X_API_KEY=f'{self.credential.key_prefix}_invalid',
        )
        self.credential.revoke()
        revoked_response = self.client.get(
            '/api/private/v1/formats/',
            **self.auth_headers,
        )

        self.assertEqual(missing_response.status_code, 401)
        self.assertEqual(invalid_response.status_code, 401)
        self.assertEqual(revoked_response.status_code, 401)

    def test_generate_is_idempotent_and_records_integration_audit_fields(self):
        first_response = self.generate()
        replay_response = self.generate()

        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(replay_response.status_code, 200)
        self.assertEqual(replay_response['Idempotent-Replayed'], 'true')
        self.assertEqual(
            first_response.data['data']['document_number'],
            replay_response.data['data']['document_number'],
        )
        self.assertEqual(GeneratedDocument.objects.count(), 1)
        self.assertEqual(IdempotencyRecord.objects.count(), 1)
        document = GeneratedDocument.objects.get()
        self.assertEqual(document.source_credential, self.credential)
        self.assertEqual(document.external_reference, 'erp-order-42')
        self.assertEqual(document.generated_by, self.user)

    def test_reusing_idempotency_key_with_different_payload_returns_conflict(self):
        self.generate()

        response = self.generate(context_data={'branch': 'ANK'})

        self.assertEqual(response.status_code, 409)
        self.assertEqual(GeneratedDocument.objects.count(), 1)

    def test_generate_requires_well_formed_idempotency_key(self):
        response = self.client.post(
            '/api/private/v1/numbers/',
            {'format_code': 'ORDER'},
            format='json',
            **self.auth_headers,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('idempotency_key', response.data['error']['details'])

    def test_generate_requires_context_declared_by_format(self):
        response = self.generate(context_data={})

        self.assertEqual(response.status_code, 400)
        self.assertIn('branch', response.data['error']['details']['context_data'])
        self.assertFalse(GeneratedDocument.objects.exists())

    def test_format_contract_and_preview_do_not_consume_a_number(self):
        detail_response = self.client.get(
            '/api/private/v1/formats/ORDER/',
            **self.auth_headers,
        )
        preview_response = self.client.post(
            '/api/private/v1/formats/ORDER/preview/',
            {'context_data': {'branch': 'IST'}},
            format='json',
            **self.auth_headers,
        )

        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(
            detail_response.data['data']['required_context'][0]['key'],
            'branch',
        )
        self.assertEqual(preview_response.status_code, 200)
        self.assertIn('IST', preview_response.data['data']['preview'])
        self.assertFalse(GeneratedDocument.objects.exists())

    def test_scope_blocks_generation(self):
        self.credential.scopes = ['formats:read']
        self.credential.save(update_fields=['scopes'])

        response = self.generate()

        self.assertEqual(response.status_code, 403)
        self.assertFalse(GeneratedDocument.objects.exists())

    def test_allowed_formats_limit_discovery_and_generation(self):
        self.credential.allowed_formats.set([self.other_format])

        list_response = self.client.get('/api/private/v1/formats/', **self.auth_headers)
        generate_response = self.generate()

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(
            [item['code'] for item in list_response.data['data']],
            ['INVOICE'],
        )
        self.assertEqual(generate_response.status_code, 404)

    def test_validate_handles_separator_characters_and_reports_lifecycle_validity(self):
        document = self.document_format.get_generator().generate(user=self.user)
        document.cancel(reason='Duplicate order')

        response = self.client.post(
            '/api/private/v1/numbers/validate/',
            {'document_number': document.document_number},
            format='json',
            **self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['data']['exists'])
        self.assertFalse(response.data['data']['valid'])
        self.assertEqual(response.data['data']['status'], 'cancelled')

    def test_status_update_is_idempotent_and_rejects_conflicting_terminal_state(self):
        document = self.document_format.get_generator().generate(user=self.user)
        url = f'/api/private/v1/numbers/{document.id}/status/'

        first_response = self.client.patch(
            url,
            {'status': 'used'},
            format='json',
            **self.auth_headers,
        )
        replay_response = self.client.patch(
            url,
            {'status': 'used'},
            format='json',
            **self.auth_headers,
        )
        conflict_response = self.client.patch(
            url,
            {'status': 'cancelled', 'reason': 'Changed mind'},
            format='json',
            **self.auth_headers,
        )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(replay_response.status_code, 200)
        self.assertEqual(conflict_response.status_code, 409)
        document.refresh_from_db()
        self.assertEqual(document.status, 'used')

    def test_number_list_supports_reconciliation_filters(self):
        generated = self.generate()

        response = self.client.get(
            '/api/private/v1/numbers/',
            {'format_code': 'order', 'external_reference': 'erp-order-42'},
            **self.auth_headers,
        )

        self.assertEqual(generated.status_code, 201)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['pagination']['count'], 1)

    def test_expired_key_is_rejected(self):
        self.credential.expires_at = timezone.now() - timedelta(seconds=1)
        self.credential.save(update_fields=['expires_at'])

        response = self.client.get('/api/private/v1/formats/', **self.auth_headers)

        self.assertEqual(response.status_code, 401)


class PrivateApiSchemaTests(TestCase):
    """Keep the machine-readable private API contract discoverable."""

    def test_generation_documents_api_key_and_idempotency_headers(self):
        schema = SchemaGenerator().get_schema(request=None, public=True)
        operation = schema['paths']['/api/private/v1/numbers/']['post']

        self.assertEqual(
            operation['security'],
            [{'ExternalApplicationApiKey': []}],
        )
        self.assertIn(
            'Idempotency-Key',
            [parameter['name'] for parameter in operation['parameters']],
        )
        security_scheme = schema['components']['securitySchemes']['ExternalApplicationApiKey']
        self.assertEqual(security_scheme['name'], 'X-API-Key')
        self.assertEqual(security_scheme['in'], 'header')
