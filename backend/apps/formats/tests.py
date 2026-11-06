from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, close_old_connections, connection
from django.test import TestCase, TransactionTestCase, override_settings
from redis.exceptions import LockNotOwnedError

from apps.documents.models import GeneratedDocument
from apps.formats.engine.segments import DateSegment, SegmentConfig
from apps.formats.models import DocumentFormat, FormatCategory, FormatSequence


class ExpiredRedisLock:
    """Model Redis's token-safe release failure after its lease expires."""

    def acquire(self, **kwargs):
        return True

    def release(self):
        raise LockNotOwnedError('The test lock lease expired')


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class DocumentNumberGeneratorTests(TestCase):
    """Integration tests for unique document number generation."""

    def setUp(self):
        """Create an active invoice format used by every test."""
        self.user = get_user_model().objects.create_user('operator', password='secret')
        self.format = DocumentFormat.objects.create(
            code='INV',
            name='Invoice',
            status='active',
            sequence_start=7,
            sequence_step=2,
            segments_config=[
                {'type': 'static', 'order': 1, 'config': {'value': 'INV-'}},
                {'type': 'date', 'order': 2, 'config': {'format': 'YYYY'}},
                {'type': 'separator', 'order': 3, 'config': {'value': '-'}},
                {'type': 'sequence', 'order': 4, 'config': {'padding': 4}},
            ],
            created_by=self.user,
        )

    def test_generate_persists_unique_number_and_sequence(self):
        """Generated numbers are saved and sequence values increase atomically."""
        first = self.format.get_generator().generate(user=self.user)
        second = self.format.get_generator().generate(user=self.user)

        self.assertNotEqual(first.document_number, second.document_number)
        self.assertEqual(first.sequence_value, 7)
        self.assertEqual(second.sequence_value, 9)
        self.assertTrue(first.document_number.endswith('0007'))

    def test_preview_does_not_advance_sequence(self):
        """Preview renders a sample number without creating sequence state."""
        preview = self.format.generate_preview()

        self.assertIn('INV-', preview)
        self.assertFalse(FormatSequence.objects.exists())

    def test_monthly_reset_uses_period_specific_sequences(self):
        """Reset periods are isolated by period key in sequence storage."""
        self.format.sequence_reset_period = 'monthly'
        self.format.save(update_fields=['sequence_reset_period'])

        document = self.format.get_generator().generate(user=self.user)

        self.assertEqual(document.sequence_value, 7)
        self.assertEqual(FormatSequence.objects.count(), 1)

    def test_collision_advances_to_next_available_sequence(self):
        """A different format's existing number must not stall this sequence."""
        self.format.get_generator().generate(user=self.user)
        other_format = DocumentFormat.objects.create(
            code='OTHER', name='Other', status='active',
            sequence_start=7, sequence_step=2,
            segments_config=self.format.segments_config,
        )

        document = other_format.get_generator().generate(user=self.user)
        next_document = other_format.get_generator().generate(user=self.user)

        self.assertEqual(document.sequence_value, 9)
        self.assertEqual(next_document.sequence_value, 11)
        self.assertEqual(other_format.sequences.get().current_value, 11)

    def test_unrelated_integrity_error_propagates_and_rolls_back_sequence(self):
        """A NOT NULL violation must not become a duplicate retry exhaustion."""
        with self.assertRaises(IntegrityError):
            self.format.get_generator().generate(external_reference=None)

        self.assertFalse(GeneratedDocument.objects.exists())
        self.assertFalse(FormatSequence.objects.exists())

    def test_bulk_failure_rolls_back_documents_and_counter(self):
        """A failed later item leaves the batch's first number available."""
        self.format.validation_regex = r'.*0007'
        with self.assertRaises(ValueError):
            self.format.get_generator().bulk_generate(2, user=self.user)

        self.assertFalse(GeneratedDocument.objects.exists())
        self.assertFalse(FormatSequence.objects.exists())
        self.format.validation_regex = ''
        self.assertEqual(self.format.get_generator().generate().sequence_value, 7)

    def test_exhausted_collisions_do_not_advance_counter(self):
        """An impossible fixed format must roll back all failed candidates."""
        self.format.segments_config = [{'type': 'static', 'config': {'value': 'FIXED'}}]
        self.format.get_generator().generate()

        with self.assertRaises(RuntimeError):
            self.format.get_generator().generate()

        self.assertEqual(self.format.generated_documents.count(), 1)
        self.assertEqual(self.format.sequences.get().current_value, 7)

    @override_settings(TIME_ZONE='UTC')
    def test_day_month_year_date_format_renders_literal_date(self):
        """The builder's DDMMYYYY option has the same server-side meaning."""
        segment = DateSegment(SegmentConfig(format='DDMMYYYY'))
        rendered = segment.generate({'timestamp': datetime(2026, 11, 7, 12, tzinfo=timezone.utc)})
        self.assertEqual(rendered, '07112026')


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class DocumentFormatApiTests(TestCase):
    """Regression tests for document format API query annotations."""

    def setUp(self):
        """Create an authenticated API client and reusable document format."""
        from rest_framework.test import APIClient

        self.user = get_user_model().objects.create_user('apiuser', password='secret')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.format = DocumentFormat.objects.create(
            code='API',
            name='API Format',
            status='active',
            segments_config=[
                {'type': 'static', 'order': 1, 'config': {'value': 'API-'}},
                {'type': 'sequence', 'order': 2, 'config': {'padding': 3}},
            ],
            created_by=self.user,
        )

    def test_create_category_returns_wrapped_payload(self):
        """Category creation returns the API envelope expected by the UI."""
        response = self.client.post(
            '/api/v1/categories/',
            {'name': 'Finance', 'code': 'FINANCE'},
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data['success'])
        self.assertEqual(response.data['data']['name'], 'Finance')

    def test_duplicate_category_code_has_actionable_message(self):
        """Duplicate category codes explain which field must change."""
        FormatCategory.objects.create(name='Finance', code='FINANCE')

        response = self.client.post(
            '/api/v1/categories/',
            {'name': 'Finance Copy', 'code': 'FINANCE'},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('code:', response.data['error']['message'])
        self.assertIn('different name', response.data['error']['message'])

    def test_list_formats_does_not_collide_with_total_generated_property(self):
        """List endpoint must not annotate over the read-only model property."""
        response = self.client.get('/api/v1/formats/')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['success'])
        self.assertEqual(response.data['data'][0]['total_generated'], 0)

    def test_detail_and_preview_do_not_collide_with_total_generated_property(self):
        """Detail and preview endpoints must load annotated format instances."""
        detail_response = self.client.get(f'/api/v1/formats/{self.format.id}/')
        preview_response = self.client.get(f'/api/v1/formats/{self.format.id}/preview/')

        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(preview_response.status_code, 200)
        self.assertEqual(detail_response.data['total_generated'], 0)
        self.assertTrue(preview_response.data['success'])

    def test_bulk_generation_preserves_metadata_on_every_document(self):
        response = self.client.post(
            f'/api/v1/formats/{self.format.id}/generate/',
            {'count': 2, 'metadata': {'batch': 'review'}}, format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item['metadata'] for item in response.data['data']],
                         [{'batch': 'review'}, {'batch': 'review'}])
        self.assertEqual(list(self.format.generated_documents.values_list('metadata', flat=True)),
                         [{'batch': 'review'}, {'batch': 'review'}])

    def test_duplicate_format_can_be_repeated_without_code_collision(self):
        """Repeated copy requests create distinct drafts with the source settings."""
        copies = []
        for expected_code in ['API_COPY', 'API_COPY_2', 'API_COPY_3']:
            response = self.client.post(f'/api/v1/formats/{self.format.id}/duplicate/')
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.data['data']['code'], expected_code)
            copied_format = DocumentFormat.objects.get(pk=response.data['data']['id'])
            self.assertEqual(copied_format.status, 'draft')
            self.assertEqual(copied_format.segments_config, self.format.segments_config)
            self.assertEqual(copied_format.created_by, self.user)
            copies.append(copied_format.pk)

        self.assertEqual(len(set(copies)), 3)
        self.format.refresh_from_db()
        self.assertEqual(self.format.code, 'API')
        self.assertEqual(self.format.status, 'active')

    def test_duplicate_format_skips_soft_deleted_copy_codes(self):
        """Soft deletion retains unique codes and must not prevent future copies."""
        previous_copy = DocumentFormat.objects.create(code='API_COPY', name='Deleted copy')
        previous_copy.delete()

        response = self.client.post(f'/api/v1/formats/{self.format.id}/duplicate/')

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['data']['code'], 'API_COPY_2')
        previous_copy.refresh_from_db()
        self.assertTrue(previous_copy.is_deleted)

    def test_duplicate_maximum_length_format_keeps_copy_suffix_within_limits(self):
        """Copying valid maximum-length fields remains valid on PostgreSQL."""
        self.format.code = 'A' * 50
        self.format.name = 'N' * 100
        self.format.save(update_fields=['code', 'name'])

        for expected_code in ['A' * 45 + '_COPY', 'A' * 43 + '_COPY_2']:
            response = self.client.post(f'/api/v1/formats/{self.format.id}/duplicate/')
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.data['data']['code'], expected_code)
            self.assertEqual(response.data['data']['name'], 'N' * 92 + ' (Kopya)')

    def test_invalid_context_options_are_rejected_before_persistence(self):
        cases = [
            {'key': 'department', 'max_length': 'ten'},
            {'key': 'department', 'max_length': 0},
            {'key': 'department', 'max_length': -1},
            {'key': 'department', 'max_length': True},
            {'key': ['department']},
            {'key': 42},
            {'key': '   '},
        ]
        for index, config in enumerate(cases):
            with self.subTest(config=config):
                code = f'BAD_CONTEXT_{index}'
                response = self.client.post('/api/v1/formats/', {
                    'code': code, 'name': 'Invalid context',
                    'segments_config': [{'type': 'context', 'config': config}],
                }, format='json')
                self.assertEqual(response.status_code, 400)
                self.assertFalse(DocumentFormat.objects.filter(code=code).exists())

    def test_historical_invalid_context_does_not_break_list_or_detail(self):
        self.format.segments_config = [
            {'type': 'context', 'config': {'key': 'department', 'max_length': 'ten'}},
        ]
        self.format.save(update_fields=['segments_config'])

        listing = self.client.get('/api/v1/formats/')
        detail = self.client.get(f'/api/v1/formats/{self.format.id}/')

        self.assertEqual(listing.status_code, 200)
        self.assertIsNone(listing.data['data'][0]['preview'])
        self.assertEqual(detail.status_code, 200)
        self.assertIsNone(detail.data['preview'])
        self.assertEqual(detail.data['current_sequence'], 1)


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class DocumentGenerationTransactionTests(TransactionTestCase):
    """Exercise committed generation across cache leases and worker threads."""

    def setUp(self):
        self.format = DocumentFormat.objects.create(
            code='TRANSACTION', name='Transaction', status='active',
            segments_config=[{'type': 'sequence', 'config': {'padding': 3}}],
        )

    def test_expired_redis_lease_does_not_hide_committed_batch(self):
        with patch('apps.formats.engine.generator.cache.lock', create=True,
                   return_value=ExpiredRedisLock()):
            documents = self.format.get_generator().bulk_generate(2)

        self.assertFalse(connection.in_atomic_block)
        self.assertEqual([document.document_number for document in documents], ['001', '002'])
        self.assertEqual(self.format.generated_documents.count(), 2)
        self.assertEqual(self.format.sequences.get().current_value, 2)

    def test_expired_redis_lease_preserves_batch_failure_and_rollback(self):
        self.format.validation_regex = '001'
        with patch('apps.formats.engine.generator.cache.lock', create=True,
                   return_value=ExpiredRedisLock()):
            with self.assertRaisesMessage(ValueError, 'does not match validation pattern'):
                self.format.get_generator().bulk_generate(2)

        self.assertFalse(self.format.generated_documents.exists())
        self.assertFalse(self.format.sequences.exists())

    def test_same_format_batches_from_multiple_threads_remain_contiguous(self):
        ready = Barrier(3)

        def generate_batch():
            close_old_connections()
            try:
                ready.wait(timeout=10)
                return [document.sequence_value
                        for document in self.format.get_generator().bulk_generate(3)]
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=3) as executor:
            results = list(executor.map(lambda _: generate_batch(), range(3)))

        self.assertEqual(sorted(results), [[1, 2, 3], [4, 5, 6], [7, 8, 9]])
        self.assertEqual(self.format.generated_documents.count(), 9)
        self.assertEqual(self.format.sequences.get().current_value, 9)
