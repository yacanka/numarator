from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from django.core.management import call_command
from io import StringIO

from apps.documents.models import GeneratedDocument
from apps.formats.models import DocumentFormat, FormatCategory


class GeneratedDocumentModelTests(TestCase):
    """Tests for generated document lifecycle helpers."""

    def setUp(self):
        """Create a persisted generated document."""
        user = get_user_model().objects.create_user('operator')
        self.document_format = DocumentFormat.objects.create(
            code='PO',
            name='Purchase Order',
            status='active',
            segments_config=[{'type': 'static', 'config': {'value': 'PO'}}],
            created_by=user,
        )
        self.document = GeneratedDocument.objects.create(
            format=self.document_format,
            document_number='PO-1',
            sequence_value=1,
            generated_by=user,
            generated_at=timezone.now(),
        )

    def test_cancel_marks_document_invalid(self):
        """Cancelling records the reason and invalidates the document."""
        self.document.cancel(reason='Wrong customer')

        self.document.refresh_from_db()
        self.assertEqual(self.document.status, 'cancelled')
        self.assertFalse(self.document.is_valid)
        self.assertEqual(self.document.cancellation_reason, 'Wrong customer')

    def test_mark_used_updates_usage_timestamp(self):
        """Marking a document as used sets status and usage timestamp."""
        self.document.mark_used()

        self.document.refresh_from_db()
        self.assertEqual(self.document.status, 'used')
        self.assertIsNotNone(self.document.used_at)


class GeneratedDocumentApiTests(TestCase):
    """Tests for generated document API status management."""

    def setUp(self):
        """Create an authenticated API client and a document."""
        from rest_framework.test import APIClient

        self.user = get_user_model().objects.create_user('apiuser', password='secret')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.document_format = DocumentFormat.objects.create(
            code='API_DOC',
            name='API Document',
            status='active',
            segments_config=[{'type': 'static', 'config': {'value': 'API'}}],
            created_by=self.user,
        )
        self.document = GeneratedDocument.objects.create(
            format=self.document_format,
            document_number='API-1',
            sequence_value=1,
            generated_by=self.user,
            generated_at=timezone.now(),
        )

    def test_list_filters_documents_by_format(self):
        """Documents can be filtered by the selected format UUID."""
        other_format = DocumentFormat.objects.create(
            code='OTHER_DOC',
            name='Other API Document',
            status='active',
            segments_config=[{'type': 'static', 'config': {'value': 'OTHER'}}],
            created_by=self.user,
        )
        GeneratedDocument.objects.create(
            format=other_format,
            document_number='OTHER-1',
            sequence_value=1,
            generated_by=self.user,
            generated_at=timezone.now(),
        )

        response = self.client.get('/api/v1/documents/', {'format_id': str(self.document_format.id)})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['pagination']['count'], 1)
        self.assertEqual(
            response.data['data'][0]['document_number'],
            self.document.document_number,
        )

    def test_list_filters_documents_by_number(self):
        """Document number search is case-insensitive and returns only matches."""
        GeneratedDocument.objects.create(
            format=self.document_format,
            document_number='API-20',
            sequence_value=20,
            generated_by=self.user,
            generated_at=timezone.now(),
        )

        response = self.client.get('/api/v1/documents/', {'search': 'api-1'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['pagination']['count'], 1)
        self.assertEqual(response.data['data'][0]['document_number'], 'API-1')

    def test_list_filters_documents_by_format_category(self):
        """Category filtering spans formats and combines with existing filters."""
        category = FormatCategory.objects.create(name='Orders', code='ORDERS')
        other_category = FormatCategory.objects.create(name='Invoices', code='INVOICES')
        self.document_format.category = category
        self.document_format.save(update_fields=['category'])
        for code, format_category in [('SAME', category), ('OTHER', other_category), ('NONE', None)]:
            document_format = DocumentFormat.objects.create(
                code=code, name=code, category=format_category, created_by=self.user,
            )
            GeneratedDocument.objects.create(
                format=document_format, document_number=f'{code}-1',
                sequence_value=1, generated_by=self.user, status='used',
                generated_at=timezone.now(),
            )

        cases = [
            ({'category': category.id}, {'API-1', 'SAME-1'}),
            ({'category': category.id, 'format_id': str(self.document_format.id)}, {'API-1'}),
            ({'category': category.id, 'status': 'active', 'search': 'api'}, {'API-1'}),
            ({'category': other_category.id, 'format_id': str(self.document_format.id)}, set()),
            ({'category': 999999}, set()),
            ({'category': ''}, {'API-1', 'SAME-1', 'OTHER-1', 'NONE-1'}),
            ({}, {'API-1', 'SAME-1', 'OTHER-1', 'NONE-1'}),
        ]
        for filters, expected in cases:
            with self.subTest(filters=filters):
                response = self.client.get('/api/v1/documents/', filters)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data['pagination']['count'], len(expected))
                self.assertEqual(
                    {item['document_number'] for item in response.data['data']}, expected,
                )

    def test_list_rejects_invalid_category(self):
        """Malformed category IDs must not silently disable the filter."""
        response = self.client.get('/api/v1/documents/', {'category': 'invalid'})
        self.assertEqual(response.status_code, 400)

    def test_update_status_marks_document_used(self):
        """Status endpoint updates status and usage timestamp."""
        response = self.client.patch(
            f'/api/v1/documents/{self.document.id}/status/',
            {'status': 'used'},
            format='json',
        )

        self.document.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['data']['status'], 'used')
        self.assertIsNotNone(self.document.used_at)

    def test_update_status_rejects_unknown_status(self):
        """Status endpoint validates the requested lifecycle status."""
        response = self.client.patch(
            f'/api/v1/documents/{self.document.id}/status/',
            {'status': 'unknown'},
            format='json',
        )

        self.assertEqual(response.status_code, 400)

    def test_legacy_validation_reports_lifecycle_validity(self):
        for document_status, expected_valid in [
            ('active', True), ('cancelled', False), ('used', False), ('expired', False),
        ]:
            with self.subTest(status=document_status):
                self.document.change_status(document_status)
                response = self.client.get('/api/v1/documents/validate/API-1/')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data['data']['valid'], expected_valid)
                self.assertTrue(response.data['data']['exists'])

    def test_query_validation_accepts_all_supported_separators(self):
        for number in ['API/1', 'API.1', 'API\\1', 'API|1', 'API:1', 'API_1', 'API-1']:
            with self.subTest(number=number):
                self.document.document_number = number
                self.document.save(update_fields=['document_number'])
                response = self.client.get('/api/v1/documents/validate/', {'number': number})
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.data['data']['valid'])
                self.assertEqual(response.data['data']['document']['document_number'], number)

    def test_query_validation_reports_missing_number(self):
        response = self.client.get('/api/v1/documents/validate/', {'number': 'MISSING/1'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['data'], {'exists': False, 'valid': False})

    def test_query_validation_requires_nonempty_bounded_number(self):
        for params in [{}, {'number': ''}, {'number': 'x' * 201}]:
            with self.subTest(params=params):
                response = self.client.get('/api/v1/documents/validate/', params)
                self.assertEqual(response.status_code, 400)


class DocumentSchemaTests(TestCase):
    def test_validation_routes_do_not_block_production_schema_checks(self):
        # Native startup treats schema warnings as errors, including colliding
        # operation IDs for the legacy and query-based validation routes.
        call_command('spectacular', fail_on_warn=True, stdout=StringIO(), stderr=StringIO())
