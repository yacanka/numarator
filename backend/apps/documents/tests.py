from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

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
