import hashlib
import json

from django.db import IntegrityError, transaction

from .exceptions import Conflict
from .models import IdempotencyRecord


def request_digest(payload):
    """Build a deterministic, non-reversible fingerprint for retry validation."""
    canonical_payload = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
    )
    return hashlib.sha256(canonical_payload.encode('utf-8')).hexdigest()


def validate_idempotency_payload(record, payload):
    """Reject reuse of a retry key for a different normalized request body."""
    if record.request_hash != request_digest(payload):
        raise Conflict('This Idempotency-Key was already used with a different request body.')


def generate_idempotently(*, credential, idempotency_key, document_format, payload, user):
    """Commit the retry record and number before releasing the format lock."""
    generator = document_format.get_generator()
    # All generation paths take the format lock before database write locks.
    with generator.generation_lock():
        return _generate_idempotently(
            credential=credential,
            idempotency_key=idempotency_key,
            generator=generator,
            payload=payload,
            user=user,
        )


@transaction.atomic
def _generate_idempotently(*, credential, idempotency_key, generator, payload, user):
    payload_hash = request_digest(payload)
    created = False
    try:
        with transaction.atomic():
            record = IdempotencyRecord.objects.create(
                credential=credential,
                key=idempotency_key,
                request_hash=payload_hash,
            )
            created = True
    except IntegrityError:
        record = IdempotencyRecord.objects.select_for_update().get(
            credential=credential,
            key=idempotency_key,
        )

    validate_idempotency_payload(record, payload)
    if record.document_id:
        return record.document, True

    document = generator.generate_locked(
        context_data=payload.get('context_data'),
        user=user,
        metadata=payload.get('metadata'),
        source_credential=credential,
        external_reference=payload.get('external_reference', ''),
    )
    record.document = document
    record.save(update_fields=['document', 'updated_at'])
    return document, not created
