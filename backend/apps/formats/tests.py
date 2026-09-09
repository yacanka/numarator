from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from apps.formats.models import DocumentFormat, FormatCategory, FormatSequence


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
