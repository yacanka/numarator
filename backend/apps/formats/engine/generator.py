import logging
import threading
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone

from .segments import BaseSegment, ChecksumSegment, SegmentConfig, get_segment_class

logger = logging.getLogger(__name__)
_local_locks: dict[str, threading.Lock] = {}
_local_locks_guard = threading.Lock()


class DocumentNumberGenerator:
    """Generate unique document numbers from a persisted format definition."""

    LOCK_PREFIX = 'docnum:lock:'
    LOCK_TIMEOUT = 30
    MAX_DUPLICATE_RETRIES = 5

    def __init__(self, format_instance):
        """Build a generator for one document format instance."""
        self.format = format_instance
        self.segments = self._build_segments()

    def generate(
        self,
        context_data: Optional[Dict[str, Any]] = None,
        user=None,
        metadata: Optional[Dict[str, Any]] = None,
        source_credential=None,
        external_reference: str = '',
    ) -> 'GeneratedDocument':
        """Generate and persist one unique document number."""
        with self._generation_lock():
            return self._generate_with_retries(
                context_data,
                user,
                metadata,
                source_credential,
                external_reference,
            )

    def preview(self, context_data: Optional[Dict[str, Any]] = None) -> str:
        """Render a non-persistent preview using the sequence start value."""
        context = self._build_context(timezone.now(), self.format.sequence_start, context_data)
        return self._render_number(context)

    def bulk_generate(
        self,
        count: int,
        context_data: Optional[Dict[str, Any]] = None,
        user=None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List['GeneratedDocument']:
        """Generate multiple document numbers within the configured limit."""
        if count > 1000:
            raise ValueError('Bulk generate limit is 1000')
        return [self.generate(context_data, user, metadata) for _ in range(count)]

    def _build_segments(self) -> List[BaseSegment]:
        segments = []
        for segment_config in sorted(self.format.segments_config, key=self._segment_order):
            segment_type = segment_config.get('type')
            options = segment_config.get('config', {})
            segments.append(get_segment_class(segment_type)(SegmentConfig(**options)))
        return segments

    @staticmethod
    def _segment_order(segment_config: Dict[str, Any]) -> int:
        return int(segment_config.get('order', 0))

    @contextmanager
    def _generation_lock(self):
        lock_key = f'{self.LOCK_PREFIX}{self.format.id}'
        lock = getattr(cache, 'lock', lambda *args, **kwargs: None)(lock_key, self.LOCK_TIMEOUT)
        if lock:
            with self._redis_lock(lock):
                yield
            return
        with self._thread_lock(lock_key):
            yield

    @contextmanager
    def _redis_lock(self, lock):
        acquired = lock.acquire(blocking=True, blocking_timeout=10)
        if not acquired:
            raise RuntimeError('Could not acquire lock for document generation')
        try:
            yield
        finally:
            lock.release()

    @contextmanager
    def _thread_lock(self, lock_key: str):
        with _local_locks_guard:
            lock = _local_locks.setdefault(lock_key, threading.Lock())
        with lock:
            yield

    def _generate_with_retries(
        self,
        context_data,
        user,
        metadata,
        source_credential,
        external_reference,
    ):
        for attempt in range(self.MAX_DUPLICATE_RETRIES):
            try:
                return self._generate_internal(
                    context_data,
                    user,
                    metadata,
                    source_credential,
                    external_reference,
                )
            except IntegrityError:
                logger.warning('Duplicate document number retry=%s', attempt + 1)
        raise RuntimeError('Could not generate a unique document number')

    @transaction.atomic
    def _generate_internal(
        self,
        context_data,
        user,
        metadata,
        source_credential,
        external_reference,
    ):
        from apps.documents.models import GeneratedDocument

        now = timezone.now()
        sequence_value = self._get_next_sequence(now)
        context = self._build_context(now, sequence_value, context_data, user)
        document_number = self._render_number(context)
        self._validate_document_number(document_number)
        return GeneratedDocument.objects.create(
            format=self.format,
            document_number=document_number,
            sequence_value=sequence_value,
            context_data=context_data or {},
            generated_by=user,
            generated_at=now,
            metadata=metadata or {},
            source_credential=source_credential,
            external_reference=external_reference,
        )

    def _build_context(self, now, sequence_value, context_data=None, user=None) -> Dict[str, Any]:
        return {
            'timestamp': now,
            'sequence_value': sequence_value,
            'context_data': context_data or {},
            'format': self.format,
            'user': user,
        }

    def _render_number(self, context: Dict[str, Any]) -> str:
        parts = []
        for segment in self.segments:
            if isinstance(segment, ChecksumSegment):
                context['partial_number'] = ''.join(parts)
            parts.append(segment.generate(context))
        return ''.join(parts)

    def _validate_document_number(self, document_number: str) -> None:
        if not self.format.validation_regex:
            return
        import re

        if not re.fullmatch(self.format.validation_regex, document_number):
            raise ValueError('Generated number does not match validation pattern')

    def _get_next_sequence(self, now) -> int:
        from apps.formats.models import FormatSequence

        period_key = self._get_period_key(now, self.format.sequence_reset_period)
        sequence, created = FormatSequence.objects.select_for_update().get_or_create(
            format=self.format,
            period_key=period_key,
            defaults=self._sequence_defaults(),
        )
        if created:
            return sequence.current_value
        sequence.current_value += sequence.step
        sequence.save(update_fields=['current_value', 'updated_at'])
        return sequence.current_value

    def _sequence_defaults(self) -> Dict[str, int]:
        return {
            'current_value': self.format.sequence_start,
            'step': self.format.sequence_step,
        }

    def _get_period_key(self, now, reset_period: str) -> str:
        local_now = timezone.localtime(now)
        period_map = {
            'never': 'ALL',
            'daily': local_now.strftime('%Y%m%d'),
            'weekly': local_now.strftime('%G-W%V'),
            'monthly': local_now.strftime('%Y%m'),
            'quarterly': f'{local_now.year}-Q{((local_now.month - 1) // 3) + 1}',
            'yearly': local_now.strftime('%Y'),
        }
        return period_map.get(reset_period, 'ALL')
