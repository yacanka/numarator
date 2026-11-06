from datetime import timedelta
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from drf_spectacular.generators import SchemaGenerator

from apps.documents.models import GeneratedDocument
from apps.formats.models import DocumentFormat
from apps.formats.engine.generator import DocumentNumberGenerator

from .models import API_SCOPES, ApiCredential, IdempotencyRecord
from .services import generate_idempotently


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class ApiCredentialManagementTests(TestCase):
    """Cover one-time key disclosure and owner-isolated management."""

    def setUp(self):
        self.user = get_user_model().objects.create_user('owner', password='secret', is_staff=True)
        self.other_user = get_user_model().objects.create_user('other', password='secret', is_staff=True)
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
        self.assertEqual(response['Cache-Control'], 'no-store')
        listed = self.client.get('/api/v1/integrations/api-keys/').data['data']
        self.assertEqual(len(listed), 1)
        self.assertNotIn('api_key', listed[0])
        self.assertNotIn('key_hash', listed[0])

    def test_non_admin_cannot_access_any_management_action(self):
        self.user.is_staff = False
        self.user.save(update_fields=['is_staff'])
        credential, _ = ApiCredential.issue(owner=self.user, name='Existing key')
        base = '/api/v1/integrations/api-keys/'
        for method, url in [
            ('get', base), ('post', base), ('get', f'{base}scopes/'),
            ('get', f'{base}{credential.id}/'), ('post', f'{base}{credential.id}/revoke/'),
        ]:
            with self.subTest(method=method, url=url):
                self.assertEqual(getattr(self.client, method)(url).status_code, 403)
        credential.refresh_from_db()
        self.assertIsNone(credential.revoked_at)
        self.assertEqual(ApiCredential.objects.count(), 1)

    def test_anonymous_cannot_manage_keys(self):
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get('/api/v1/integrations/api-keys/').status_code, 401)

    def test_staff_list_remains_owner_isolated(self):
        own, _ = ApiCredential.issue(owner=self.user, name='Own key')
        other, _ = ApiCredential.issue(owner=self.other_user, name='Other key')
        response = self.client.get('/api/v1/integrations/api-keys/')
        self.assertEqual([item['id'] for item in response.data['data']], [str(own.id)])
        self.assertEqual(self.client.get(
            f'/api/v1/integrations/api-keys/{other.id}/'
        ).status_code, 404)

    def test_staff_can_discover_scopes_and_revoke_own_key_idempotently(self):
        response = self.client.get('/api/v1/integrations/api-keys/scopes/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual({item['code'] for item in response.data['data']}, set(API_SCOPES))
        credential, _ = ApiCredential.issue(owner=self.user, name='Own key')
        url = f'/api/v1/integrations/api-keys/{credential.id}/revoke/'
        first = self.client.post(url)
        second = self.client.post(url)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertFalse(first.data['data']['active'])
        self.assertEqual(first.data['data']['revoked_at'], second.data['data']['revoked_at'])
        self.assertNotIn('api_key', first.data['data'])

    def test_create_preserves_selected_format_and_expiration(self):
        document_format = DocumentFormat.objects.create(
            code='SELECTED', name='Selected', status='active', created_by=self.user,
        )
        expires_at = timezone.now() + timedelta(days=30)
        response = self.client.post('/api/v1/integrations/api-keys/', {
            'name': 'Scoped key', 'scopes': ['formats:read'],
            'allowed_formats': [str(document_format.id)], 'expires_at': expires_at.isoformat(),
        }, format='json')
        self.assertEqual(response.status_code, 201)
        credential = ApiCredential.objects.get()
        self.assertEqual(list(credential.allowed_formats.all()), [document_format])
        self.assertEqual(credential.expires_at, expires_at)
        self.assertEqual(response.data['data']['allowed_format_codes'], ['SELECTED'])
        self.assertFalse(response.data['data']['all_formats'])

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

    def test_deleted_allowlisted_format_does_not_grant_access_to_other_formats(self):
        self.credential.allowed_formats.set([self.document_format])
        other_document = self.other_format.get_generator().generate(user=self.user)
        self.document_format.delete()

        formats = self.client.get('/api/private/v1/formats/', **self.auth_headers)
        numbers = self.client.get('/api/private/v1/numbers/', **self.auth_headers)
        generated = self.generate(format_code='INVOICE', context_data={})
        changed = self.client.patch(
            f'/api/private/v1/numbers/{other_document.pk}/status/',
            {'status': 'used'}, format='json', **self.auth_headers,
        )

        self.assertEqual(formats.data['data'], [])
        self.assertEqual(numbers.data['data'], [])
        self.assertEqual(generated.status_code, 404)
        self.assertEqual(changed.status_code, 404)
        other_document.refresh_from_db()
        self.assertEqual(other_document.status, 'active')

    def test_mixed_deleted_and_live_allowlist_preserves_live_access(self):
        self.credential.allowed_formats.set([self.document_format, self.other_format])
        self.document_format.delete()
        response = self.generate(format_code='INVOICE', context_data={})
        self.assertEqual(response.status_code, 201)

    def test_explicit_empty_allowlist_still_allows_new_formats(self):
        self.credential.allowed_formats.clear()
        response = self.generate(format_code='INVOICE', context_data={})
        self.assertEqual(response.status_code, 201)

    def test_deleted_allowlist_is_not_reported_as_all_formats(self):
        from .serializers import ApiCredentialSerializer

        self.credential.allowed_formats.set([self.document_format])
        self.document_format.delete()
        self.assertFalse(ApiCredentialSerializer(self.credential).data['all_formats'])

    def test_replay_survives_new_required_context(self):
        first = self.generate()
        self.document_format.segments_config.append({
            'type': 'context', 'order': 5, 'config': {'key': 'department'},
        })
        self.document_format.save(update_fields=['segments_config'])

        replay = self.generate()
        fresh = self.generate(idempotency_key='new-order')

        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay['Idempotent-Replayed'], 'true')
        self.assertEqual(replay.data['data']['id'], first.data['data']['id'])
        self.assertEqual(fresh.status_code, 400)
        self.assertEqual(GeneratedDocument.objects.count(), 1)

    def test_replay_survives_archival_but_new_generation_is_rejected(self):
        first = self.generate()
        self.document_format.status = 'archived'
        self.document_format.save(update_fields=['status'])

        replay = self.generate()
        fresh = self.generate(idempotency_key='new-order')

        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.data['data']['id'], first.data['data']['id'])
        self.assertEqual(fresh.status_code, 404)
        self.assertEqual(IdempotencyRecord.objects.count(), 1)

    def test_archived_replay_with_changed_payload_still_conflicts(self):
        self.generate()
        self.document_format.status = 'archived'
        self.document_format.save(update_fields=['status'])
        response = self.generate(context_data={'branch': 'ANK'})
        self.assertEqual(response.status_code, 409)

    def test_replay_does_not_bypass_current_format_permissions(self):
        self.generate()
        self.credential.allowed_formats.set([self.other_format])
        self.assertEqual(self.generate().status_code, 404)

    def test_replay_does_not_bypass_revocation_or_scopes(self):
        self.generate()
        self.credential.scopes = ['numbers:read']
        self.credential.save(update_fields=['scopes'])
        self.assertEqual(self.generate().status_code, 403)
        self.credential.revoke()
        self.assertEqual(self.generate().status_code, 401)


