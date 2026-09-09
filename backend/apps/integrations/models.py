import hashlib
import secrets

from django.conf import settings
from django.db import IntegrityError, models, transaction
from django.utils import timezone

from apps.core.models import TimeStampedModel


API_SCOPES = {
    'formats:read': 'Aktif formatları ve önizlemelerini okuyabilir.',
    'numbers:generate': 'Yeni numara üretebilir.',
    'numbers:read': 'Üretilmiş numaraları sorgulayabilir ve doğrulayabilir.',
    'numbers:status': 'Numaraları kullanıldı veya iptal edildi olarak işaretleyebilir.',
}


class ApiCredential(TimeStampedModel):
    """A revocable, hashed credential used by one external application."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='api_credentials',
    )
    name = models.CharField(max_length=100)
    key_prefix = models.CharField(max_length=32, unique=True, db_index=True)
    key_hash = models.CharField(max_length=64)
    scopes = models.JSONField(default=list)
    allowed_formats = models.ManyToManyField(
        'formats.DocumentFormat',
        blank=True,
        related_name='api_credentials',
    )
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} ({self.key_prefix})'

    @classmethod
    def issue(cls, *, owner, name, scopes=None, expires_at=None):
        """Create a credential and return its one-time plaintext API key."""
        for _ in range(5):
            public_id = secrets.token_hex(6)
            key_prefix = f'dnk_{public_id}'
            raw_key = f'{key_prefix}_{secrets.token_urlsafe(32)}'
            try:
                with transaction.atomic():
                    credential = cls.objects.create(
                        owner=owner,
                        name=name,
                        key_prefix=key_prefix,
                        key_hash=cls.hash_key(raw_key),
                        scopes=scopes if scopes is not None else [],
                        expires_at=expires_at,
                    )
            except IntegrityError:
                continue
            return credential, raw_key
        raise RuntimeError('A unique API key could not be generated.')

    @staticmethod
    def hash_key(raw_key):
        """Return a non-reversible digest suitable for credential lookup."""
        return hashlib.sha256(raw_key.encode('utf-8')).hexdigest()

    @property
    def is_usable(self):
        """Return whether this key and its owner may authenticate now."""
        if self.revoked_at or self.owner is None or not self.owner.is_active:
            return False
        return self.expires_at is None or self.expires_at > timezone.now()

    def revoke(self):
        """Permanently disable this credential."""
        if self.revoked_at is None:
            self.revoked_at = timezone.now()
            self.save(update_fields=['revoked_at', 'updated_at'])


class IdempotencyRecord(TimeStampedModel):
    """Bind one client retry key and request body to its generated number."""

    credential = models.ForeignKey(
        ApiCredential,
        on_delete=models.PROTECT,
        related_name='idempotency_records',
    )
    key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)
    document = models.ForeignKey(
        'documents.GeneratedDocument',
        on_delete=models.PROTECT,
        related_name='idempotency_records',
        null=True,
        blank=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['credential', 'key'],
                name='unique_idempotency_key_per_credential',
            ),
        ]
