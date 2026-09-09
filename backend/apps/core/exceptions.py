# apps/core/exceptions.py
from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
import logging

logger = logging.getLogger(__name__)


class DocumentNumberError(Exception):
    """Base exception for document number errors"""
    pass


class FormatValidationError(DocumentNumberError):
    """Format validation failed"""
    pass


class SequenceExhaustedError(DocumentNumberError):
    """Sequence counter exhausted"""
    pass


class DuplicateNumberError(DocumentNumberError):
    """Generated number already exists"""
    pass


def custom_exception_handler(exc, context):
    """Wrap DRF errors in the API envelope used by the frontend."""
    response = exception_handler(exc, context)

    if response is not None:
        response.data = {
            'success': False,
            'error': {
                'code': response.status_code,
                'message': _get_error_message(response.data),
                'details': response.data,
            }
        }
    else:
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        response = Response(
            {
                'success': False,
                'error': {
                    'code': 500,
                    'message': 'Internal server error',
                    'details': str(exc) if isinstance(exc, DocumentNumberError) else None,
                }
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    return response


def _get_error_message(data):
    """Extract a human-readable message from nested validation details."""
    if isinstance(data, dict):
        if 'detail' in data:
            return str(data['detail'])
        field_message = _first_field_error(data)
        return field_message or 'Validation error'
    if isinstance(data, list):
        return str(data[0]) if data else 'Error occurred'
    return str(data)


def _first_field_error(data):
    """Return the first field-specific validation message."""
    for field_name, messages in data.items():
        message = _stringify_error(messages)
        if message:
            return f'{field_name}: {message}'
    return None


def _stringify_error(value):
    """Convert validation payload fragments to displayable text."""
    if isinstance(value, list):
        return str(value[0]) if value else ''
    if isinstance(value, dict):
        return _first_field_error(value) or ''
    return str(value)
