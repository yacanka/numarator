"""Validate signing keys and persist a private key for local development."""

import os
import secrets
import tempfile
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured


def validate_secret_key(key: str) -> str:
    if len(key.encode('utf-8')) < 32:
        raise ImproperlyConfigured(
            'SECRET_KEY must contain at least 32 bytes; configure a cryptographically '
            'random key in the environment or backend/.env.'
        )
    return key


def development_secret_key(key: str, base_dir: Path) -> str:
    """Reuse a configured key or atomically create a persistent local-only key."""
    if key:
        return validate_secret_key(key)

    path = base_dir / '.dev-secret-key'
    if not path.exists():
        # Publish a complete, owner-only file so concurrent starts share one key.
        with tempfile.NamedTemporaryFile(dir=base_dir) as temporary:
            temporary.write(secrets.token_urlsafe(48).encode('ascii'))
            temporary.flush()
            try:
                os.link(temporary.name, path)
            except FileExistsError:
                pass
    return validate_secret_key(path.read_text(encoding='utf-8'))
