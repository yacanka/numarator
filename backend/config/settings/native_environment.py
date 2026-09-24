"""Explicit external configuration for the native production profile only."""

import os
from pathlib import Path

from decouple import Config, RepositoryEnv
from django.core.exceptions import ImproperlyConfigured

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def external_path(value: str, label: str) -> Path:
    path = Path(value).expanduser()
    if not value or not path.is_absolute() or path.resolve().is_relative_to(REPOSITORY_ROOT):
        raise ImproperlyConfigured(f'{label} must be an absolute path outside the repository')
    if path.is_symlink():
        raise ImproperlyConfigured(f'{label} cannot be a symbolic link')
    return path.resolve()


env_file = external_path(os.environ.get('NUMARATOR_ENV_FILE', ''), 'NUMARATOR_ENV_FILE')
if not env_file.is_file():
    raise ImproperlyConfigured('NUMARATOR_ENV_FILE must exist')
config = Config(RepositoryEnv(str(env_file)))
data_dir = external_path(config('NUMARATOR_DATA_DIR', default=''), 'NUMARATOR_DATA_DIR')
for relative in ('logs', 'logs/app.log', 'staticfiles', 'media', 'numarator.sqlite3', '.native.lock'):
    if (data_dir / relative).is_symlink():
        raise ImproperlyConfigured('Native runtime data paths cannot be symbolic links')