class IdempotencyTransactionTests(TransactionTestCase):
    def test_concurrent_retries_issue_one_document(self):
        results = self._generate_concurrently(['same-request', 'same-request'])
        self.assertEqual({item[0] for item in results}, {'0001'})
        self.assertEqual(sorted(item[1] for item in results), [False, True])
        self.assertEqual(GeneratedDocument.objects.count(), 1)
        self.assertEqual(IdempotencyRecord.objects.count(), 1)

    def test_concurrent_distinct_requests_issue_distinct_numbers(self):
        results = self._generate_concurrently(['request-a', 'request-b'])
        self.assertEqual({item[0] for item in results}, {'0001', '0002'})
        self.assertEqual([item[1] for item in results], [False, False])
        self.assertEqual(GeneratedDocument.objects.count(), 2)
        self.assertEqual(IdempotencyRecord.objects.count(), 2)

    def _generate_concurrently(self, keys):
        user = get_user_model().objects.create_user('concurrent-owner')
        document_format = DocumentFormat.objects.create(
            code='CONCURRENT', name='Concurrent', status='active',
            segments_config=[{'type': 'sequence', 'config': {'padding': 4}}],
        )
        credential, _ = ApiCredential.issue(owner=user, name='Concurrent client')
        barrier = Barrier(len(keys))

        def issue(key):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                document, replayed = generate_idempotently(
                    credential=credential, idempotency_key=key,
                    document_format=document_format, payload={'format_code': 'CONCURRENT'},
                    user=user,
                )
                return document.document_number, replayed
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=len(keys)) as executor:
            futures = [executor.submit(issue, key) for key in keys]
            return [future.result(timeout=20) for future in futures]

    def test_number_and_retry_record_commit_before_format_lock_release(self):
        user = get_user_model().objects.create_user('transaction-owner')
        document_format = DocumentFormat.objects.create(
            code='ATOMIC', name='Atomic', status='active',
            segments_config=[{'type': 'sequence', 'config': {'padding': 4}}],
        )
        credential, _ = ApiCredential.issue(owner=user, name='Transaction client')
        lock_states = []
        original_lock = DocumentNumberGenerator.generation_lock

        @contextmanager
        def observe_lock(generator):
            lock_states.append(('acquire', connection.in_atomic_block))
            with original_lock(generator):
                yield
                lock_states.append(('release', connection.in_atomic_block))
                self.assertEqual(GeneratedDocument.objects.count(), 1)
                self.assertIsNotNone(IdempotencyRecord.objects.get().document_id)

        with patch.object(DocumentNumberGenerator, 'generation_lock', observe_lock):
            document, replayed = generate_idempotently(
                credential=credential, idempotency_key='atomic-request',
                document_format=document_format, payload={'format_code': 'ATOMIC'}, user=user,
            )

        self.assertFalse(replayed)
        self.assertEqual(document.document_number, '0001')
        self.assertEqual(lock_states, [('acquire', False), ('release', False)])


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
